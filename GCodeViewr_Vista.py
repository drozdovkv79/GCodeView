import sys
from datetime import datetime, time

import numpy as np
import pyvista as pv
import vtk
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextLine
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
)
from pyvistaqt import BackgroundPlotter
from qtpy.QtWidgets import QLineEdit, QTextEdit


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
        # Словарь для хранения акторов (объектов на сцене)
        self.actors = {}
        self.counter = 0

        self.parser = UltraFastParser()
        self.plotter = BackgroundPlotter(show=False)
        self.plotter.enable_anti_aliasing()
        self.plotter.enable_terrain_style(mouse_wheel_zooms=0.95)
        self.plotter.camera_position = "xy"
        # self.plotter.disable_camera_reset()
        self.plotter.show_grid(
            color=(80, 80, 90), grid="back", location="outer", ticks="both"
        )

        # Включаем оптимизацию для macOS
        self.plotter.render_window.SetMultiSamples(0)  # Отключаем MSAA для скорости

        # Настройка UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self.layout = QtWidgets.QHBoxLayout(central)

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

        # --- Секция добавления объектов ---
        panel.addWidget(QLabel("<b>Добавить объект:</b>"))
        btn_layout = QHBoxLayout()

        btn_cube = QPushButton("Куб")
        btn_cube.clicked.connect(lambda: self.add_shape("cube"))

        btn_sphere = QPushButton("Сфера")
        btn_sphere.clicked.connect(lambda: self.add_shape("sphere"))

        btn_layout.addWidget(btn_cube)
        btn_layout.addWidget(btn_sphere)
        panel.addLayout(btn_layout)

        panel.addWidget(QFrame(frameShape=QFrame.HLine))

        # --- Секция выбора активного объекта ---
        panel.addWidget(QLabel("<b>Выберите объект для перемещения:</b>"))
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.sync_sliders_with_actor)
        panel.addWidget(self.selector)

        # --- Секция ползунков (X, Y, Z) ---
        self.sliders = {}
        self.xyz = {}
        for axis in ["X", "Y", "Z"]:
            panel.addWidget(QLabel(f"Смещение по {axis}:"))
            edit_xyz = QLineEdit("0.0")
            panel.addWidget(edit_xyz)
            self.xyz[axis] = edit_xyz
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(-3000)
            slider.setMaximum(3000)
            slider.setValue(0)
            slider.valueChanged.connect(self.update_position)
            panel.addWidget(slider)
            self.sliders[axis] = slider

        btn_scr = QPushButton("Применить")
        btn_scr.clicked.connect(self.xyz_apply)
        panel.addWidget(btn_scr)

        btn_scr = QPushButton("ScreenShot")
        btn_scr.clicked.connect(
            lambda: self.get_screenshot("/Users/drozdovkv/screen1.png")
        )
        panel.addWidget(btn_scr)

        panel.addStretch()
        self.layout.addLayout(panel, 1)
        self.layout.addWidget(self.plotter.interactor, 4)

        # -- закончили создавать интерфейс
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

    def get_screenshot(self, fname):
        self.plotter.screenshot(fname)

    def add_shape(self, shape_type):
        """Добавляет куб или сферу"""
        self.counter += 1
        name = f"{shape_type.capitalize()}_{self.counter}"

        if shape_type == "cube":
            mesh = pv.Cube(x_length=50, y_length=50, z_length=10)
            color = "orange"
        else:
            mesh = pv.Sphere(radius=10)
            color = "magenta"

        actor = self.plotter.add_mesh(mesh, color=color, show_edges=True)
        self.actors[name] = actor
        self.selector.addItem(name)
        # Автоматически выбираем новый объект
        self.selector.setCurrentText(name)

    def update_position(self):
        """Обновляет позицию выбранного объекта на основе ползунков"""
        active_name = self.selector.currentText()
        if active_name in self.actors:
            # Получаем значения ползунков (делим на 10 для плавности)
            x = self.sliders["X"].value()
            y = self.sliders["Y"].value()
            z = self.sliders["Z"].value()
            # Устанавливаем позицию актора
            self.actors[active_name].position = (x, y, z)
            self.xyz["X"].setText(f"{x}")
            self.xyz["Y"].setText(f"{y}")
            self.xyz["Z"].setText(f"{z}")

    def xyz_apply(self):
        self.sliders["X"].setValue(int(self.xyz["X"].text().split(".")[0]))
        self.sliders["Y"].setValue(int(self.xyz["Y"].text().split(".")[0]))
        self.sliders["Z"].setValue(int(self.xyz["Z"].text().split(".")[0]))
        self.update_position()

    def sync_sliders_with_actor(self):
        """Синхронизирует положение ползунков при смене объекта в списке"""
        active_name = self.selector.currentText()
        if active_name in self.actors:
            pos = self.actors[active_name].position

            # Блокируем сигналы, чтобы перемещение ползунка не вызывало update_position
            for i, axis in enumerate(["X", "Y", "Z"]):
                self.sliders[axis].blockSignals(True)
                self.sliders[axis].setValue(int(pos[i] * 10))
                self.sliders[axis].blockSignals(False)

    def render_model(self):
        if self.actor:
            self.plotter.remove_actor(self.actor)

        line = pv.lines_from_points(self.parser.all_points)
        # 2. Настраиваем VTK-фильтр
        self.tube_filter = vtk.vtkTubeFilter()
        self.tube_filter.SetInputData(line)
        self.tube_filter.SetRadius(1.5)
        self.tube_filter.SetNumberOfSides(8)
        self.tube_filter.SetCapping(True)
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
