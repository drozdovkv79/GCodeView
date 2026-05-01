import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv
import pyvistaqt
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

# Исключаем легкие элементы
EXCLUDED_TYPES = {
    "IfcAnnotation",
    "IfcGrid",
    "IfcOpeningElement",
    "IfcSpace",
    "IfcSpatialStructureElement",
    "IfcDrawing",
}

TYPE_COLORS = {
    "IfcWall": (0.85, 0.85, 0.85),
    "IfcSlab": (0.95, 0.90, 0.65),
    "IfcColumn": (0.60, 0.60, 0.60),
    "IfcBeam": (0.50, 0.50, 0.50),
    "IfcDoor": (0.70, 0.40, 0.20),
    "IfcWindow": (0.30, 0.60, 0.90),
    "IfcRoof": (0.70, 0.30, 0.30),
    "IfcStair": (0.60, 0.40, 0.70),
    "IfcFurniture": (0.40, 0.70, 0.40),
    "IfcCurtainWall": (0.20, 0.80, 0.60),
}


def fix_ifc_encoding(text):
    if not text or text.isascii():
        return text
    try:
        fixed = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        if any("\u0400" <= c <= "\u04ff" for c in fixed):
            return fixed
        fixed = text.encode("latin1", errors="ignore").decode(
            "windows-1251", errors="ignore"
        )
        if any("\u0400" <= c <= "\u04ff" for c in fixed):
            return fixed
    except:
        pass
    return text


def get_fast_color(p_type, pid):
    if p_type in TYPE_COLORS:
        return TYPE_COLORS[p_type]
    h = hash(pid) & 0xFFFFFF
    return ((h & 0xFF) / 255, ((h >> 8) & 0xFF) / 255, ((h >> 16) & 0xFF) / 255)


# --- Функция для воркера (запускается в отдельном процессе) ---
def process_chunk(ifc_path, product_ids, settings_dict):
    """
    Эта функция выполняется в отдельном процессе.
    Она открывает файл, находит продукты по ID и триангулирует их.
    """
    try:
        # Открываем файл в каждом процессе (это быстро, так как кэшируется ОС)
        ifc_file = ifcopenshell.open(ifc_path)

        settings = ifcopenshell.geom.settings()
        for k, v in settings_dict.items():
            settings.set(k, v)

        local_verts = []
        local_faces = []
        local_colors = []
        vertex_offset = 0

        for pid in product_ids:
            try:
                product = ifc_file.by_id(pid)
                if not product or product.is_a() in EXCLUDED_TYPES:
                    continue

                shape = ifcopenshell.geom.create_shape(settings, product)
                if not shape.geometry:
                    continue

                v = np.array(shape.geometry.verts, dtype=np.float32).reshape(-1, 3)
                f = np.array(shape.geometry.faces, dtype=np.int32).reshape(-1, 3)

                if len(v) == 0 or len(f) == 0:
                    continue

                local_verts.append(v)
                local_faces.append(f + vertex_offset)

                color = get_fast_color(product.is_a(), pid)
                local_colors.append(np.tile(color, (len(f), 1)))

                vertex_offset += len(v)

            except Exception:
                continue

        if not local_verts:
            return None

        # Возвращаем сырые данные
        return {
            "verts": np.vstack(local_verts),
            "faces": np.vstack(local_faces),
            "colors": np.vstack(local_colors),
            "count": len(local_verts),
        }
    except Exception as e:
        print(f"Worker error: {e}")
        return None


