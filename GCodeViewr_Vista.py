import sys

import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv
import vtk
from PIL import Image
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
)
from pyvistaqt import BackgroundPlotter
from scipy.interpolate import splev, splprep


def generate_realistic_sand_texture(size=(1024, 1024)):
    from noise import pnoise2

    # Несколько слоёв шума разного масштаба
    layers = []
    scales = [50, 100, 200]
    weights = [0.5, 0.3, 0.2]

    for scale, weight in zip(scales, weights):
        layer = np.zeros(size)
        for i in range(size[0]):
            for j in range(size[1]):
                layer[i][j] = pnoise2(i / scale, j / scale, octaves=6, persistence=0.5)
        layers.append(layer * weight)

    combined = np.sum(layers, axis=0)
    combined = (combined - combined.min()) / (combined.max() - combined.min())

    # Цветовая карта песка
    sand_colors = np.stack(
        [
            combined * 0.9 + 0.1,  # R: тёплый бежевый
            combined * 0.8 + 0.15,  # G: чуть зеленее
            combined * 0.6 + 0.2,  # B: немного синего для реализма
        ],
        axis=-1,
    )

    # Добавляем вкрапления
    dark_mask = combined < 0.2
    light_mask = combined > 0.8

    sand_colors[dark_mask] *= [0.7, 0.6, 0.5]  # Тёмные вкрапления (тёмно-коричневый)
    sand_colors[light_mask] *= [1.3, 1.2, 1.1]  # Светлые вкрапления (почти белый)

    return (np.clip(sand_colors, 0, 1) * 255).astype(np.uint8)


def generate_sand_with_pebbles_texture(size=(1024, 1024), pebble_density=0.02):
    np.random.seed(42)  # Для воспроизводимости

    # Основной песок — гладкий шум
    from scipy.ndimage import gaussian_filter

    base = np.random.rand(size[0], size[1])
    sand_base = gaussian_filter(base, sigma=2)

    sand_base = (sand_base - sand_base.min()) / (sand_base.max() - sand_base.min())

    # Создаём карту гальки
    pebbles = np.random.rand(size[0], size[1]) < pebble_density
    pebble_centers = np.where(pebbles)

    # Размываем гальку для реалистичности
    pebble_map = np.zeros_like(sand_base)
    for i, j in zip(pebble_centers[0], pebble_centers[1]):
        # Случайный размер гальки
        radius = np.random.randint(3, 8)
        y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
        mask = x**2 + y**2 <= radius**2
        if (
            0 <= i - radius
            and i + radius + 1 < size[0]
            and 0 <= j - radius
            and j + radius + 1 < size[1]
        ):
            pebble_map[i - radius : i + radius + 1, j - radius : j + radius + 1][
                mask
            ] = 1

    # Применяем гальку с разной интенсивностью
    pebble_intensity = np.random.uniform(0.3, 0.8, pebble_map.shape)
    pebble_map *= pebble_intensity

    # Комбинируем
    final = sand_base + pebble_map * 0.3
    final = (final - final.min()) / (final.max() - final.min())

    # Цвета
    color_map = np.stack(
        [final * 0.9 + 0.05, final * 0.8 + 0.08, final * 0.6 + 0.1], axis=-1
    )

    return (color_map * 255).astype(np.uint8)


