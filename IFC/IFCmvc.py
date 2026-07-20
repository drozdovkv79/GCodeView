# pip install PyQt6 pyvista pyvistaqt ifcopenshell numpy trimesh
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import List

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor


@dataclass
class LoadStats:
    """Статистика загрузки IFC файла"""

    total_time: float = 0.0
    elements_time: float = 0.0
    elements_count: int = 0
    materials_time: float = 0.0
    materials_count: int = 0
    geometry_time: float = 0.0
    geometry_count: int = 0
    colors_time: float = 0.0
    colors_count: int = 0
    relationships_time: float = 0.0
    relationships_count: int = 0
    file_size_mb: float = 0.0


class LoadWorker(QThread):
    """Поток для загрузки IFC файла"""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object, object, LoadStats)
    error = pyqtSignal(str)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            stats = LoadStats()
            file_size = os.path.getsize(self.filepath)
            stats.file_size_mb = file_size / (1024 * 1024)

            self.progress.emit(
                10, f"Открытие файла {os.path.basename(self.filepath)}..."
            )

            start_time = time.time()

            ifc_file = ifcopenshell.open(self.filepath)
            self.progress.emit(20, f"Файл открыт (размер: {stats.file_size_mb:.1f} MB)")

            stats.total_time = time.time() - start_time

            # Загрузка элементов
            self.progress.emit(30, "Загрузка элементов...")
            start_elements = time.time()
            elements = list(ifc_file.by_type("IfcProduct"))
            stats.elements_count = len(elements)
            stats.elements_time = time.time() - start_elements

            # Загрузка материалов
            self.progress.emit(40, "Загрузка материалов...")
            start_materials = time.time()
            materials = list(ifc_file.by_type("IfcMaterial"))
            stats.materials_count = len(materials)
            stats.materials_time = time.time() - start_materials

            # Загрузка цветов и стилей
            self.progress.emit(50, "Загрузка цветов и стилей...")
            start_colors = time.time()
            colors = list(ifc_file.by_type("IfcColourRgb"))
            styles = list(ifc_file.by_type("IfcSurfaceStyle"))
            stats.colors_count = len(colors) + len(styles)
            stats.colors_time = time.time() - start_colors

            # Загрузка геометрии
            self.progress.emit(60, "Загрузка геометрии...")
            start_geometry = time.time()
            geometries = list(ifc_file.by_type("IfcGeometricRepresentationItem"))
            stats.geometry_count = len(geometries)
            stats.geometry_time = time.time() - start_geometry

            # Загрузка отношений
            self.progress.emit(70, "Загрузка отношений...")
            start_relationships = time.time()
            relationships = list(ifc_file.by_type("IfcRelAggregates")) + list(
                ifc_file.by_type("IfcRelContainedInSpatialStructure")
            )
            stats.relationships_count = len(relationships)
            stats.relationships_time = time.time() - start_relationships

            # Построение иерархии
            self.progress.emit(80, "Построение иерархии...")
            hierarchy = self.build_hierarchy(ifc_file, elements)

            self.progress.emit(100, "Загрузка завершена!")
            self.finished.emit(ifc_file, hierarchy, stats)

        except Exception as e:
            self.error.emit(str(e))

    def build_hierarchy(self, ifc_file, elements):
        """Построение дерева иерархии элементов"""
        hierarchy = {"name": "Model", "children": {}, "elements": []}

        for elem in elements:
            elem_type = elem.is_a()
            if elem_type not in hierarchy["children"]:
                hierarchy["children"][elem_type] = {
                    "name": elem_type,
                    "children": {},
                    "elements": [],
                }

            try:
                elem_info = {
                    "id": elem.id(),
                    "name": getattr(elem, "Name", f"Unnamed_{elem.id()}"),
                    "global_id": getattr(elem, "GlobalId", "N/A"),
                    "type": elem_type,
                }
                hierarchy["children"][elem_type]["elements"].append(elem_info)
            except:
                pass

        return hierarchy


