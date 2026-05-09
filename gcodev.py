import sys

import numpy as np
import pyvista as pv
import vtk
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
)
from pyvistaqt import BackgroundPlotter


class UltraFastParser:
    def __init__(self):
        self.points = []
        self.lines = []

    def parse(self, file_path):
        self.points = []
        self.lines = []
        try:
            with open(file_path, "r") as f:
                current_path = []
                curr = [0.0, 0.0, 0.0]

                for line in f:
                    if not line or line.startswith((";", "(", "%")):
                        continue

                    parts = line.split()
                    new_pos = list(curr)
                    is_g1 = False
                    is_move = False

                    for p in parts:
                        if p.startswith("G1"):
                            is_g1 = True
                        elif p.startswith("X"):
                            new_pos[0] = float(p[1:])
                            is_move = True
                        elif p.startswith("Y"):
                            new_pos[1] = float(p[1:])
                            is_move = True
                        elif p.startswith("Z"):
                            new_pos[2] = float(p[1:])
                            is_move = True

                    if is_g1 and is_move:
                        if not current_path:
                            current_path.append(curr)
                        current_path.append(new_pos)
                        curr = new_pos
                    elif is_move:
                        if len(current_path) > 1:
                            self._add_polyline(current_path)
                        current_path = []
                        curr = new_pos

                if len(current_path) > 1:
                    self._add_polyline(current_path)

            self.all_points = np.vstack(self.points).astype(np.float32)
            self.all_lines = np.concatenate(self.lines).astype(np.int32)
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False

    def _add_polyline(self, path_points):
        start_idx = sum(len(p) for p in self.points)
        pts = np.array(path_points, dtype=np.float32)
        self.points.append(pts)
        n_pts = len(pts)
        indices = np.arange(start_idx, start_idx + n_pts)
        self.lines.append(np.hstack([[n_pts], indices]))


class GCodeApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("G-Code Viewer")
        self.resize(1280, 720)

        self.parser = UltraFastParser()
        self.plotter = BackgroundPlotter(show=False)
        self.plotter.background_color = "silver"
        self.plotter.enable_anti_aliasing()
        self.plotter.render_window.SetMultiSamples(2)
        self.plotter.enable_terrain_style(mouse_wheel_zooms=1.035)
        self.plotter.camera_position = "iso"

        # Настройка сетки
        self.plotter.show_grid(
            color=(80, 80, 90),
            grid="back",
            show_yaxis=True,
            location="outer",
            ticks="both",
            xtitle="X (мм)",
            ytitle="Y (мм)",
            ztitle="Z (мм)",
            font_size=14,
        )

        # Настройка толщины линий сетки
        try:
            axes_actor = self.plotter.renderer.axes_actor
            if axes_actor:
                axes_actor.SetGridLineWidth(2)
                axes_actor.SetAxisLinesWidth(2)
        except:
            pass

        self.plotter.show()

        # --- UI setup ---
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left panel
        panel = QVBoxLayout()

        # Load button
        btn_load = QPushButton("Загрузить файл")
        btn_load.clicked.connect(self.load_file)
        panel.addWidget(btn_load)

        # Line thickness
        thick_layout = QHBoxLayout()
        thick_layout.addWidget(QLabel("Толщина линии:"))
        self.thick_input = QLineEdit()
        self.thick_input.setFixedWidth(40)
        self.thick_input.setText("50")
        self.thick_input.editingFinished.connect(self.update_slider_from_input)
        thick_layout.addWidget(self.thick_input)

        self.thick_slider = QSlider(Qt.Horizontal)
        self.thick_slider.setRange(1, 100)
        self.thick_slider.setValue(50)
        self.thick_slider.valueChanged.connect(self.update_appearance)
        thick_layout.addWidget(self.thick_slider)
        panel.addLayout(thick_layout)

        # Model color
        btn_color = QPushButton("Цвет модели")
        btn_color.clicked.connect(self.change_color)
        panel.addWidget(btn_color)

        # Opacity slider
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Прозрачность:"))
        self.opacity_input = QLineEdit()
        self.opacity_input.setFixedWidth(40)
        self.opacity_input.setText("100")
        self.opacity_input.editingFinished.connect(self.update_opacity_from_input)
        opacity_layout.addWidget(self.opacity_input)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.update_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        panel.addLayout(opacity_layout)

        # Zoom
        zoom_layout = QGridLayout()
        self.zoom_label = QLabel("zoom [1]:")
        zoom_layout.addWidget(self.zoom_label, 0, 0)
        zoom_slider = QSlider(Qt.Horizontal)
        zoom_slider.setMinimum(1)
        zoom_slider.setMaximum(60)
        zoom_slider.setValue(30)
        zoom_slider.valueChanged.connect(self.update_zoom)
        zoom_layout.addWidget(zoom_slider, 0, 1)
        panel.addLayout(zoom_layout)

        # Camera buttons
        camera_buttons = ["front", "back", "left", "right", "up", "down", "iso"]
        camera_layout = QHBoxLayout()
        for name in camera_buttons:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _, n=name: self.set_camera_position(n))
            camera_layout.addWidget(btn)
        panel.addLayout(camera_layout)

        # Screenshot
        btn_screenshot = QPushButton("Скриншот")
        btn_screenshot.clicked.connect(self.get_screenshot)
        panel.addWidget(btn_screenshot)

        panel.addWidget(QFrame(frameShape=QFrame.HLine))

        # Measurement tools
        measure_layout = QHBoxLayout()
        self.btn_measure = QPushButton("Измерить")
        self.btn_measure.setCheckable(True)
        self.btn_measure.clicked.connect(self.toggle_measurement)
        measure_layout.addWidget(self.btn_measure)

        self.btn_reset_measure = QPushButton("Сбросить измерение")
        self.btn_reset_measure.clicked.connect(self.reset_measurement)
        self.btn_reset_measure.setEnabled(False)
        measure_layout.addWidget(self.btn_reset_measure)
        panel.addLayout(measure_layout)

        self.measure_label = QLabel("Расстояние: —")
        panel.addWidget(self.measure_label)

        panel.addWidget(QFrame(frameShape=QFrame.HLine))

        # Section tools group (НОВАЯ ЛОГИКА)
        section_group = QGroupBox("Сечение модели")
        section_layout = QVBoxLayout()

        # Кнопка 1: Отобразить плоскость сечения
        self.btn_show_plane = QPushButton("1. Отобразить плоскость сечения")
        self.btn_show_plane.clicked.connect(self.show_section_plane)
        section_layout.addWidget(self.btn_show_plane)

        # Кнопка 2: Рассечь модель справа от сечения
        self.btn_clip_right = QPushButton("2. Рассечь модель справа")
        self.btn_clip_right.clicked.connect(lambda: self.apply_clipping("right"))
        self.btn_clip_right.setEnabled(False)
        section_layout.addWidget(self.btn_clip_right)

        # Кнопка 3: Рассечь модель слева от сечения
        self.btn_clip_left = QPushButton("3. Рассечь модель слева")
        self.btn_clip_left.clicked.connect(lambda: self.apply_clipping("left"))
        self.btn_clip_left.setEnabled(False)
        section_layout.addWidget(self.btn_clip_left)

        # Кнопка 4: Скрыть плоскость сечения
        self.btn_hide_plane = QPushButton("4. Скрыть плоскость сечения")
        self.btn_hide_plane.clicked.connect(self.hide_section_plane)
        self.btn_hide_plane.setEnabled(False)
        section_layout.addWidget(self.btn_hide_plane)

        # Кнопка 5: Сбросить настройки сечения
        self.btn_reset_section = QPushButton("5. Сбросить настройки сечения")
        self.btn_reset_section.clicked.connect(self.reset_section)
        section_layout.addWidget(self.btn_reset_section)

        section_group.setLayout(section_layout)
        panel.addWidget(section_group)

        panel.addStretch()
        main_layout.addLayout(panel, 1)
        main_layout.addWidget(self.plotter.interactor, 4)

        # State variables
        self.measuring_mode = False
        self.measure_points = []
        self.measure_actors = []

        self.mesh = None
        self.actor = None
        self.tube_filter = None
        self.section_plane_widget = None
        self.original_bounds = None
        self.original_mapper = None
        self.original_mesh = None
        self.clip_filter = None
        self.section_active = False  # Плоскость отображена
        self.is_clipped = False  # Модель рассечена

    # ========== Section Widget (НОВАЯ ЛОГИКА) ==========
    def show_section_plane(self):
        """Отобразить плоскость сечения (без выполнения самого сечения)"""
        if not self.actor:
            print("Сначала загрузите модель")
            return

        # Если плоскость уже существует, просто показываем её
        if self.section_plane_widget:
            self.section_plane_widget.On()
            self.section_active = True
            self.btn_hide_plane.setEnabled(True)
            return

        # Store original bounds if not already stored
        if self.original_bounds is None:
            self.original_bounds = self.actor.bounds

        # Store original mapper
        if self.original_mapper is None:
            self.original_mapper = self.actor.GetMapper()

        # Store original mesh for clipping
        if self.original_mesh is None:
            self.original_mesh = self.actor.mapper.dataset

        # Создаем плоскость для визуализации
        center = (
            (self.original_bounds[0] + self.original_bounds[1]) / 2,
            (self.original_bounds[2] + self.original_bounds[3]) / 2,
            (self.original_bounds[4] + self.original_bounds[5]) / 2,
        )

        self.section_plane_widget = self.plotter.add_plane_widget(
            callback=self.on_plane_moved,
            bounds=self.original_bounds,
            color="cyan",
            normal=(1, 0, 0),
            origin=center,
            # opacity=0.5,
        )

        self.section_active = True

        # Включаем кнопки управления
        self.btn_clip_right.setEnabled(True)
        self.btn_clip_left.setEnabled(True)
        self.btn_hide_plane.setEnabled(True)

        print(
            "Плоскость сечения отображена. Перемещайте её мышью, затем нажмите 'Рассечь модель'"
        )

    def on_plane_moved(self, plane_widget, event):
        """Callback при перемещении плоскости (только сохраняем позицию)"""
        if self.section_plane_widget:
            # Просто сохраняем, что плоскость переместилась
            # Если нужно, можно отображать координаты
            try:
                origin = plane_widget.GetOrigin()
                normal = plane_widget.GetNormal()
                # Можно добавить отображение координат в статусную строку
                # print(f"Plane position: {origin}, normal: {normal}")
            except:
                pass

    def apply_clipping(self, side="right"):
        """Рассечь модель с указанной стороны от плоскости"""
        if not self.section_plane_widget:
            print("Сначала отобразите плоскость сечения (кнопка 1)")
            return

        if not self.actor:
            return

        # Получаем параметры плоскости
        try:
            if hasattr(self.section_plane_widget, "GetOrigin"):
                origin = self.section_plane_widget.GetOrigin()
                normal = self.section_plane_widget.GetNormal()
            else:
                widget = (
                    self.section_plane_widget[0]
                    if isinstance(self.section_plane_widget, tuple)
                    else self.section_plane_widget
                )
                origin = widget.GetOrigin()
                normal = widget.GetNormal()
        except Exception as e:
            print(f"Error getting plane parameters: {e}")
            return

        # Создаем плоскость для обрезки
        clip_plane = vtk.vtkPlane()
        clip_plane.SetOrigin(origin)
        clip_plane.SetNormal(normal)

        # Применяем обрезку
        if self.clip_filter is None:
            self.clip_filter = vtk.vtkClipPolyData()

        self.clip_filter.SetInputData(self.original_mesh)
        self.clip_filter.SetClipFunction(clip_plane)

        # SetInsideOut в зависимости от выбранной стороны
        if side == "right":
            self.clip_filter.SetInsideOut(True)  # Показываем правую сторону
            print("Модель рассечена: показана правая часть")
        else:  # 'left'
            self.clip_filter.SetInsideOut(False)  # Показываем левую сторону
            print("Модель рассечена: показана левая часть")

        self.clip_filter.Update()

        # Создаем новый mapper с обрезанными данными
        clipped_mapper = vtk.vtkPolyDataMapper()
        clipped_mapper.SetInputConnection(self.clip_filter.GetOutputPort())
        self.actor.SetMapper(clipped_mapper)

        self.is_clipped = True
        self.plotter.render()

    def hide_section_plane(self):
        """Скрыть плоскость сечения, но оставить модель рассеченной"""
        if self.section_plane_widget:
            self.section_plane_widget.Off()  # SetVisibility(False)
            self.section_active = False
            self.btn_hide_plane.setEnabled(False)
            self.btn_show_plane.setEnabled(True)
            print("Плоскость сечения скрыта")

    def reset_section(self):
        """Полностью сбросить настройки сечения"""
        # Восстанавливаем оригинальную модель
        if self.actor and self.original_mapper:
            self.actor.SetMapper(self.original_mapper)
            self.is_clipped = False

        # Удаляем плоскость сечения
        if self.section_plane_widget:
            try:
                self.plotter.remove_actor(self.section_plane_widget)
            except:
                pass
            self.section_plane_widget = None

        # Сбрасываем состояние
        self.section_active = False
        self.is_clipped = False

        # Обновляем состояние кнопок
        self.btn_clip_right.setEnabled(False)
        self.btn_clip_left.setEnabled(False)
        self.btn_hide_plane.setEnabled(False)
        self.btn_show_plane.setEnabled(True)

        self.plotter.render()
        print("Настройки сечения сброшены")

    # ========== Measurement ==========
    def toggle_measurement(self, checked):
        if checked:
            try:
                self.plotter.disable_picking()
            except:
                pass
            self.measuring_mode = True
            self.plotter.enable_point_picking(
                callback=self.on_measure_pick,
                left_clicking=True,
                show_message=False,
                use_picker=False,
            )
            self.btn_measure.setText("Измерение активно (щелкните 2 точки)")
        else:
            self.measuring_mode = False
            self.plotter.disable_picking()
            self.btn_measure.setText("Измерить")

    def on_measure_pick(self, point):
        if not self.measuring_mode:
            return
        if len(self.measure_points) >= 2:
            return

        self.measure_points.append(point)
        sphere = pv.Sphere(radius=2, center=point)
        actor = self.plotter.add_mesh(sphere, color="red", pickable=False)
        self.measure_actors.append(actor)

        if len(self.measure_points) == 2:
            p1, p2 = self.measure_points
            dist = np.linalg.norm(np.array(p1) - np.array(p2))
            self.measure_label.setText(f"Расстояние: {dist:.2f} мм")

            line = pv.Line(p1, p2)
            line_actor = self.plotter.add_mesh(
                line, color="cyan", line_width=4, pickable=False
            )
            self.measure_actors.append(line_actor)

            mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2)
            text_actor = self.plotter.add_point_labels(
                [mid],
                [f"{dist:.2f} mm"],
                font_size=16,
                point_color="yellow",
                text_color="black",
                always_visible=True,
                name="measure_label",
            )
            self.measure_actors.append(text_actor)

            self.btn_reset_measure.setEnabled(True)
            self.btn_measure.setChecked(False)
            self.toggle_measurement(False)

    def reset_measurement(self):
        for actor in self.measure_actors:
            self.plotter.remove_actor(actor)
        self.measure_actors.clear()
        self.measure_points.clear()
        self.measure_label.setText("Расстояние: —")
        self.btn_reset_measure.setEnabled(False)
        if self.measuring_mode:
            self.btn_measure.setChecked(False)
            self.toggle_measurement(False)

    # ========== Opacity ==========
    def update_opacity(self, value):
        self.opacity_input.setText(str(value))
        if self.actor:
            opacity = value / 100.0
            self.actor.GetProperty().SetOpacity(opacity)
            self.plotter.render()

    def update_opacity_from_input(self):
        try:
            value = int(self.opacity_input.text())
            value = max(0, min(100, value))
            self.opacity_slider.setValue(value)
        except ValueError:
            self.opacity_input.setText(str(self.opacity_slider.value()))

    # ========== File operations ==========
    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code")
        if path:
            if self.parser.parse(path):
                self.render_model()
                n = len(self.parser.all_points)
                self.setWindowTitle(f"G-Code Viewer: [{n}] {path}")
                self.plotter.reset_camera()
                self.reset_measurement()
                # Сбрасываем сечение при загрузке нового файла
                self.reset_section()

    def get_screenshot(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Save File", "", "PNG Files (*.png);;All Files (*)", options=options
        )
        if fileName:
            self.plotter.screenshot(fileName)

    def set_camera_position(self, position_name):
        camera_positions = {
            "back": [0, 1, 0],
            "up": [0, 0, 1],
            "right": [1, 0, 0],
            "left": [-1, 0, 0],
            "down": [0, 0, -1],
            "front": [0, -1, 0],
            "iso": [1, 1, 1],
        }
        if position_name in camera_positions:
            self.plotter.camera_position = camera_positions[position_name]
            self.plotter.render()

    def update_zoom(self, value):
        self.zoom_label.setText(f"zoom: [{value}]")
        self.plotter.camera.view_angle = value
        self.plotter.render()

    def render_model(self):
        if self.actor:
            self.plotter.remove_actor(self.actor)

        spl = pv.PolyData(self.parser.all_points)
        n_pts = len(self.parser.all_points)
        lines = np.hstack([[n_pts], np.arange(n_pts)])
        spl.lines = lines

        self.tube_filter = vtk.vtkTubeFilter()
        self.tube_filter.SetInputData(spl)
        self.tube_filter.SetRadius(2.5)
        self.tube_filter.SetNumberOfSides(8)
        self.tube_filter.Update()
        tube = pv.wrap(self.tube_filter.GetOutput())

        # Store original mesh for clipping
        self.original_mesh = tube

        self.actor = self.plotter.add_mesh(
            tube,
            name="3d_panel",
            color="beige",
            smooth_shading=True,
            show_edges=False,
            specular=0.1,
            specular_power=1,
            diffuse=0.8,
            ambient=0.3,
            pickable=True,
        )
        self.update_opacity(self.opacity_slider.value())
        self.plotter.enable_depth_peeling(number_of_peels=40, occlusion_ratio=0.0)

    def change_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid() and self.actor:
            r, g, b, _ = color.getRgb()
            self.actor.GetProperty().SetColor(r / 255.0, g / 255.0, b / 255.0)

    def update_appearance(self, value):
        self.thick_input.setText(str(value))
        if self.actor and self.tube_filter:
            self.tube_filter.SetRadius(value / 20)
            self.tube_filter.Update()
            self.actor.GetMapper().SetInputData(self.tube_filter.GetOutput())
            # Update original mesh reference
            self.original_mesh = pv.wrap(self.tube_filter.GetOutput())
            self.plotter.render()

    def update_slider_from_input(self):
        try:
            value = int(self.thick_input.text())
            if 1 <= value <= 100:
                self.thick_slider.setValue(value)
            else:
                self.thick_input.setText(str(self.thick_slider.value()))
        except ValueError:
            self.thick_input.setText(str(self.thick_slider.value()))


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, False)
    app = QApplication(sys.argv)
    window = GCodeApp()
    window.show()
    sys.exit(app.exec())
