import sys
import time
import numpy as np
from PyQt6 import QtWidgets, QtCore
import pyvista as pv
from pyvistaqt import QtInteractor

class MultiMeshApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyVista: Spheres, Cubes & Cones (10mm)")
        self.resize(1200, 850)

        # UI Layout
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QtWidgets.QHBoxLayout(self.central_widget)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setFixedWidth(260)
        self.list_widget.currentRowChanged.connect(self.on_selection_changed)
        
        self.plotter = QtInteractor(self)
        
        self.layout.addWidget(self.list_widget)
        self.layout.addWidget(self.plotter)

        self.centers = None
        self.create_scene()

    def create_scene(self):
        n_total = 500_000
        field_radius = 3000
        size = 10 # Диаметр/размер фигуры

        start_time = time.time()
        # 1. Генерация всех позиций
        self.centers = np.random.uniform(-field_radius, field_radius, (n_total, 3))
        
        # 2. Определяем геометрии (3 вида)
        geometries = [
            pv.Sphere(radius=size/2, theta_resolution=5, phi_resolution=5), # Сфера
            pv.Cube(x_length=size, y_length=size, z_length=size),          # Куб
            pv.Cone(radius=size/2, height=size, resolution=8)             # Конус
        ]
        geom_names = ["Sphere", "Cube", "Cone"]

        # Разбиваем 5000 индексов на 3 группы
        indices = np.arange(n_total)
        np.random.shuffle(indices)
        groups = np.array_split(indices, 3)

        print("Генерация объектов...")

        for i, group_indices in enumerate(groups):
            group_centers = self.centers[group_indices]
            n_group = len(group_indices)
            
            # Создаем облако точек для группы
            cloud = pv.PolyData(group_centers)
            
            # Цвета для группы
            colors = np.random.randint(0, 255, (n_group, 3), dtype=np.uint8)
            cloud.point_data["colors"] = colors
            
            # Глифинг конкретной фигурой
            # scale=False предотвращает раздувание фигур от данных цвета
            glyph_mesh = cloud.glyph(geom=geometries[i], scale=False, factor=1.0)
            
            # Ручной проброс цветов для стабильности на macOS/Python 3.14
            if "colors" not in glyph_mesh.point_data:
                n_v = geometries[i].n_points
                glyph_mesh.point_data["colors"] = np.repeat(colors, n_v, axis=0)

            # Добавляем группу на сцену
            self.plotter.add_mesh(
                glyph_mesh, 
                scalars="colors", 
                rgb=True, 
                preference="point",
                smooth_shading=True,
                name=f"group_{i}"
            )

        # Заполняем список с указанием типа фигуры
        """list_items = ["" for _ in range(n_total)]
        for i, group_indices in enumerate(groups):
            for idx in group_indices:
                list_items[idx] = f"{geom_names[i]} #{idx}"
        
        self.list_widget.addItems(list_items)"""
        
        total_time = time.time() - start_time
        print(f"✅ Готово за {total_time:.2f} сек.")
        self.plotter.reset_camera()
        self.plotter.render()

    def on_selection_changed(self, index):
        if index < 0 or self.centers is None: return
        
        target = self.centers[index]
        
        
        # Подсветка рамкой
        self.plotter.remove_actor("highlight")
        box = pv.Box(bounds=(target[0]-8, target[0]+8, 
                             target[1]-8, target[1]+8, 
                             target[2]-8, target[2]+8))
        self.plotter.add_mesh(box, color="white", style="wireframe", line_width=2, name="highlight")
        # Летим к объекту (fly_to учитывает малый размер 10мм)
        self.plotter.fly_to(target)
        self.plotter.render()

    def closeEvent(self, event):
        self.plotter.close()
        event.accept()

if __name__ == "__main__":
    if sys.platform == 'darwin':
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    
    app = QtWidgets.QApplication(sys.argv)
    window = MultiMeshApp()
    window.show()
    sys.exit(app.exec())