class BatchConvertWorker(QThread):
    """Поток для пакетной конвертации нескольких IFC в один GLB"""

    progress = pyqtSignal(int, str)
    file_progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, filepaths, output_file):
        super().__init__()
        self.filepaths = filepaths
        self.output_file = output_file
        self.stats = {"total_elements": 0, "total_meshes": 0}

    def run(self):
        try:
            import trimesh

            all_meshes = []
            total_files = len(self.filepaths)

            self.progress.emit(5, f"Начинаем обработку {total_files} файлов...")

            for file_idx, filepath in enumerate(self.filepaths):
                self.file_progress.emit(filepath, file_idx + 1, total_files)

                progress_val = 10 + int((file_idx / total_files) * 80)
                self.progress.emit(
                    progress_val, f"Загрузка: {os.path.basename(filepath)}"
                )

                ifc_file = ifcopenshell.open(filepath)

                settings = ifcopenshell.geom.settings()
                settings.set(settings.USE_WORLD_COORDS, True)

                elements = ifc_file.by_type("IfcProduct")

                self.progress.emit(
                    progress_val, f"Обработка {len(elements)} элементов..."
                )

                file_meshes = []

                for elem_idx, element in enumerate(elements):
                    if elem_idx % 50 == 0:
                        self.progress.emit(
                            progress_val, f"Элемент {elem_idx}/{len(elements)}"
                        )

                    try:
                        shape = ifcopenshell.geom.create_shape(settings, element)

                        if shape and shape.geometry:
                            verts = np.array(shape.geometry.verts).reshape(-1, 3)
                            faces = shape.geometry.faces

                            if len(verts) > 0 and len(faces) > 0:
                                trimesh_faces = []
                                for j in range(0, len(faces), 3):
                                    trimesh_faces.append(
                                        [faces[j], faces[j + 1], faces[j + 2]]
                                    )

                                mesh = trimesh.Trimesh(
                                    vertices=verts,
                                    faces=trimesh_faces,
                                    process=False,
                                    validate=False,
                                )

                                mesh.metadata["name"] = getattr(
                                    element, "Name", f"Unnamed_{element.id()}"
                                )
                                mesh.metadata["type"] = element.is_a()
                                mesh.metadata["source"] = os.path.basename(filepath)

                                # Получаем цвет
                                r, g, b = 0.7, 0.7, 0.7
                                try:
                                    materials = shape.geometry.materials
                                    if materials and len(materials) > 0:
                                        diffuse = str(materials[0].diffuse)
                                        if diffuse and diffuse.startswith("colour"):
                                            parts = diffuse.split()
                                            if len(parts) >= 4:
                                                r, g, b = (
                                                    float(parts[1]),
                                                    float(parts[2]),
                                                    float(parts[3]),
                                                )
                                except:
                                    pass

                                mesh.visual.vertex_colors = [r, g, b, 1.0]
                                file_meshes.append(mesh)

                    except Exception as e:
                        continue

                if file_meshes:
                    all_meshes.extend(file_meshes)
                    self.progress.emit(
                        progress_val, f"Добавлено {len(file_meshes)} элементов"
                    )

            self.progress.emit(90, "Объединение всех мешей...")

            if all_meshes:
                combined = trimesh.util.concatenate(all_meshes)
                self.progress.emit(95, f"Сохранение GLB файла...")
                combined.export(self.output_file, file_type="glb")
                self.progress.emit(100, "Конвертация завершена!")
                self.finished.emit(self.output_file)
            else:
                self.error.emit("Нет геометрии для экспорта")

        except Exception as e:
            self.error.emit(str(e))


class IFCViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ifc_file = None
        self.plotter = None
        self.element_actors = {}
        self.highlighted_actor = None
        self.selected_files = []
        self.current_directory = ""
        self.cancel_visualization = False
        self.loaded_files = []
        self.geometry_types = [
            "IfcWall",
            "IfcWallStandardCase",
            "IfcSlab",
            "IfcBeam",
            "IfcColumn",
            "IfcDoor",
            "IfcWindow",
            "IfcRoof",
            "IfcStair",
            "IfcRamp",
            "IfcPlate",
            "IfcCovering",
            "IfcCurtainWall",
            "IfcBuildingElementProxy",
            "IfcMember",
            "IfcFooting",
            "IfcPile",
            "IfcRailing",
        ]
        self.init_ui()

    def init_ui(self):
        """Инициализация пользовательского интерфейса"""
        self.setWindowTitle("IFC Viewer - Анализ больших моделей зданий")
        self.setGeometry(100, 100, 1600, 900)
        font = QFont("Arial", 12)
        self.setFont(font)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Верхняя панель с кнопками
        button_layout = QHBoxLayout()

        self.select_dir_btn = QPushButton("Выбрать директорию")
        self.select_dir_btn.clicked.connect(self.select_directory)
        button_layout.addWidget(self.select_dir_btn)

        self.read_btn = QPushButton("Читать файл")
        self.read_btn.clicked.connect(self.read_ifc_file)
        self.read_btn.setEnabled(False)
        button_layout.addWidget(self.read_btn)

        self.convert_btn = QPushButton("Конвертировать в GLB")
        self.convert_btn.clicked.connect(self.convert_to_glb)
        button_layout.addWidget(self.convert_btn)

        self.batch_convert_btn = QPushButton("Пакетная конвертация")
        self.batch_convert_btn.clicked.connect(self.batch_convert_to_glb)
        self.batch_convert_btn.setEnabled(False)
        button_layout.addWidget(self.batch_convert_btn)

        self.clear_btn = QPushButton("Очистить модель")
        self.clear_btn.clicked.connect(self.clear_model)
        button_layout.addWidget(self.clear_btn)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        # Панель управления визуализацией
        controls_group = QGroupBox("Режимы визуализации")
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("Прозрачность:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(70)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        controls_layout.addWidget(self.opacity_slider)

        self.opacity_label = QLabel("70%")
        controls_layout.addWidget(self.opacity_label)

        self.style_btn = QPushButton("Стиль: Solid")
        self.style_btn.clicked.connect(self.toggle_visualization_style)
        controls_layout.addWidget(self.style_btn)

        self.grid_btn = QPushButton("Сетка: Вкл")
        self.grid_btn.clicked.connect(self.toggle_grid)
        controls_layout.addWidget(self.grid_btn)

        self.edges_btn = QPushButton("Грани: Вкл")
        self.edges_btn.clicked.connect(self.toggle_edges)
        controls_layout.addWidget(self.edges_btn)

        self.reset_view_btn = QPushButton("Сброс вида")
        self.reset_view_btn.clicked.connect(self.reset_view)
        controls_layout.addWidget(self.reset_view_btn)

        self.cancel_btn = QPushButton("Отменить")
        self.cancel_btn.clicked.connect(self.cancel_visualization_loading)
        self.cancel_btn.setEnabled(False)
        controls_layout.addWidget(self.cancel_btn)

        controls_group.setMaximumHeight(70)

        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)

        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Основной сплиттер
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        left_layout.addWidget(QLabel("IFC файлы:"))
        left_layout.addWidget(self.file_list)

        left_layout.addWidget(QLabel("Иерархия модели:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Элементы модели")
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        left_layout.addWidget(self.tree)

        main_splitter.addWidget(left_widget)

        # Центральная панель
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.addWidget(QLabel("3D Визуализация:"))
        self.pyvista_widget = QWidget()
        center_layout.addWidget(self.pyvista_widget)
        main_splitter.addWidget(center_widget)

        # Правая панель
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        self.right_tabs = QTabWidget()

        self.attributes_table = QTableWidget()
        self.attributes_table.setColumnCount(3)
        self.attributes_table.setHorizontalHeaderLabels(
            ["Группа", "Атрибут", "Значение"]
        )
        self.attributes_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.right_tabs.addTab(self.attributes_table, "Атрибуты")

        self.properties_table = QTableWidget()
        self.properties_table.setColumnCount(3)
        self.properties_table.setHorizontalHeaderLabels(
            ["Набор свойств", "Свойство", "Значение"]
        )
        self.properties_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.right_tabs.addTab(self.properties_table, "Свойства IFC")

        self.materials_table = QTableWidget()
        self.materials_table.setColumnCount(2)
        self.materials_table.setHorizontalHeaderLabels(["Материал", "Объем (м³)"])
        self.materials_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.right_tabs.addTab(self.materials_table, "Материалы")

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Параметр", "Значение"])
        self.right_tabs.addTab(self.stats_table, "Статистика")

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier New", 12))
        self.right_tabs.addTab(self.log_text, "Логи")

        right_layout.addWidget(self.right_tabs)
        main_splitter.addWidget(right_widget)

        main_splitter.setSizes([300, 900, 400])
        main_layout.addWidget(main_splitter)

        self.init_pyvista()
        self.log("Программа запущена. Выберите директорию с IFC файлами.")

    def init_pyvista(self):
        """Инициализация PyVista виджета"""
        try:
            self.plotter = QtInteractor(self.pyvista_widget)
            self.plotter.set_background("silver")
            self.plotter.show_axes()
            layout = QVBoxLayout(self.pyvista_widget)
            layout.addWidget(self.plotter.interactor)
            layout.setContentsMargins(0, 0, 0, 0)
            self.plotter.show()
            self.log("PyVista инициализирован успешно")
        except Exception as e:
            self.log(f"Ошибка инициализации PyVista: {str(e)}")

    # ==================== Управление визуализацией ====================
    def toggle_visualization_style(self):
        """Переключение стиля визуализации"""
        if not hasattr(self, "current_style"):
            self.current_style = 0

        styles = ["solid", "wireframe", "points"]
        self.current_style = (self.current_style + 1) % len(styles)
        style_names = ["Solid", "Wireframe", "Points"]
        self.style_btn.setText(f"Стиль: {style_names[self.current_style]}")

        for actor in self.plotter.renderer.actors.values():
            try:
                if hasattr(actor, "GetProperty") and hasattr(
                    actor.GetProperty(), "SetRepresentationToWireframe"
                ):
                    prop = actor.GetProperty()
                    if self.current_style == 0:
                        prop.SetRepresentationToSurface()
                    elif self.current_style == 1:
                        prop.SetRepresentationToWireframe()
                    else:
                        prop.SetRepresentationToPoints()
            except AttributeError:
                pass

        self.plotter.render()

    def change_opacity(self, value):
        """Изменение прозрачности"""
        self.opacity_label.setText(f"{value}%")
        opacity = value / 100.0

        for actor in self.plotter.renderer.actors.values():
            try:
                if hasattr(actor, "GetProperty") and hasattr(
                    actor.GetProperty(), "SetOpacity"
                ):
                    actor.GetProperty().SetOpacity(opacity)
            except AttributeError:
                pass

        self.plotter.render()

    def toggle_grid(self):
        """Включение/выключение сетки"""
        if not hasattr(self, "grid_enabled"):
            self.grid_enabled = True

        if self.grid_enabled:
            self.plotter.show_grid()
            self.grid_btn.setText("Сетка: Выкл")
        else:
            for actor in list(self.plotter.renderer.actors.values()):
                if hasattr(actor, "GetClassName") and "Grid" in actor.GetClassName():
                    self.plotter.renderer.RemoveActor(actor)
            self.grid_btn.setText("Сетка: Вкл")

        self.grid_enabled = not self.grid_enabled
        self.plotter.render()

    def toggle_edges(self):
        """Включение/выключение отображения граней"""
        if not hasattr(self, "edges_enabled"):
            self.edges_enabled = True

        for actor in self.plotter.renderer.actors.values():
            try:
                if hasattr(actor, "GetProperty") and hasattr(
                    actor.GetProperty(), "SetEdgeVisibility"
                ):
                    actor.GetProperty().SetEdgeVisibility(self.edges_enabled)
                    if self.edges_enabled:
                        actor.GetProperty().SetEdgeColor(0, 0, 0)
            except AttributeError:
                pass

        self.edges_btn.setText("Грани: Выкл" if self.edges_enabled else "Грани: Вкл")
        self.edges_enabled = not self.edges_enabled
        self.plotter.render()

    def reset_view(self):
        """Сброс вида камеры"""
        self.plotter.reset_camera()
        self.plotter.render()

    def cancel_visualization_loading(self):
        """Отмена загрузки визуализации"""
        self.cancel_visualization = True
        self.log("Визуализация отменена пользователем")

    # ==================== Работа с файлами ====================
    def select_directory(self):
        """Выбор директории с IFC файлами"""
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите директорию с IFC файлами", ""
        )
        if directory:
            self.log(f"Выбрана директория: {directory}")
            self.current_directory = directory
            self.load_ifc_files_from_directory(directory)

    def load_ifc_files_from_directory(self, directory):
        """Загрузка списка IFC файлов из директории с размерами"""
        self.file_list.clear()

        ifc_extensions = [".ifc", ".IFC", ".ifcxml", ".ifczip"]

        for file in os.listdir(directory):
            if any(file.endswith(ext) for ext in ifc_extensions):
                filepath = os.path.join(directory, file)
                size_bytes = os.path.getsize(filepath)
                size_mb = size_bytes / (1024 * 1024)

                if size_mb < 1:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_mb:.1f} MB"

                self.file_list.addItem(f"{file}  [{size_str}]")
                # Сохраняем реальное имя файла в данные элемента списка
                self.file_list.item(self.file_list.count() - 1).setData(
                    Qt.ItemDataRole.UserRole, file
                )

        if self.file_list.count() == 0:
            self.log("В выбранной директории не найдено IFC файлов")
        else:
            self.log(f"Найдено {self.file_list.count()} IFC файлов")

    def on_file_selected(self):
        """Обработка выбора файлов из списка"""
        selected_items = self.file_list.selectedItems()
        if selected_items:
            self.selected_files = []
            for item in selected_items:
                filename = item.data(Qt.ItemDataRole.UserRole)
                if not filename:
                    text = item.text()
                    filename = text.split("  [")[0]
                self.selected_files.append(filename)

            self.read_btn.setEnabled(len(self.selected_files) == 1)
            self.batch_convert_btn.setEnabled(len(self.selected_files) >= 1)
            self.log(f"Выбрано файлов: {len(self.selected_files)}")
        else:
            self.read_btn.setEnabled(False)
            self.batch_convert_btn.setEnabled(False)
            self.selected_files = []

    def read_ifc_file(self):
        """Чтение выбранного IFC файла и объединение с существующей моделью"""
        if not self.selected_files or not self.current_directory:
            self.log("Ошибка: Файл не выбран")
            return

        filepath = os.path.join(self.current_directory, self.selected_files[0])

        if filepath in self.loaded_files:
            self.log(f"Файл {self.selected_files[0]} уже загружен")
            return

        self.log(f"Загрузка и объединение файла: {self.selected_files[0]}")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = LoadWorker(filepath)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_load_finished_merge)
        self.worker.error.connect(self.on_load_error)
        self.worker.start()

    def update_progress(self, value, message):
        """Обновление прогресса загрузки"""
        self.progress_bar.setValue(value)
        self.log(message)

    def on_load_error(self, error_msg):
        """Обработка ошибки загрузки"""
        self.progress_bar.setVisible(False)
        self.log(f"ОШИБКА загрузки: {error_msg}")

    def on_load_finished_merge(self, ifc_file, hierarchy, stats):
        """Обработка завершения загрузки с объединением моделей"""
        self.ifc_file = ifc_file
        self.progress_bar.setVisible(False)

        self.log("\n" + "=" * 60)
        self.log("ЗАГРУЗКА НОВОГО ФАЙЛА")
        self.log(f"Файл: {self.selected_files[0]}")
        self.log(
            f"Размер: {stats.file_size_mb:.2f} MB | Элементов: {stats.elements_count}"
        )
        self.log(f"Время загрузки: {stats.total_time:.3f} сек")
        self.log("=" * 60)

        filepath = os.path.join(self.current_directory, self.selected_files[0])
        self.loaded_files.append(filepath)

        self.update_tree_with_file(hierarchy, self.selected_files[0])
        self.visualize_model_merge(ifc_file, self.selected_files[0])

    def update_tree_with_file(self, hierarchy, filename):
        """Обновление дерева иерархии с добавлением нового файла"""
        file_item = QTreeWidgetItem([f"📁 {filename}"])
        file_item.setData(0, Qt.ItemDataRole.UserRole, {"name": filename})

        total_elements = 0
        for category_name, category_data in hierarchy["children"].items():
            category_item = QTreeWidgetItem(
                [f"{category_name} ({len(category_data['elements'])} эл.)"]
            )
            category_item.setData(0, Qt.ItemDataRole.UserRole, category_data)

            for elem in category_data["elements"]:
                elem_item = QTreeWidgetItem([f"{elem['name']} (ID: {elem['id']})"])
                elem_item.setData(0, Qt.ItemDataRole.UserRole, elem)
                category_item.addChild(elem_item)

            file_item.addChild(category_item)
            total_elements += len(category_data["elements"])

        self.tree.addTopLevelItem(file_item)
        file_item.setExpanded(True)

    def clear_model(self):
        """Очистка текущей модели"""
        self.plotter.clear()
        self.plotter.set_background("silver")
        self.element_actors.clear()
        self.loaded_files.clear()
        self.tree.clear()
        self.attributes_table.setRowCount(0)
        self.properties_table.setRowCount(0)
        self.materials_table.setRowCount(0)
        self.stats_table.setRowCount(0)
        if hasattr(self, "combined_mesh"):
            delattr(self, "combined_mesh")
        self.log("Модель очищена")

    # ==================== Визуализация ====================
    def visualize_model_merge(self, ifc_file, filename):
        """Визуализация нового файла и объединение с существующей моделью"""
        if not ifc_file:
            return

        self.cancel_btn.setEnabled(True)
        self.cancel_visualization = False

        try:
            self.log(f"Начинаем объединение геометрии из {filename}...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)

            elements_to_process = []
            for elem_type in self.geometry_types:
                try:
                    elements = ifc_file.by_type(elem_type)
                    if elements:
                        elements_to_process.extend(elements)
                except:
                    pass

            if not elements_to_process:
                elements_to_process = ifc_file.by_type("IfcProduct")

            total_elements = len(elements_to_process)
            self.log(f"Обработка {total_elements} элементов для объединения...")

            new_vertices = []
            new_faces = []
            vertex_offset = (
                len(getattr(self, "combined_mesh", pv.PolyData()).points)
                if hasattr(self, "combined_mesh")
                else 0
            )
            new_element_actors = {}
            success_count = 0

            for i, element in enumerate(elements_to_process):
                if self.cancel_visualization:
                    self.log("Объединение прервано")
                    return

                if i % 100 == 0:
                    progress = int((i / total_elements) * 90)
                    self.progress_bar.setValue(progress)
                    QApplication.processEvents()

                try:
                    shape = ifcopenshell.geom.create_shape(settings, element)

                    if shape and shape.geometry:
                        verts = np.array(shape.geometry.verts).reshape(-1, 3)
                        faces = shape.geometry.faces

                        if len(verts) > 0 and len(faces) > 0:
                            color = self.get_element_color_from_shape(shape, element)
                            if not color:
                                color = self.get_default_color_by_type(element.is_a())

                            for vert in verts:
                                new_vertices.append(vert)

                            for j in range(0, len(faces), 3):
                                new_faces.append(3)
                                new_faces.append(faces[j] + vertex_offset)
                                new_faces.append(faces[j + 1] + vertex_offset)
                                new_faces.append(faces[j + 2] + vertex_offset)

                            vertex_offset += len(verts)
                            success_count += 1

                            try:
                                elem_id = (
                                    element.GlobalId
                                    if hasattr(element, "GlobalId")
                                    else str(element.id())
                                )
                            except:
                                elem_id = f"{filename}_{i}"

                            elem_name = getattr(element, "Name", f"Unnamed_{elem_id}")
                            elem_type = element.is_a()

                            new_element_actors[elem_id] = {
                                "name": elem_name,
                                "type": elem_type,
                                "id": elem_id,
                                "color": color,
                                "source_file": filename,
                            }

                except Exception as e:
                    continue

            self.progress_bar.setValue(95)

            if len(new_vertices) > 0:
                new_mesh = pv.PolyData(np.array(new_vertices), np.array(new_faces))

                if hasattr(self, "combined_mesh") and self.combined_mesh.n_points > 0:
                    self.combined_mesh = self.combined_mesh.append_polydata(new_mesh)
                else:
                    self.combined_mesh = new_mesh

                self.element_actors.update(new_element_actors)

                self.plotter.clear()
                self.plotter.set_background("silver")
                self.plotter.add_mesh(
                    self.combined_mesh,
                    color=(0.7, 0.7, 0.7),
                    show_edges=False,
                    opacity=0.7,
                    lighting=True,
                    smooth_shading=True,
                )
                self.plotter.add_text(
                    f"IFC Model\nFiles: {len(self.loaded_files)}\nElements: {len(self.element_actors)}",
                    position="upper_left",
                    font_size=12,
                    font="arial",
                    color="black",
                )
                self.plotter.show_axes()
                self.plotter.reset_camera()
                self.plotter.show()

                self.log(
                    f"Объединение завершено. Добавлено {success_count} элементов из {filename}"
                )
                self.update_statistics_merged()
            else:
                self.log(f"Нет геометрии для добавления из {filename}")

            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.cancel_btn.setEnabled(False)

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.log(f"Ошибка объединения: {str(e)}")
            import traceback

            self.log(traceback.format_exc())

    def get_element_color_from_shape(self, shape, element):
        """Извлечение цвета из shape геометрии элемента"""
        try:
            materials = shape.geometry.materials
            if materials and len(materials) > 0:
                diffuse_value = str(materials[0].diffuse)
                if diffuse_value and diffuse_value.startswith("colour"):
                    parts = diffuse_value.split()
                    if len(parts) >= 4:
                        r = float(parts[1])
                        g = float(parts[2])
                        b = float(parts[3])
                        return (r, g, b)
        except:
            pass
        return None

    def get_default_color_by_type(self, elem_type):
        """Определение цвета по типу элемента IFC"""
        colors = {
            "IfcWall": (0.678, 0.847, 0.902),
            "IfcWallStandardCase": (0.678, 0.847, 0.902),
            "IfcSlab": (0.753, 0.753, 0.753),
            "IfcBeam": (0.647, 0.165, 0.165),
            "IfcColumn": (0.663, 0.663, 0.663),
            "IfcDoor": (1.000, 0.647, 0.000),
            "IfcWindow": (0.000, 1.000, 1.000),
            "IfcRoof": (1.000, 0.000, 0.000),
            "IfcStair": (0.000, 0.502, 0.000),
            "IfcRamp": (0.133, 0.545, 0.133),
            "IfcPlate": (0.753, 0.753, 0.753),
            "IfcCovering": (0.961, 0.961, 0.863),
            "IfcCurtainWall": (0.678, 0.847, 0.902),
            "IfcBuildingElementProxy": (0.800, 0.600, 1.000),
            "IfcMember": (1.000, 0.843, 0.000),
            "IfcFooting": (0.545, 0.271, 0.075),
            "IfcPile": (0.804, 0.522, 0.247),
            "IfcRailing": (0.000, 0.000, 0.545),
        }
        for key in colors:
            if key in elem_type:
                return colors[key]
        return (0.800, 0.800, 0.800)

    def show_demo_geometry(self):
        """Отображение демонстрационной геометрии"""
        self.plotter.clear()
        self.plotter.set_background("silver")
        cube = pv.Cube()
        self.plotter.add_mesh(cube, color="lightblue", show_edges=True, opacity=0.7)
        self.plotter.add_text(
            "DEMO MODE\nCould not extract geometry from IFC",
            position="upper_left",
            font_size=12,
            font="arial",
            color="red",
        )
        self.plotter.show()

    # ==================== Обработка выбора элемента ====================
    def on_tree_item_clicked(self, item, column):
        """Обработка клика по элементу дерева"""
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if data and isinstance(data, dict):
            self.attributes_table.setRowCount(0)
            row = 0
            for key, value in data.items():
                if key != "children":
                    self.attributes_table.insertRow(row)
                    self.attributes_table.setItem(row, 0, QTableWidgetItem("Элемент"))
                    self.attributes_table.setItem(row, 1, QTableWidgetItem(str(key)))
                    self.attributes_table.setItem(row, 2, QTableWidgetItem(str(value)))
                    row += 1

            element_id = data.get("global_id") or data.get("id")
            element_name = data.get("name", "Unknown")
            self.log(f"Выделен элемент: {element_name} (ID: {element_id})")

    # ==================== Статистика ====================
    def update_statistics_merged(self):
        """Обновление статистики для объединенной модели"""
        if not self.element_actors:
            return

        type_counts = defaultdict(int)
        files_count = defaultdict(int)

        for elem_id, elem_info in self.element_actors.items():
            type_counts[elem_info["type"]] += 1
            if "source_file" in elem_info:
                files_count[elem_info["source_file"]] += 1

        self.stats_table.setRowCount(0)

        stats = [
            ("Всего загружено файлов", len(self.loaded_files)),
            ("Всего элементов", len(self.element_actors)),
            ("Всего типов элементов", len(type_counts)),
            ("", ""),
            ("--- Распределение по файлам ---", ""),
        ]

        for stat_name, stat_value in stats:
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            self.stats_table.setItem(row, 0, QTableWidgetItem(stat_name))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(stat_value)))

        for filename, count in sorted(
            files_count.items(), key=lambda x: x[1], reverse=True
        ):
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            self.stats_table.setItem(
                row, 0, QTableWidgetItem(f"  {os.path.basename(filename)}")
            )
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(count)))

        row = self.stats_table.rowCount()
        self.stats_table.insertRow(row)
        self.stats_table.setItem(
            row, 0, QTableWidgetItem("--- Распределение по типам ---")
        )
        self.stats_table.setItem(row, 1, QTableWidgetItem(""))

        for elem_type, count in sorted(
            type_counts.items(), key=lambda x: x[1], reverse=True
        ):
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            self.stats_table.setItem(row, 0, QTableWidgetItem(f"  {elem_type}"))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(count)))

    # ==================== Конвертация ====================
    def convert_to_glb(self):
        """Конвертация текущей модели в GLB"""
        if not self.element_actors:
            self.log("Нет загруженной модели для конвертации")
            return

        if not hasattr(self, "combined_mesh") or self.combined_mesh.n_points == 0:
            self.log("Нет геометрии для конвертации")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Сохранить GLB файл", self.current_directory, "GLB Files (*.glb)"
        )

        if not filepath:
            return

        self.log(f"Экспорт модели в GLB: {filepath}")
        try:
            self.combined_mesh.save(filepath, binary=True)
            self.log(f"Экспорт завершен: {filepath}")
        except Exception as e:
            self.log(f"Ошибка экспорта: {str(e)}")

    def batch_convert_to_glb(self):
        """Пакетная конвертация выбранных IFC файлов в GLB"""
        if not self.selected_files or not self.current_directory:
            self.log("Выберите файлы для конвертации")
            return

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить объединенный GLB файл",
            self.current_directory,
            "GLB Files (*.glb)",
        )

        if not output_file:
            return

        filepaths = [
            os.path.join(self.current_directory, f) for f in self.selected_files
        ]

        self.log(f"Начинаем пакетную конвертацию {len(filepaths)} файлов")

        self.batch_worker = BatchConvertWorker(filepaths, output_file)
        self.batch_worker.progress.connect(self.update_progress)
        self.batch_worker.file_progress.connect(self.batch_file_progress)
        self.batch_worker.finished.connect(self.on_batch_finished)
        self.batch_worker.error.connect(self.on_convert_error)
        self.batch_worker.start()

        self.progress_bar.setVisible(True)
        self.batch_convert_btn.setEnabled(False)

    def batch_file_progress(self, filename, current, total):
        """Прогресс обработки текущего файла"""
        self.log(f"[{current}/{total}] Обработка: {os.path.basename(filename)}")

    def on_batch_finished(self, output_file):
        """Обработка завершения пакетной конвертации"""
        self.progress_bar.setVisible(False)
        self.batch_convert_btn.setEnabled(True)
        self.log(f"Пакетная конвертация завершена! Файл сохранен: {output_file}")

        reply = QMessageBox.question(
            self,
            "Конвертация завершена",
            f"Файл сохранен:\n{output_file}\n\nОткрыть папку?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import platform
            import subprocess

            folder = os.path.dirname(output_file)
            if platform.system() == "Windows":
                os.startfile(folder)
            elif platform.system() == "Darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])

    def on_convert_error(self, error_msg):
        """Обработка ошибки конвертации"""
        self.progress_bar.setVisible(False)
        self.batch_convert_btn.setEnabled(True)
        self.log(f"ОШИБКА конвертации: {error_msg}")

    def log(self, message):
        """Вывод сообщения в лог"""
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    viewer = IFCViewer()
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
