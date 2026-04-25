import pyvista as pv
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import BackgroundPlotter


class ShapeManagerApp:
    def __init__(self):
        # Инициализация плоттера
        self.plotter = BackgroundPlotter()
        self.plotter.add_axes()
        self.plotter.camera_position = "xy"
        # Словарь для хранения акторов (объектов на сцене)
        self.actors = {}
        self.counter = 0

        # Создание основного окна управления (UI)
        self.gui = QWidget()
        self.gui.setWindowTitle("Управление 3D объектами")
        self.layout = QVBoxLayout(self.gui)

        # --- Секция добавления объектов ---
        self.layout.addWidget(QLabel("<b>Добавить объект:</b>"))
        btn_layout = QHBoxLayout()

        btn_cube = QPushButton("Куб")
        btn_cube.clicked.connect(lambda: self.add_shape("cube"))

        btn_sphere = QPushButton("Сфера")
        btn_sphere.clicked.connect(lambda: self.add_shape("sphere"))

        btn_layout.addWidget(btn_cube)
        btn_layout.addWidget(btn_sphere)
        self.layout.addLayout(btn_layout)

        self.layout.addWidget(QFrame(frameShape=QFrame.HLine))

        # --- Секция выбора активного объекта ---
        self.layout.addWidget(QLabel("<b>Выберите объект для перемещения:</b>"))
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.sync_sliders_with_actor)
        self.layout.addWidget(self.selector)

        # --- Секция ползунков (X, Y, Z) ---
        self.sliders = {}
        for axis in ["X", "Y", "Z"]:
            self.layout.addWidget(QLabel(f"Смещение по {axis}:"))
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(-100)
            slider.setMaximum(100)
            slider.setValue(0)
            slider.valueChanged.connect(self.update_position)
            self.layout.addWidget(slider)
            self.sliders[axis] = slider

        btn_scr = QPushButton("ScreenShot")
        btn_scr.clicked.connect(
            lambda: self.get_screenshot("/Users/drozdovkv/screen1.png")
        )
        self.layout.addWidget(btn_scr)

        # Добавляем начальную спираль
        self.add_spiral()

        # Показываем интерфейс
        self.gui.resize(300, 400)
        self.gui.show()

    def add_spiral(self):
        """Создает 3D спираль (Helix)"""
        # Параметрическая спираль
        helix = pv.Sphere(radius=3)
        name = "Сфера_1"
        # Добавляем на сцену
        actor = self.plotter.add_mesh(helix, color="cyan", line_width=3, label=name)
        self.actors[name] = actor
        self.selector.addItem(name)

    def get_screenshot(self, fname):
        self.plotter.screenshot(fname)

    def add_shape(self, shape_type):
        """Добавляет куб или сферу"""
        self.counter += 1
        name = f"{shape_type.capitalize()}_{self.counter}"

        if shape_type == "cube":
            mesh = pv.Cube()
            color = "orange"
        else:
            mesh = pv.Sphere(radius=0.5)
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
            x = self.sliders["X"].value() / 10.0
            y = self.sliders["Y"].value() / 10.0
            z = self.sliders["Z"].value() / 10.0

            # Устанавливаем позицию актора
            self.actors[active_name].position = (x, y, z)
            # Принудительная перерисовка не требуется для BackgroundPlotter,
            # но можно вызвать если заметны задержки: self.plotter.render()

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


if __name__ == "__main__":
    # Для запуска в некоторых IDE может потребоваться создание QApplication
    import sys

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = ShapeManagerApp()
    sys.exit(app.exec_())
