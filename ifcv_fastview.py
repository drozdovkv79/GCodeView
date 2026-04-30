import sys

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv
import pyvistaqt
from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
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

# 🎨 Палитра по типам IFC
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


def get_element_color(product):
    """Получает цвет из IFC или палитры"""
    try:
        if product.HasAssociations:
            for rel in product.HasAssociations:
                if rel.is_a("IfcRelAssociatesMaterial"):
                    mat = rel.RelatingMaterial
                    if mat.is_a("IfcStyledItem"):
                        for s in mat.Styles:
                            if s.is_a("IfcSurfaceStyle"):
                                for style in s.Styles:
                                    if style.is_a("IfcSurfaceStyleRendering"):
                                        c = style.SurfaceColour
                                        if c:
                                            return (c.Red, c.Green, c.Blue)
    except:
        pass
    p_type = product.is_a()
    if p_type in TYPE_COLORS:
        return TYPE_COLORS[p_type]
    h = hash(product.id()) & 0xFFFFFF
    return ((h & 0xFF) / 255, ((h >> 8) & 0xFF) / 255, ((h >> 16) & 0xFF) / 255)


class IFCLoader(QThread):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    # Возвращаем: вершины, грани, цвета (для скаляров), инфо для дерева
    finished = pyqtSignal(np.ndarray, np.ndarray, np.ndarray, dict)
    error = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            self.log.emit("📂 Открытие IFC файла...")
            ifc_file = ifcopenshell.open(self.filepath)
            products = [
                p
                for p in ifc_file.by_type("IfcProduct")
                if p.is_a() not in EXCLUDED_TYPES
            ]
            self.log.emit(
                f"🔍 Найдено {len(products)} элементов. Извлечение геометрии..."
            )

            settings = ifcopenshell.geom.settings()
            settings.set("USE_WORLD_COORDS", True)
            settings.set("APPLY_DEFAULT_MATERIALS", False)

            all_verts = []
            all_faces = []
            all_colors = []  # Список цветов для каждого элемента
            tree_data = {}

            vertex_offset = 0

            for i, product in enumerate(products):
                self.progress.emit(
                    i + 1, len(products), f"⏳ {fix_ifc_encoding(product.is_a())}"
                )
                try:
                    shape = ifcopenshell.geom.create_shape(settings, product)
                    if not shape.geometry:
                        continue

                    v = np.array(shape.geometry.verts, dtype=np.float32).reshape(-1, 3)
                    f = np.array(shape.geometry.faces, dtype=np.int32).reshape(-1, 3)

                    if len(v) > 0 and len(f) > 0:
                        all_verts.append(v)
                        all_faces.append(f + vertex_offset)

                        # Получаем цвет элемента
                        color = get_element_color(product)
                        # Сохраняем цвет для каждой грани этого элемента (Cell Data)
                        # Это эффективнее, чем хранить цвет для каждой вершины
                        n_faces_in_element = len(f)
                        element_colors = np.tile(color, (n_faces_in_element, 1))
                        all_colors.append(element_colors)

                        vertex_offset += len(v)

                        name = fix_ifc_encoding(product.Name) or f"ID:{product.id()}"
                        tree_data.setdefault(product.is_a(), []).append(
                            (name, product.id())
                        )
                except:
                    continue

            if not all_verts:
                self.error.emit("Не найдено геометрии")
                return

            combined_verts = np.vstack(all_verts)
            combined_faces = np.vstack(all_faces)
            combined_colors = np.vstack(all_colors)  # Форма: (N_graney, 3)

            self.log.emit(
                f"✅ Готово. Вершин: {len(combined_verts)}, Граней: {len(combined_faces)}"
            )
            self.finished.emit(
                combined_verts, combined_faces, combined_colors, tree_data
            )
        except Exception as e:
            self.error.emit(str(e))


class IFCViewerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IFC Viewer (Fast + Colors + Shadows)")
        self.resize(1400, 900)

        self.plotter = pyvistaqt.QtInteractor(self)
        self.setCentralWidget(self.plotter)
        self.plotter.set_background(
            "#f0f0f0"
        )  # Светло-серый фон для лучшего контраста теней
        self.plotter.add_axes()
        self.plotter.show_grid()

        # ⚡ ВАЖНО: Отключаем picking для скорости, так как у нас один огромный меш
        self.plotter.disable_picking()

        self.tree_dock = QDockWidget("📦 Структура модели", self)
        self.tree_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Тип", "Количество"])
        self.tree_widget.setSortingEnabled(True)
        self.tree_widget.itemClicked.connect(
            lambda item, col: self.log_label.setText(f"Тип: {item.text(0)}")
        )
        self.tree_dock.setWidget(self.tree_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)

        toolbar = QToolBar("Основные действия")
        toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(toolbar)

        self.act_open = QAction("📂 Открыть IFC", self)
        self.act_open.triggered.connect(self.load_ifc)
        toolbar.addAction(self.act_open)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.log_label = QLabel("Ожидание файла...")
        self.statusBar.addPermanentWidget(self.log_label, 1)

        self.loader = None
        self.main_actor = None

    def load_ifc(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Выберите IFC файл", "", "IFC Files (*.ifc *.ifczip *.ifcXML)"
        )
        if not filepath:
            return

        self.plotter.clear()
        self.tree_widget.clear()
        self.main_actor = None
        self.plotter.add_axes()
        self.plotter.show_grid()
        self.log_label.setText("⏳ Инициализация загрузки...")

        self.progress = QProgressDialog("Загрузка геометрии...", "Отмена", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.canceled.connect(
            lambda: self.loader and self.loader.requestInterruption()
        )

        self.loader = IFCLoader(filepath)
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
        self.log_label.setText("✅ Загрузка завершена. Рендеринг с тенями...")
        QApplication.processEvents()

        # Формируем грани для VTK
        n_faces = faces.shape[0]
        faces_vtk = np.column_stack(
            [np.full(n_faces, 3, dtype=np.int32), faces]
        ).ravel()

        # Создаем единый меш
        mesh = pv.PolyData(verts, faces_vtk)

        # 🎨 Добавляем цвета как Cell Data (данные для граней)
        # Это позволяет VTK интерполировать цвета или использовать их напрямую
        mesh.cell_data["colors"] = colors

        # 🌟 Настройка материалов и света для реалистичности
        # Используем PBR (Physically Based Rendering) если поддерживается, иначе Phong

        # Добавляем основной направленный свет для теней
        light = pv.Light(position=(10, 10, 10), focal_point=(0, 0, 0), intensity=1.0)
        self.plotter.add_light(light)

        # Добавляем заполняющий свет, чтобы тени не были черными
        fill_light = pv.Light(
            position=(-10, -10, 5), focal_point=(0, 0, 0), intensity=0.3, color="white"
        )
        self.plotter.add_light(fill_light)

        # Добавляем меш с настройками материала
        # scalars="colors" указывает использовать наши данные
        # rgb=True говорит, что скаляры уже являются RGB значениями (0-1)
        # smooth_shading=True включает интерполяцию нормалей (блики)
        # specular и roughness добавляют реализм
        self.main_actor = self.plotter.add_mesh(
            mesh,
            scalars="colors",
            rgb=True,
            smooth_shading=True,
            specular=0.1,  # Сила блика
            specular_power=0,  # Резкость блика
            roughness=0.5,  # Шероховатость поверхности
            metallic=0.5,  # Неметаллический материал
            show_edges=False,
            ambient=0.2,  # Фоновое освещение
        )

        # Заполняем дерево
        self.tree_widget.clear()
        for p_type in sorted(tree_data.keys()):
            items = tree_data[p_type]
            parent = QTreeWidgetItem(
                self.tree_widget, [fix_ifc_encoding(p_type), str(len(items))]
            )
            for name, pid in items:
                child = QTreeWidgetItem(parent, [name, ""])
                child.setData(0, Qt.ItemDataRole.UserRole, pid)
        self.tree_widget.expandToDepth(1)

        self.plotter.reset_camera()
        self.plotter.render_window.Render()

        self.log_label.setText(f"✅ Модель загружена. Цвета и тени активны.")

    def _on_load_error(self, err):
        self.progress.close()
        QMessageBox.critical(self, "Ошибка IFC", f"Не удалось загрузить файл:\n{err}")
        self.log_label.setText("❌ Ошибка загрузки")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = IFCViewerGUI()
    window.show()
    sys.exit(app.exec())
