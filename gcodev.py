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
        self.plotter.show_grid(
            color=(80, 80, 90),
            grid="back",
            show_yaxis=False,
            location="outer",
            ticks="both",
        )
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

        # Section tools group
        section_group = QGroupBox("Сечение модели")
        section_layout = QVBoxLayout()

        # Enable/disable section box widget
        self.section_enabled = False
        self.btn_section = QPushButton("Включить сечение")
        self.btn_section.setCheckable(True)
        self.btn_section.clicked.connect(self.toggle_section_widget)
        section_layout.addWidget(self.btn_section)

        # Reset section button
        btn_reset_section = QPushButton("Сбросить сечение")
        btn_reset_section.clicked.connect(self.reset_section_widget)
        section_layout.addWidget(btn_reset_section)

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
        self.clip_box_widget = None
        self.original_bounds = None

    # ========== Section Widget ==========
    def toggle_section_widget(self, checked):
        if checked:
            self.enable_section_widget()
            self.btn_section.setText("Выключить сечение")
        else:
            self.disable_section_widget()
            self.btn_section.setText("Включить сечение")

    def enable_section_widget(self):
        if not self.actor:
            print("Сначала загрузите модель")
            self.btn_section.setChecked(False)
            return

        # Store original bounds if not already stored
        if self.original_bounds is None:
            self.original_bounds = self.actor.bounds

        # Store original mapper
        if not hasattr(self, "original_mapper"):
            self.original_mapper = self.actor.GetMapper()

        # Create box widget for clipping
        self.clip_box_widget = self.plotter.add_box_widget(
            callback=self.update_clip,
            bounds=self.original_bounds,
            color="red",
            rotation_enabled=False,
        )
        self.section_enabled = True

    def disable_section_widget(self):
        if self.clip_box_widget:
            try:
                self.plotter.remove_actor(self.clip_box_widget)
            except:
                # If remove_actor fails, try alternative method
                pass
            self.clip_box_widget = None

        # Remove clip filter if exists
        if hasattr(self, "clip_filter") and self.clip_filter:
            if self.actor and hasattr(self, "original_mapper") and self.original_mapper:
                self.actor.SetMapper(self.original_mapper)

        self.section_enabled = False
        self.plotter.render()

    def update_clip(self, box_widget):
        """Callback function for box widget - clips the model"""
        if not self.actor or not box_widget:
            return

        # Get box bounds - box_widget is a vtkBoxWidget, not vtkPlanes
        try:
            # Get bounds from the widget
            bounds = [0, 0, 0, 0, 0, 0]
            box_widget.GetBounds(bounds)
        except:
            # Fallback: use original bounds
            bounds = self.original_bounds

        # Apply clipping using vtkClipPolyData
        if not hasattr(self, "clip_filter"):
            self.clip_filter = vtk.vtkClipPolyData()

        # Create implicit function for box clipping
        box = vtk.vtkBox()
        box.SetBounds(bounds)

        # Configure clip filter
        self.clip_filter.SetInputData(self.original_mesh)
        self.clip_filter.SetClipFunction(box)
        self.clip_filter.SetInsideOut(True)  # Keep inside of box
        self.clip_filter.Update()

        # Create new mapper with clipped data
        clipped_mapper = vtk.vtkPolyDataMapper()
        clipped_mapper.SetInputConnection(self.clip_filter.GetOutputPort())

        # Apply to actor
        self.actor.SetMapper(clipped_mapper)
        self.plotter.render()

    def reset_section_widget(self):
        """Reset clipping to show full model"""
        if self.section_enabled and self.actor:
            # Restore original mapper
            if hasattr(self, "original_mapper") and self.original_mapper:
                self.actor.SetMapper(self.original_mapper)
                self.plotter.render()

    # ========== Measurement ==========
    def toggle_measurement(self, checked):
        if checked:
            # Disable any previous picking before enabling new one
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
        # visual feedback: mark point
        sphere = pv.Sphere(radius=2, center=point)
        actor = self.plotter.add_mesh(sphere, color="red", pickable=False)
        self.measure_actors.append(actor)

        if len(self.measure_points) == 2:
            p1, p2 = self.measure_points
            dist = np.linalg.norm(np.array(p1) - np.array(p2))
            self.measure_label.setText(f"Расстояние: {dist:.2f} мм")

            # draw line between points
            line = pv.Line(p1, p2)
            line_actor = self.plotter.add_mesh(
                line, color="cyan", line_width=4, pickable=False
            )
            self.measure_actors.append(line_actor)

            # add a label at midpoint
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
            # automatically exit measurement mode after two picks
            self.btn_measure.setChecked(False)
            self.toggle_measurement(False)

    def reset_measurement(self):
        # remove all measurement graphics
        for actor in self.measure_actors:
            self.plotter.remove_actor(actor)
        self.measure_actors.clear()
        self.measure_points.clear()
        self.measure_label.setText("Расстояние: —")
        self.btn_reset_measure.setEnabled(False)
        # if in measurement mode, turn it off
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
                # Disable section if active
                if self.section_enabled:
                    self.disable_section_widget()
                    self.btn_section.setChecked(False)

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
