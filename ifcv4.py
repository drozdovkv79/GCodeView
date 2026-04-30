import sys
import time

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


class FastIFCLoader(QThread):
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
            self.log.emit("📂 Открытие IFC файла...")
            ifc_file = ifcopenshell.open(self.filepath)

            # Получаем все продукты сразу
            products = ifc_file.by_type("IfcProduct")
            total_products = len(products)
            self.log.emit(
                f"🔍 Найдено {total_products} элементов. Начинаем быструю триангуляцию..."
            )

            settings = ifcopenshell.geom.settings()
            settings.set("USE_WORLD_COORDS", True)
            settings.set("APPLY_DEFAULT_MATERIALS", False)
            # Отключаем сварку вершин для скорости (merge_points=False аналог)
            settings.set("WELD_VERTICES", False)

            all_verts = []
            all_faces = []
            all_colors = []
            tree_data = {}
            vertex_offset = 0

            processed = 0
            skipped = 0

            # Используем итератор для экономии памяти
            for product in products:
                if product.is_a() in EXCLUDED_TYPES:
                    continue

                try:
                    # create_shape все еще самый надежный способ получить геометрию
                    # Но мы минимизируем обработку внутри цикла
                    shape = ifcopenshell.geom.create_shape(settings, product)
                    if not shape.geometry:
                        skipped += 1
                        continue

                    v = np.array(shape.geometry.verts, dtype=np.float32).reshape(-1, 3)
                    f = np.array(shape.geometry.faces, dtype=np.int32).reshape(-1, 3)

                    if len(v) == 0 or len(f) == 0:
                        skipped += 1
                        continue

                    all_verts.append(v)
                    all_faces.append(f + vertex_offset)

                    # Быстрый цвет по типу (без глубокого парсинга материалов для скорости)
                    p_type = product.is_a()
                    color = self._get_fast_color(p_type, product)

                    n_faces = len(f)
                    # Повторяем цвет для каждой грани
                    all_colors.append(np.tile(color, (n_faces, 1)))

                    vertex_offset += len(v)

                    name = fix_ifc_encoding(product.Name) or f"ID:{product.id()}"
                    tree_data.setdefault(p_type, []).append((name, product.id()))

                except Exception:
                    skipped += 1
                    continue

                processed += 1
                if processed % 1000 == 0:
                    elapsed = time.time() - start_time
                    self.progress.emit(
                        processed,
                        total_products,
                        f"⏳ Обработано: {processed}, Время: {elapsed:.1f}s",
                    )
                    # Даем UI обновиться
                    if self.isInterruptionRequested():
                        return

            if not all_verts:
                self.error.emit("Не найдено геометрии")
                return

            self.log.emit("🧩 Объединение массивов NumPy...")
            # Самое быстрое объединение
            combined_verts = np.vstack(all_verts)
            combined_faces = np.vstack(all_faces)
            combined_colors = np.vstack(all_colors)

            total_time = time.time() - start_time
            self.log.emit(
                f"✅ Готово за {total_time:.2f} сек. Вершин: {len(combined_verts)}, Граней: {len(combined_faces)}"
            )
            self.finished.emit(
                combined_verts, combined_faces, combined_colors, tree_data
            )

        except Exception as e:
            self.error.emit(str(e))

    def _get_fast_color(self, p_type, product):
        """Упрощенная логика цвета для скорости"""
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
        if p_type in TYPE_COLORS:
            return TYPE_COLORS[p_type]
        # Детерминированный хеш для остальных
        h = hash(product.id()) & 0xFFFFFF
        return ((h & 0xFF) / 255, ((h >> 8) & 0xFF) / 255, ((h >> 16) & 0xFF) / 255)


class IFCViewerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fast IFC Viewer (100k elements)")
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

        self.progress = QProgressDialog("Triangulating...", "Cancel", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.canceled.connect(
            lambda: self.loader and self.loader.requestInterruption()
        )

        self.loader = FastIFCLoader(filepath)
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

        # Быстрый рендер без сложных теней для максимальной скорости FPS
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

        self.tree_widget.clear()
        for p_type in sorted(tree_data.keys()):
            items = tree_data[p_type]
            parent = QTreeWidgetItem(
                self.tree_widget, [fix_ifc_encoding(p_type), str(len(items))]
            )
        self.tree_widget.expandToDepth(1)

        self.plotter.reset_camera()
        self.plotter.render_window.Render()
        self.log_label.setText(f"✅ Done. {len(verts)} verts.")

    def _on_load_error(self, err):
        self.progress.close()
        QMessageBox.critical(self, "Error", str(err))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IFCViewerGUI()
    window.show()
    sys.exit(app.exec())
