import sys
from datetime import datetime, time

import numpy as np
import pyvista as pv
import vtk
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
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
                current_path = []  # Накапливаем непрерывную линию
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
                        # Если G0 или разрыв — сохраняем накопленный путь
                        if len(current_path) > 1:
                            self._add_polyline(current_path)
                        current_path = []
                        curr = new_pos

                # Сохраняем последний путь
                if len(current_path) > 1:
                    self._add_polyline(current_path)

            self.all_points = np.vstack(self.points).astype(np.float32)
            self.all_lines = np.concatenate(self.lines).astype(np.int32)

            return True
        except Exception as e:
            print(f"Error: {e}")
            return False

    def _add_polyline(self, path_points):
        """Создает структуру PolyLine для VTK: [N, id0, id1, ..., idN-1]"""
        start_idx = sum(len(p) for p in self.points)
        pts = np.array(path_points, dtype=np.float32)
        self.points.append(pts)
        n_pts = len(pts)
        indices = np.arange(start_idx, start_idx + n_pts)
        self.lines.append(np.hstack([[n_pts], indices]))


class GCodeApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("G-Code Viewer")
        self.resize(1280, 720)

        self.parser = UltraFastParser()
        self.plotter = BackgroundPlotter(show=False)
        self.plotter.enable_anti_aliasing()
        self.plotter.enable_terrain_style(mouse_wheel_zooms=0.95)
        # self.plotter.disable_camera_reset()
        self.plotter.show_grid(
            color=(80, 80, 90), grid="back", location="outer", ticks="both"
        )

        # Включаем оптимизацию для macOS
        self.plotter.render_window.SetMultiSamples(0)  # Отключаем MSAA для скорости

        # Настройка UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)

        panel = QtWidgets.QVBoxLayout()
        btn_load = QtWidgets.QPushButton("Загрузить файл")
        btn_load.clicked.connect(self.load_file)
        panel.addWidget(btn_load)

        self.thick_label = QtWidgets.QLabel("Толщина линии: ")
        panel.addWidget(self.thick_label)
        self.thick_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.thick_slider.setRange(1, 50)
        self.thick_slider.setValue(30)
        self.thick_slider.valueChanged.connect(self.update_appearance)
        panel.addWidget(self.thick_slider)

        self.btn_color = QtWidgets.QPushButton("Цвет модели")
        self.btn_color.clicked.connect(self.change_color)
        panel.addWidget(self.btn_color)

        panel.addStretch()
        layout.addLayout(panel, 1)
        layout.addWidget(self.plotter.interactor, 4)

        self.mesh = None
        self.actor = None

    def load_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open G-code")
        if path:
            if self.parser.parse(path):
                self.render_model()
                n = len(self.parser.all_points)
                self.setWindowTitle(f"G-Code Viewer: [{n}] {path}")
                self.plotter.reset_camera()

    def render_model(self):
        if self.actor:
            self.plotter.remove_actor(self.actor)

        line = pv.lines_from_points(self.parser.all_points)
        # 2. Настраиваем VTK-фильтр
        self.tube_filter = vtk.vtkTubeFilter()
        self.tube_filter.SetInputData(line)
        self.tube_filter.SetRadius(1.5)
        self.tube_filter.SetNumberOfSides(16)
        self.tube_filter.SetCapping(False)
        self.tube_filter.Update()
        # 3. Оборачиваем результат в PyVista
        tube = pv.wrap(self.tube_filter.GetOutput())
        # 4. Добавляем в плоттер
        self.actor = self.plotter.add_mesh(
            tube,
            name="3d_panel",
            color="beige",
            smooth_shading=True,
            specular=0.5,
            diffuse=0.8,
            ambient=0.2,
            pickable=False,
        )

    def change_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.model_color = color.name()
            self.btn_color.setText("Цвет: " + color.name())
            if self.actor:
                r, g, b, _ = color.getRgb()
                self.actor.GetProperty().SetColor(r / 255.0, g / 255.0, b / 255.0)

    def update_appearance(self):
        self.thick_label.setText(f"Толщина линии: {self.thick_slider.value()}")
        if self.actor:
            self.tube_filter.SetRadius(self.thick_slider.value() / 20)
            self.tube_filter.Update()
            # Обновляем только данные в уже добавленном меше (быстрее чем add_mesh)
            self.actor.GetMapper().SetInputData(self.tube_filter.GetOutput())
            self.plotter.render()  # Рендерим только при изменении параметра


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, False)
    app = QtWidgets.QApplication(sys.argv)
    # Отключаем vsync если нужен максимальный FPS при интерактиве
    # app.setAttribute(Qt.AA_ShareOpenGLContexts)
    window = GCodeApp()
    window.show()
    sys.exit(app.exec_())