# Функция для создания синтетической текстуры песка
def create_synthetic_sand_texture(size=(256, 256)):
    height, width = size
    # Создаём базовый шум
    noise = np.random.rand(height, width, 3) * 0.1
    # Базовый цвет песка (бежевый)
    base_color = np.array([0.9, 0.8, 0.6])
    texture = base_color + noise
    # Нормализуем значения в диапазон [0, 1]
    texture = np.clip(texture, 0, 1)
    return (texture * 255).astype(np.uint8)


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
        self.actors = {}
        self.counter = 0
        self.sliders = {}
        self.xyz = {}

        self.parser = UltraFastParser()
        self.plotter = BackgroundPlotter(show=False)
        self.plotter.background_color = "silver"
        self.plotter.enable_anti_aliasing()
        self.plotter.render_window.SetMultiSamples(2)
        """Render time for False : 37.045 ms
        2 Render time for fxaa  : 40.458 ms
        4 Render time for msaa  : 42.566 ms
        8-32 Render time for ssaa  : 51.450 ms"""
        # self.plotter.render_window.LineSmoothingOn()  # включить сглаживание линий.
        # self.plotter.render_window.PointSmoothingOn()  # включить сглаживание точек.
        self.plotter.enable_terrain_style(mouse_wheel_zooms=1.035)
        self.plotter.camera_position = "iso"  # xy, xz, yz, yx, zx, zy, iso
        self.plotter.show_grid(
            color=(80, 80, 90),
            grid="back",
            show_yaxis=False,
            location="outer",
            ticks="both",
        )
        self.plotter.show()

        # Настройка UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self.layout = QtWidgets.QHBoxLayout(central)

        panel = QtWidgets.QVBoxLayout()
        btn_load = QtWidgets.QPushButton("Загрузить файл")
        btn_load.clicked.connect(self.load_file)
        panel.addWidget(btn_load)

        panel1 = QHBoxLayout()
        # Метка для толщины линии
        self.thick_label = QtWidgets.QLabel("Толщина линии: ")
        panel1.addWidget(self.thick_label)

        # Текстовое поле для ввода значения толщины линии
        self.thick_input = QtWidgets.QLineEdit()
        self.thick_input.setFixedWidth(30)
        self.thick_input.setText("50")
        self.thick_input.editingFinished.connect(self.update_slider_from_input)
        panel1.addWidget(self.thick_input)

        # Слайдер для изменения толщины линии
        self.thick_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.thick_slider.setRange(1, 100)
        self.thick_slider.setValue(50)
        self.thick_slider.valueChanged.connect(self.update_appearance)
        panel1.addWidget(self.thick_slider)
        panel.addLayout(panel1)

        self.btn_color = QtWidgets.QPushButton("Цвет модели")
        self.btn_color.clicked.connect(self.change_color)
        panel.addWidget(self.btn_color)

        # zoom
        zoom_layout = QGridLayout()
        self.xyz["zoom"] = QLabel(f"zoom [1]:")
        zoom_layout.addWidget(self.xyz["zoom"], 0, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(1)
        slider.setMaximum(60)
        slider.setValue(30)
        slider.valueChanged.connect(self.update_zoom)
        zoom_layout.addWidget(slider, 0, 1)
        # Добавляем макеты в основной макет
        panel.addLayout(zoom_layout)

        # Создаем кнопки
        buttons = ["zy", "xy", "yz", "yx", "xz", "zx", "iso"]
        button_layout = QHBoxLayout()
        for button_name in buttons:
            button = QPushButton(button_name)
            button.clicked.connect(
                lambda _, name=button_name: self.set_camera_position(name)
            )
            button_layout.addWidget(button)
        panel.addLayout(button_layout)

        # Сохранение экрана в файл
        btn_scr = QPushButton("ScreenShot")
        btn_scr.clicked.connect(
            lambda: self.get_screenshot("/Users/drozdovkv/screen1.png")
        )
        panel.addWidget(btn_scr)
        panel.addWidget(QFrame(frameShape=QFrame.HLine))

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

        # --- Секция выбора активного объекта ---
        panel.addWidget(QLabel("<b>Выберите объект для перемещения:</b>"))
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.sync_sliders_with_actor)
        panel.addWidget(self.selector)

        # --- Секция ползунков (X, Y, Z) ---
        # Создаем макет для полей ввода
        input_layout = QGridLayout()
        # --- Секция ползунков (X, Y, Z) ---
        for i, axis in enumerate(["X", "Y", "Z"]):
            # Добавляем метку
            input_layout.addWidget(QLabel(f"{axis}:"), i, 0)
            # Добавляем поле ввода
            edit_xyz = QLineEdit("0.0")
            edit_xyz.setFixedWidth(50)
            input_layout.addWidget(edit_xyz, i, 1)
            self.xyz[axis] = edit_xyz
            # Добавляем ползунок
            slider = QSlider(Qt.Horizontal)
            len = 3000
            if axis == "X":
                len = 1000
            elif axis == "Y":
                len = 500
            slider.setMinimum(len * -1)
            slider.setMaximum(len)
            slider.setValue(0)
            slider.valueChanged.connect(self.update_position)
            input_layout.addWidget(slider, i, 2)
            self.sliders[axis] = slider
            # размеры
            edit_xyz = QLineEdit("0.0")
            edit_xyz.setFixedWidth(50)
            input_layout.addWidget(edit_xyz, i, 3)
            self.xyz["h" + axis] = edit_xyz
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(1)
            slider.setMaximum(3000)
            slider.setValue(100)
            slider.valueChanged.connect(self.update_size)
            input_layout.addWidget(slider, i, 4)
            self.sliders["h" + axis] = slider

        # Добавляем макеты в основной макет
        panel.addLayout(input_layout)

        # Кнопка применения
        btn_scr = QPushButton("Применить")
        btn_scr.clicked.connect(self.xyz_apply)
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
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Save File", "", "All Files (*);;PNG Files (*.png)", options=options
        )
        if fileName:
            self.plotter.screenshot(fileName)

    def add_shape(self, shape_type):
        """Добавляет куб или сферу"""
        self.counter += 1
        name = f"{shape_type.capitalize()}_{self.counter}"

        if shape_type == "cube":
            mesh = pv.Cube(x_length=50, y_length=50, z_length=50)
            color = "orange"
        else:
            mesh = pv.Sphere(radius=50)
            color = "magenta"

        actor = self.plotter.add_mesh(mesh, color=color, show_edges=True)
        self.actors[name] = actor
        self.selector.addItem(name)
        # Автоматически выбираем новый объект
        self.selector.setCurrentText(name)
        self.plotter.reset_camera()

    def set_camera_position(self, position_name):
        camera_positions = {
            "xy": [0, 1, 0],
            "xz": [0, 0, 1],
            "yz": [1, 0, 0],
            "yx": [-1, 0, 0],
            "zx": [0, 0, -1],
            "zy": [0, -1, 0],
            "iso": [1, 1, 1],
        }

        if position_name in camera_positions:
            self.plotter.camera_position = camera_positions[position_name]
            self.plotter.render()

    def update_zoom(self, value):
        scale_factor = value
        self.xyz["zoom"].setText(f"zoom: [{scale_factor}]")
        self.plotter.camera.view_angle = scale_factor
        self.plotter.render()

    def update_position(self):
        active_name = self.selector.currentText()
        if active_name in self.actors:
            x = self.sliders["X"].value()
            y = self.sliders["Y"].value()
            z = self.sliders["Z"].value()
            self.actors[active_name].position = (x, y, z)
            self.xyz["X"].setText(f"{x}")
            self.xyz["Y"].setText(f"{y}")
            self.xyz["Z"].setText(f"{z}")

    def resize_cube(self, mesh, x_len, y_len, z_len):
        b = mesh.bounds
        curr_x = b[1] - b[0]
        curr_y = b[3] - b[2]
        curr_z = b[5] - b[4]
        factors = [
            x_len / curr_x if curr_x != 0 else 1,
            y_len / curr_y if curr_y != 0 else 1,
            z_len / curr_z if curr_z != 0 else 1,
        ]
        mesh.points[:, 0] *= factors[0]  # X
        mesh.points[:, 1] *= factors[1]  # Y
        mesh.points[:, 2] *= factors[2]  # Z
        return mesh

    def update_size(self):
        active_name = self.selector.currentText()
        if active_name in self.actors:
            x = self.sliders["hX"].value()
            y = self.sliders["hY"].value()
            z = self.sliders["hZ"].value()
            self.resize_cube(self.actors[active_name].mapper.dataset, x, y, z)
            self.xyz["hX"].setText(f"{x}")
            self.xyz["hY"].setText(f"{y}")
            self.xyz["hZ"].setText(f"{z}")

    def xyz_apply(self):
        for i, axis in enumerate(["hX", "hY", "hZ", "X", "Y", "Z"]):
            self.sliders[axis].blockSignals(True)
            self.sliders[axis].setValue(int(self.xyz[axis].text().split(".")[0]))
            self.sliders[axis].blockSignals(False)
        self.update_position()
        self.update_size()

    def sync_sliders_with_actor(self):
        active_name = self.selector.currentText()
        if active_name in self.actors:
            pos = self.actors[active_name].position
            b = self.actors[active_name].mapper.dataset.bounds
            size = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
            for i, axis in enumerate(["X", "Y", "Z"]):
                self.sliders[axis].blockSignals(True)
                self.sliders[axis].setValue(int(pos[i] * 10))
                self.xyz[axis].setText(f"{pos[i]}")
                self.sliders[axis].blockSignals(False)

            for i, axis in enumerate(["hX", "hY", "hZ"]):
                self.sliders[axis].blockSignals(True)
                self.sliders[axis].setValue(int(size[i]))
                self.xyz[axis].setText(f"{size[i]}")
                self.sliders[axis].blockSignals(False)

    def interpolate_spline(self, polydata, num_points=1000):
        points = polydata.points.copy()
        tck, u = splprep(points.T, s=0, k=3)  # Сплайн 3-й степени
        u_fine = np.linspace(u.min(), u.max(), num_points)
        xnew, ynew, znew = splev(u_fine, tck)
        interpolated_points = np.column_stack((xnew, ynew, znew))
        return pv.PolyData(interpolated_points)

    def render_model(self):
        if self.actor:
            self.plotter.remove_actor(self.actor)
        # line = pv.lines_from_points(self.parser.all_points)
        spl = pv.PolyData(self.parser.all_points)
        spl.lines = np.hstack(
            [[len(self.parser.all_points)], np.arange(len(self.parser.all_points))]
        )
        # 2. Настраиваем VTK-фильтр
        self.tube_filter = vtk.vtkTubeFilter()
        self.tube_filter.SetInputData(spl)
        self.tube_filter.SetRadius(2.5)
        self.tube_filter.SetNumberOfSides(8)
        # self.tube_filter.SetCapping(True)
        self.tube_filter.Update()
        # 3. Оборачиваем результат в PyVista
        tube = pv.wrap(self.tube_filter.GetOutput())

        # Текстурирование
        """tube.texture_map_to_plane(inplace=True, use_bounds=False)
        texture_array = generate_realistic_sand_texture()
        texture = pv.Texture(texture_array)"""

        # 4. Добавляем в плоттер
        self.actor = self.plotter.add_mesh(
            tube,
            # texture=texture,
            name="3d_panel",
            color="beige",
            smooth_shading=True,  # Включает интерполяцию цветов между вершинами
            # split_sharp_edges=True,  # Помогает сглаживанию на резких изгибах
            show_edges=False,
            specular=0.1,  # Почти убираем зеркальные блики
            specular_power=1,  # Делаем остаточный блик очень рассеянным
            diffuse=0.8,  # Основной цвет поверхности (матовый слой)
            ambient=0.3,  # Общая освещенность в тенях (чтобы не было черных пятен)
            pickable=False,
        )
        self.plotter.enable_depth_peeling(number_of_peels=40, occlusion_ratio=0.0)

    def change_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.model_color = color.name()
            self.btn_color.setText("Цвет: " + color.name())
            if self.actor:
                r, g, b, _ = color.getRgb()
                self.actor.GetProperty().SetColor(r / 255.0, g / 255.0, b / 255.0)

    def update_appearance(self, value):
        self.thick_input.setText(str(value))
        if self.actor:
            self.tube_filter.SetRadius(value / 20)
            self.tube_filter.Update()
            self.actor.GetMapper().SetInputData(self.tube_filter.GetOutput())
            self.plotter.render()  # Рендерим только при изменении параметра

    def update_slider_from_input(self):
        # Обновляем значение слайдера при изменении текстового поля
        try:
            value = int(self.thick_input.text())
            if 1 <= value <= 50:
                self.thick_slider.setValue(value)
            else:
                self.thick_input.setText(str(self.thick_slider.value()))
        except ValueError:
            self.thick_input.setText(str(self.thick_slider.value()))


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, False)
    app = QtWidgets.QApplication(sys.argv)
    # Отключаем vsync если нужен максимальный FPS при интерактиве
    # app.setAttribute(Qt.AA_ShareOpenGLContexts)
    window = GCodeApp()
    window.show()
    sys.exit(app.exec_())