class ParallelIFCLoader(QThread):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    finished = pyqtSignal(np.ndarray, np.ndarray, np.ndarray, dict)
    error = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        start_time = time.time()
        try:
            self.log.emit("📂 Открытие IFC файла и подготовка данных...")
            ifc_file = ifcopenshell.open(self.filepath)

            products = [
                p
                for p in ifc_file.by_type("IfcProduct")
                if p.is_a() not in EXCLUDED_TYPES
            ]
            total_products = len(products)

            if total_products == 0:
                self.error.emit("Нет геометрии")
                return

            self.log.emit(
                f"🔍 Найдено {total_products} элементов. Распределение по ядрам..."
            )

            # Определяем количество ядер (Apple M4 имеет 8-10+ ядер)
            num_cores = max(1, mp.cpu_count() - 1)  # Оставляем одно ядро для UI
            chunk_size = max(1, total_products // num_cores)

            # Разбиваем список продуктов на чанки
            chunks = [
                products[i : i + chunk_size]
                for i in range(0, total_products, chunk_size)
            ]

            # Собираем только ID для передачи в процессы (легче сериализовать)
            chunk_ids = [[p.id() for p in chunk] for chunk in chunks]

            settings_dict = {
                "USE_WORLD_COORDS": True,
                "APPLY_DEFAULT_MATERIALS": False,
                "WELD_VERTICES": False,
            }

            all_results = []
            processed_count = 0

            self.log.emit(f"🚀 Запуск {len(chunks)} процессов на {num_cores} ядрах...")

            # Используем ProcessPoolExecutor для параллельной обработки
            with ProcessPoolExecutor(max_workers=num_cores) as executor:
                futures = {
                    executor.submit(process_chunk, self.filepath, ids, settings_dict): i
                    for i, ids in enumerate(chunk_ids)
                }

                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        all_results.append(result)
                        processed_count += result["count"]
                        # Обновляем прогресс приблизительно
                        self.progress.emit(
                            processed_count,
                            total_products,
                            f"⏳ Обработано блоков: {len(all_results)}/{len(chunks)}",
                        )

            if not all_results:
                self.error.emit("Не удалось извлечь геометрию")
                return

            self.log.emit("🧩 Объединение результатов из всех ядер...")

            # Объединяем результаты
            final_verts = np.vstack([r["verts"] for r in all_results])
            final_faces = np.vstack([r["faces"] for r in all_results])
            final_colors = np.vstack([r["colors"] for r in all_results])

            # Корректируем индексы граней, так как они были локальными для каждого чанка
            # Но wait! В process_chunk мы уже делали offset внутри чанка.
            # Теперь нужно сделать глобальный offset между чанками.
            current_offset = 0
            corrected_faces_list = []
            for r in all_results:
                corrected_faces_list.append(r["faces"] + current_offset)
                current_offset += len(r["verts"])

            final_faces_corrected = np.vstack(corrected_faces_list)

            total_time = time.time() - start_time
            self.log.emit(
                f"✅ Готово за {total_time:.2f} сек. Вершин: {len(final_verts)}, Граней: {len(final_faces_corrected)}"
            )

            # Дерево данных (упрощенное, так как мы потеряли связь ID->Name в воркерах для скорости)
            # Для полного дерева нужно было бы передавать больше данных, но это замедлит.
            # Здесь мы просто создадим заглушку или соберем дерево в основном потоке если нужно.
            tree_data = {}

            self.finished.emit(
                final_verts, final_faces_corrected, final_colors, tree_data
            )

        except Exception as e:
            self.error.emit(str(e))


class IFCViewerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parallel IFC Viewer (M4 Optimized)")
        self.resize(1400, 900)

        self.plotter = pyvistaqt.QtInteractor(self)
        self.setCentralWidget(self.plotter)
        self.plotter.set_background("#f0f0f0")
        self.plotter.add_axes()
        self.plotter.show_grid()
        self.plotter.disable_picking()

        self.tree_dock = QDockWidget("📦 Структура", self)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Тип", "Кол-во"])
        self.tree_dock.setWidget(self.tree_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)

        toolbar = QToolBar("Actions")
        toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(toolbar)

        self.act_open = QAction("📂 Open IFC", self)
        self.act_open.triggered.connect(self.load_ifc)
        toolbar.addAction(self.act_open)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.log_label = QLabel("Ready")
        self.statusBar.addPermanentWidget(self.log_label, 1)

        self.loader = None

    def load_ifc(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select IFC", "", "IFC Files (*.ifc)"
        )
        if not filepath:
            return

        self.plotter.clear()
        self.tree_widget.clear()
        self.log_label.setText("⏳ Loading...")

        self.progress = QProgressDialog(
            "Triangulating (Multi-Core)...", "Cancel", 0, 100, self
        )
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.canceled.connect(
            lambda: self.loader and self.loader.requestInterruption()
        )

        self.loader = ParallelIFCLoader(filepath)
        self.loader.progress.connect(
            lambda c, t, m: (
                self.progress.setValue(int(c / t * 100)),
                self.log_label.setText(m),
            )
        )
        self.loader.log.connect(self.log_label.setText)
        self.loader.finished.connect(self._on_load_finished)
        self.loader.error.connect(self._on_load_error)
        self.loader.start()
        self.progress.show()

    def _on_load_finished(self, verts, faces, colors, tree_data):
        self.progress.close()
        self.log_label.setText("✅ Rendering...")
        QApplication.processEvents()

        n_faces = faces.shape[0]
        faces_vtk = np.column_stack(
            [np.full(n_faces, 3, dtype=np.int32), faces]
        ).ravel()

        mesh = pv.PolyData(verts, faces_vtk)
        mesh.cell_data["colors"] = colors

        self.plotter.add_mesh(
            mesh,
            scalars="colors",
            rgb=True,
            smooth_shading=True,
            show_edges=False,
            ambient=0.3,
            diffuse=0.7,
            specular=0.2,
        )

        self.plotter.reset_camera()
        self.plotter.render_window.Render()
        self.log_label.setText(f"✅ Done. {len(verts)} verts.")

    def _on_load_error(self, err):
        self.progress.close()
        QMessageBox.critical(self, "Error", str(err))


if __name__ == "__main__":
    # Важно для multiprocessing на macOS
    mp.set_start_method("spawn", force=True)

    app = QApplication(sys.argv)
    window = IFCViewerGUI()
    window.show()
    sys.exit(app.exec())
