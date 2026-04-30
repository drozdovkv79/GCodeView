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
    """Исправляет крякозябры в русских IFC (latin1 -> cp1251/utf8)"""
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
    """Возвращает RGB из материалов IFC или палитры типов"""
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
    finished = pyqtSignal(list, dict)
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

            results, tree_data = [], {}
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
                        name = fix_ifc_encoding(product.Name) or f"ID:{product.id()}"
                        results.append(
                            (
                                v,
                                f,
                                get_element_color(product),
                                product.is_a(),
                                name,
                                product.id(),
                            )
                        )
                        tree_data.setdefault(product.is_a(), []).append(
                            (name, product.id())
                        )
                except:
                    continue

            self.log.emit(f"✅ Готово. Загружено {len(results)} мешей.")
            self.finished.emit(results, tree_data)
        except Exception as e:
            self.error.emit(str(e))


class IFCViewerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IFC Viewer + PyVista")
        self.resize(1400, 900)

        self.plotter = pyvistaqt.QtInteractor(self)
        self.setCentralWidget(self.plotter)
        self.plotter.set_background("white")
        self.plotter.add_axes()
        self.plotter.show_grid()
        self.plotter.add_text(
            "Загрузите IFC файл через кнопку 📂",
            font_size=14,
            color="gray",
            position="upper_edge",
        )

        self.tree_dock = QDockWidget("📦 Структура модели", self)
        self.tree_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Тип", "Количество"])
        self.tree_widget.setSortingEnabled(True)
        self.tree_widget.itemClicked.connect(
            self._focus_on_tree_item
        )  # ✅ Клик по дереву
        self.tree_dock.setWidget(self.tree_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tree_dock)

        toolbar = QToolBar("Основные действия")
        toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(toolbar)

        self.act_open = QAction("📂 Открыть IFC", self)
        self.act_open.triggered.connect(self.load_ifc)
        toolbar.addAction(self.act_open)

        self.act_clip = QAction("📦 Куб сечения", self)
        self.act_clip.setCheckable(True)
        self.act_clip.toggled.connect(self.toggle_box_clip)
        toolbar.addAction(self.act_clip)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.log_label = QLabel("Ожидание файла...")
        self.statusBar.addPermanentWidget(self.log_label, 1)

        # 📊 Хранилища состояния
        self.original_meshes = {}  # {actor: original_color}
        self.pid_to_info = {}  # {pid: (actor, center, color)}
        self.current_hover_actor = None
        self.box_widget = None
        self.clip_active = False
        self.loader = None

        # 🖱️ Инициализация ховера
        self.plotter.enable_cell_picking(
            callback=lambda: None, show_message=False, use_actor=True
        )
        self.plotter.iren.add_observer("MouseMoveEvent", self._on_hover)

    def load_ifc(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Выберите IFC файл", "", "IFC Files (*.ifc *.ifczip *.ifcXML)"
        )
        if not filepath:
            return

        self.plotter.clear()
        self.tree_widget.clear()
        self.original_meshes.clear()
        self.pid_to_info.clear()
        self.current_hover_actor = None
        self.clip_active = False
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

    def _on_load_finished(self, results, tree_data):
        self.progress.close()
        self.log_label.setText("✅ Загрузка завершена. Построение сцены...")
        QApplication.processEvents()

        for v, f, color, p_type, name, pid in results:
            faces_vtk = np.column_stack([np.full(len(f), 3, dtype=np.int32), f]).ravel()
            mesh = pv.PolyData(v, faces_vtk)
            actor = self.plotter.add_mesh(
                mesh,
                color=color,
                smooth_shading=True,
                show_edges=False,
                pickable=True,
                name=f"mesh_{pid}",
            )

            self.original_meshes[actor] = color
            self.pid_to_info[pid] = (actor, mesh.center, color)

        self.tree_widget.clear()
        for p_type in sorted(tree_data.keys()):
            items = tree_data[p_type]
            parent = QTreeWidgetItem(
                self.tree_widget, [fix_ifc_encoding(p_type), str(len(items))]
            )
            for name, pid in items:
                child = QTreeWidgetItem(parent, [name, ""])
                child.setData(
                    0, Qt.ItemDataRole.UserRole, pid
                )  # ✅ Привязка PID к элементу
        self.tree_widget.expandToDepth(1)
        self.plotter.reset_camera()
        self.log_label.setText(
            f"🎨 Отображено {len(results)} элементов. Цвета и hover активны."
        )

    def _on_load_error(self, err):
        self.progress.close()
        QMessageBox.critical(self, "Ошибка IFC", f"Не удалось загрузить файл:\n{err}")
        self.log_label.setText("❌ Ошибка загрузки")

    def _focus_on_tree_item(self, item, column):
        """Фокус камеры на элемент при клике в дереве"""
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        if not pid or pid not in self.pid_to_info:
            return

        actor, center, orig_color = self.pid_to_info[pid]

        # 1. Подсветка элемента
        self._set_actor_color(actor, (1.0, 0.85, 0.0), 0.85)
        self.plotter.render()

        # 2. Плавный фокус камеры
        bounds = actor.GetBounds()
        diag = np.sqrt(sum((bounds[2 * i + 1] - bounds[2 * i]) ** 2 for i in range(3)))
        dist = max(diag * 3.0, 5.0)

        cam = self.plotter.camera
        cam.focal_point = center
        cam.position = [center[0], center[1] - dist, center[2] + dist * 0.5]
        cam.up = [0, 0, 1]
        self.plotter.render()

        # 3. Возврат цвета через 1.2 сек
        QTimer.singleShot(
            1200, lambda a=actor, c=orig_color: self._set_actor_color(a, c, 1.0)
        )

    def _set_actor_color(self, actor, color, opacity):
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(opacity)

    def _on_hover(self, obj, event):
        """Интерактивная подсветка при наведении мыши"""
        try:
            picker = self.plotter.picker
            x, y = self.plotter.iren.get_event_position()
            picker.Pick(int(x), int(y), 0, self.plotter.renderer)

            actor = picker.GetActor()
            if actor and actor in self.original_meshes:
                if self.current_hover_actor != actor:
                    if self.current_hover_actor:
                        self._set_actor_color(
                            self.current_hover_actor,
                            self.original_meshes[self.current_hover_actor],
                            1.0,
                        )
                    self.current_hover_actor = actor
                    self._set_actor_color(actor, (1.0, 0.85, 0.0), 0.9)
                    self.plotter.render()
            else:
                if self.current_hover_actor:
                    self._set_actor_color(
                        self.current_hover_actor,
                        self.original_meshes[self.current_hover_actor],
                        1.0,
                    )
                    self.current_hover_actor = None
                    self.plotter.render()
        except Exception:
            pass  # Игнорируем ошибки пикера при взаимодействии с виджетами

    def toggle_box_clip(self, checked):
        self.clip_active = checked
        if checked:
            if not self.original_meshes:
                QMessageBox.warning(self, "Предупреждение", "Сначала загрузите модель.")
                self.act_clip.setChecked(False)
                return

            all_bounds = [a.GetBounds() for a in self.original_meshes.keys()]
            if not all_bounds:
                return
            gb = (
                min(b[0] for b in all_bounds),
                max(b[1] for b in all_bounds),
                min(b[2] for b in all_bounds),
                max(b[3] for b in all_bounds),
                min(b[4] for b in all_bounds),
                max(b[5] for b in all_bounds),
            )
            m = [(gb[1] - gb[0]) * 0.05, (gb[3] - gb[2]) * 0.05, (gb[5] - gb[4]) * 0.05]
            init_bounds = (
                gb[0] + m[0],
                gb[1] - m[0],
                gb[2] + m[1],
                gb[3] - m[1],
                gb[4] + m[2],
                gb[5] - m[2],
            )

            self.box_widget = self.plotter.add_box_widget(
                callback=self._apply_box_clip,
                bounds=init_bounds,
                interaction_event="end",
                factor=0.5,
            )
            self.log_label.setText(
                "✂️ Куб сечения активен. Перемещайте/масштабируйте грани"
            )
        else:
            if self.box_widget:
                self.box_widget.Off()
                self.plotter.remove_widget(self.box_widget)
                self.box_widget = None
            self.plotter.clear()
            self.original_meshes.clear()
            self.pid_to_info.clear()
            self.current_hover_actor = None
            self.load_ifc()  # Перезагружаем полную модель

    def _apply_box_clip(self, widget):
        if not widget or not self.original_meshes:
            return
        try:
            bounds = widget.bounds
            self.plotter.clear()
            self.original_meshes.clear()
            self.pid_to_info.clear()
            self.current_hover_actor = None

            clipped_count = 0
            for pid, (actor, center, color) in list(self.pid_to_info.items()):
                # Быстрый чек по bounding box перед клиппингом
                if not self._bounds_intersect(actor.GetBounds(), bounds):
                    continue

                clipped = actor.GetInputData().clip_box(bounds=bounds)
                if clipped.n_points > 0:
                    new_actor = self.plotter.add_mesh(
                        clipped,
                        color=color,
                        smooth_shading=True,
                        show_edges=False,
                        pickable=True,
                    )
                    self.original_meshes[new_actor] = color

            self.plotter.add_axes()
            self.plotter.show_grid()
            self.plotter.render()
            self.log_label.setText(
                f"✂️ Применено сечение. Видимо: {len(self.original_meshes)} элементов"
            )
        except Exception as e:
            self.log_label.setText(f"⚠️ Ошибка сечения: {e}")

    def _bounds_intersect(self, b1, b2):
        return not (
            b1[1] < b2[0]
            or b1[0] > b2[1]
            or b1[3] < b2[2]
            or b1[2] > b2[3]
            or b1[5] < b2[4]
            or b1[4] > b2[5]
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = IFCViewerGUI()
    window.show()
    sys.exit(app.exec())
