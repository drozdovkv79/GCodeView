import os
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
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
    finished = pyqtSignal(object, object, LoadStats)  # ifc_file, hierarchy, stats
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

            # Используем lazy=True для больших файлов
            use_lazy = file_size > 100 * 1024 * 1024
            start_time = time.time()

            if use_lazy:
                ifc_file = ifcopenshell.open(self.filepath, lazy=True)
                self.progress.emit(
                    20,
                    f"Файл открыт в lazy режиме (размер: {stats.file_size_mb:.1f} MB)",
                )
            else:
                ifc_file = ifcopenshell.open(self.filepath)
                self.progress.emit(
                    20, f"Файл открыт (размер: {stats.file_size_mb:.1f} MB)"
                )

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

        # Группировка по классам
        for elem in elements[:1000]:  # Ограничиваем для производительности
            elem_type = elem.is_a()
            if elem_type not in hierarchy["children"]:
                hierarchy["children"][elem_type] = {
                    "name": elem_type,
                    "children": {},
                    "elements": [],
                }

            # Добавляем элемент с его атрибутами
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


class IFCViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ifc_file = None
        self.current_filepath = None
        self.plotter = None
        self.mesh = None
        self.element_actors = {}  # Словарь для хранения actor'ов
        self.highlighted_actor = None  # Текущий подсвеченный actor
        self.init_ui()

    def init_ui(self):
        """Инициализация пользовательского интерфейса"""
        self.setWindowTitle("IFC Viewer - Анализ больших моделей зданий")
        self.setGeometry(100, 100, 1600, 900)

        # Устанавливаем шрифт Arial 12pt для всего приложения
        font = QFont("Arial", 12)
        self.setFont(font)

        # Основной виджет
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

        self.convert_btn = QPushButton("Конвертировать")
        self.convert_btn.clicked.connect(lambda: self.show_message("Конвертировать"))
        button_layout.addWidget(self.convert_btn)

        self.merge_btn = QPushButton("Объединить")
        self.merge_btn.clicked.connect(lambda: self.show_message("Объединить"))
        button_layout.addWidget(self.merge_btn)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self.visualization_controls = self.add_visualization_controls()
        self.visualization_controls.setMaximumHeight(70)
        main_layout.addWidget(self.visualization_controls)

        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Основной сплиттер
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель с файлами и деревом
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Список IFC файлов
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        left_layout.addWidget(QLabel("IFC файлы:"))
        left_layout.addWidget(self.file_list)

        # Дерево иерархии
        left_layout.addWidget(QLabel("Иерархия модели:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Элементы модели")
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        left_layout.addWidget(self.tree)

        main_splitter.addWidget(left_widget)

        # Центральная панель - визуализация
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.addWidget(QLabel("3D Визуализация:"))

        # Контейнер для PyVista
        self.pyvista_widget = QWidget()
        center_layout.addWidget(self.pyvista_widget)

        main_splitter.addWidget(center_widget)

        # Правая панель - вкладки
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        self.right_tabs = QTabWidget()

        # Вкладка атрибутов
        self.attributes_table = QTableWidget()
        self.attributes_table.setColumnCount(3)
        self.attributes_table.setHorizontalHeaderLabels(
            ["Группа", "Атрибут", "Значение"]
        )
        self.attributes_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.right_tabs.addTab(self.attributes_table, "Атрибуты")

        # Вкладка логов
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier New", 12))
        self.right_tabs.addTab(self.log_text, "Логи")

        right_layout.addWidget(self.right_tabs)
        main_splitter.addWidget(right_widget)

        # Настройка пропорций сплиттера
        main_splitter.setSizes([300, 900, 400])
        main_layout.addWidget(main_splitter)

        # Инициализация PyVista
        self.init_pyvista()

        # Логируем запуск
        self.log("Программа запущена. Выберите директорию с IFC файлами.")

    def init_pyvista(self):
        """Инициализация PyVista виджета"""
        try:
            # Создаем QtInteractor для интеграции с PyQt
            self.plotter = QtInteractor(self.pyvista_widget)
            self.plotter.set_background("silver")  # Silver фон

            # Добавляем оси для ориентации
            self.plotter.show_axes()

            # Применяем шрифт для текста в сцене
            self.plotter.add_text("IFC Model", font_size=12, font="arial")

            layout = QVBoxLayout(self.pyvista_widget)
            layout.addWidget(self.plotter.interactor)
            layout.setContentsMargins(0, 0, 0, 0)

            self.plotter.show()
            self.log("PyVista инициализирован успешно")
        except Exception as e:
            self.log(f"Ошибка инициализации PyVista: {str(e)}")

    def add_visualization_controls(self):
        """Добавление кнопок управления визуализацией"""
        controls_group = QGroupBox("Режимы визуализации")
        controls_layout = QHBoxLayout()

        self.style_btn = QPushButton("Стиль: Solid")
        self.style_btn.clicked.connect(self.toggle_visualization_style)
        controls_layout.addWidget(self.style_btn)

        # Исправленный слайдер прозрачности
        controls_layout.addWidget(QLabel("Прозрачность:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(70)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        controls_layout.addWidget(self.opacity_slider)

        self.opacity_label = QLabel("70%")
        controls_layout.addWidget(self.opacity_label)

        self.grid_btn = QPushButton("Сетка: Вкл")
        self.grid_btn.clicked.connect(self.toggle_grid)
        controls_layout.addWidget(self.grid_btn)

        self.edges_btn = QPushButton("Грани: Вкл")
        self.edges_btn.clicked.connect(self.toggle_edges)
        controls_layout.addWidget(self.edges_btn)

        self.reset_view_btn = QPushButton("Сброс вида")
        self.reset_view_btn.clicked.connect(self.reset_view)
        controls_layout.addWidget(self.reset_view_btn)

        controls_group.setLayout(controls_layout)
        return controls_group

    def toggle_visualization_style(self):
        """Переключение стиля визуализации"""
        if not hasattr(self, "current_style"):
            self.current_style = 0

        styles = ["solid", "wireframe", "points"]
        self.current_style = (self.current_style + 1) % len(styles)

        style_names = ["Solid", "Wireframe", "Points"]
        self.style_btn.setText(f"Стиль: {style_names[self.current_style]}")

        # Применяем стиль только к 3D mesh объектам
        for actor in self.plotter.renderer.actors.values():
            try:
                # Проверяем, есть ли нужные методы (это 3D объект)
                if hasattr(actor, "GetProperty") and hasattr(
                    actor.GetProperty(), "SetRepresentationToWireframe"
                ):
                    prop = actor.GetProperty()
                    if self.current_style == 0:  # Solid
                        prop.SetRepresentationToSurface()
                    elif self.current_style == 1:  # Wireframe
                        prop.SetRepresentationToWireframe()
                    else:  # Points
                        prop.SetRepresentationToPoints()
            except AttributeError:
                # Пропускаем 2D объекты (текст, оси и т.д.)
                pass

        self.plotter.render()

    def change_opacity(self, value):
        """Изменение прозрачности"""
        if not hasattr(self, "opacity_label"):
            self.opacity_label = QLabel(f"Прозрачность: {value}%")

        self.opacity_label.setText(f"Прозрачность: {value}%")
        opacity = value / 100.0

        for actor in self.plotter.renderer.actors.values():
            try:
                # Применяем только к 3D объектам
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
            # Удаляем сетку
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
                        actor.GetProperty().SetEdgeColor(0, 0, 0)  # Черные грани
            except AttributeError:
                pass

        self.edges_btn.setText("Грани: Выкл" if self.edges_enabled else "Грани: Вкл")
        self.edges_enabled = not self.edges_enabled
        self.plotter.render()

    def reset_view(self):
        """Сброс вида камеры"""
        self.plotter.reset_camera()
        self.plotter.render()

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

                # Форматируем размер
                if size_mb < 1:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_mb:.1f} MB"

                # Добавляем файл с размером
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
        """Обработка выбора файла из списка"""
        selected_items = self.file_list.selectedItems()
        if selected_items:
            # Получаем реальное имя файла из данных
            self.selected_filename = selected_items[0].data(Qt.ItemDataRole.UserRole)
            if not self.selected_filename:
                # Fallback: извлекаем из отображаемого текста
                text = selected_items[0].text()
                self.selected_filename = text.split("  [")[0]
            self.read_btn.setEnabled(True)
            self.log(f"Выбран файл: {self.selected_filename}")
        else:
            self.read_btn.setEnabled(False)

    def read_ifc_file(self):
        """Чтение выбранного IFC файла"""
        if not hasattr(self, "selected_filename") or not hasattr(
            self, "current_directory"
        ):
            self.log("Ошибка: Файл не выбран")
            return

        filepath = os.path.join(self.current_directory, self.selected_filename)

        self.log(f"Начинаем загрузку файла: {self.selected_filename}")

        # Запускаем загрузку в отдельном потоке
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = LoadWorker(filepath)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_load_finished)
        self.worker.error.connect(self.on_load_error)
        self.worker.start()

    def update_progress(self, value, message):
        """Обновление прогресса загрузки"""
        self.progress_bar.setValue(value)
        self.log(message)

    def on_load_finished(self, ifc_file, hierarchy, stats):
        """Обработка завершения загрузки"""
        self.ifc_file = ifc_file
        self.progress_bar.setVisible(False)

        # Вывод подробной статистики
        self.log("\n" + "=" * 60)
        self.log("СТАТИСТИКА ЗАГРУЗКИ IFC ФАЙЛА")
        self.log("=" * 60)
        self.log(f"Файл: {self.selected_filename}")
        self.log(f"Размер файла: {stats.file_size_mb:.2f} MB")
        self.log(f"Общее время загрузки: {stats.total_time:.3f} сек")
        self.log(f"\n--- Детализация по категориям ---")
        self.log(
            f"Элементы (IfcProduct): {stats.elements_count} шт, время: {stats.elements_time:.3f} сек"
        )
        self.log(
            f"Материалы (IfcMaterial): {stats.materials_count} шт, время: {stats.materials_time:.3f} сек"
        )
        self.log(
            f"Геометрия: {stats.geometry_count} шт, время: {stats.geometry_time:.3f} сек"
        )
        self.log(
            f"Цвета и стили: {stats.colors_count} шт, время: {stats.colors_time:.3f} сек"
        )
        self.log(
            f"Отношения: {stats.relationships_count} шт, время: {stats.relationships_time:.3f} сек"
        )
        self.log(
            f"\nПамять: {'Lazy режим (оптимизирован для больших файлов)' if stats.file_size_mb > 100 else 'Полная загрузка в RAM'}"
        )
        self.log("=" * 60)

        # Обновление дерева иерархии
        self.update_tree(hierarchy)

        # Визуализация модели
        self.visualize_model()

    def on_load_error(self, error_msg):
        """Обработка ошибки загрузки"""
        self.progress_bar.setVisible(False)
        self.log(f"ОШИБКА загрузки: {error_msg}")

    def update_tree(self, hierarchy):
        """Обновление дерева иерархии"""
        self.tree.clear()

        total_elements = 0
        for category_name, category_data in hierarchy["children"].items():
            category_item = QTreeWidgetItem([category_name])
            category_item.setData(0, Qt.ItemDataRole.UserRole, category_data)

            elem_count = len(category_data["elements"])
            total_elements += elem_count
            category_item.setText(0, f"{category_name} ({elem_count} эл.)")

            # Добавляем только первые 50 элементов для производительности
            for elem in category_data["elements"][:50]:
                elem_item = QTreeWidgetItem([f"{elem['name']} (ID: {elem['id']})"])
                elem_item.setData(0, Qt.ItemDataRole.UserRole, elem)
                category_item.addChild(elem_item)

            if len(category_data["elements"]) > 50:
                more_item = QTreeWidgetItem(
                    [f"... и еще {len(category_data['elements']) - 50} элементов"]
                )
                category_item.addChild(more_item)

            self.tree.addTopLevelItem(category_item)

        self.log(
            f"Построена иерархия: {len(hierarchy['children'])} категорий, {total_elements} элементов"
        )

    def get_element_material_color(self, shape):
        """Извлечение цвета материала из геометрии shape (рабочий способ)"""
        try:
            # Получаем материалы из геометрии
            materials = shape.geometry.materials
            material_ids = shape.geometry.material_ids

            if len(materials) > 0 and len(material_ids) > 0:
                # Берем первый материал (основной)
                material = materials[0]

                # Получаем diffuse цвет (RGB)
                if hasattr(material, "diffuse"):
                    diffuse = material.diffuse
                    if diffuse and len(diffuse) >= 3:
                        return (diffuse[0], diffuse[1], diffuse[2])

                # Альтернативно пытаемся получить цвет из SurfaceColour через другой путь
                if hasattr(material, "surface_colour"):
                    colour = material.surface_colour
                    if colour and hasattr(colour, "Red"):
                        return (colour.Red, colour.Green, colour.Blue)

                # Проверяем наличие SurfaceStyleRendering в материале
                if hasattr(material, "has_surface_style_rendering"):
                    if material.has_surface_style_rendering():
                        rendering = material.surface_style_rendering()
                        if rendering and hasattr(rendering, "SurfaceColour"):
                            colour = rendering.SurfaceColour
                            if colour and hasattr(colour, "Red"):
                                return (colour.Red, colour.Green, colour.Blue)

        except Exception as e:
            pass

        return None

    def extract_materials_from_ifc(self, ifc_file, element):
        """Альтернативный метод: поиск материала элемента через IfcRelAssociatesMaterial"""
        try:
            # Ищем ассоциации материала
            if hasattr(element, "HasAssociations"):
                for rel in element.HasAssociations:
                    if rel.is_a("IfcRelAssociatesMaterial"):
                        material_assoc = rel.RelatingMaterial

                        # Если материал представлен как IfcMaterial
                        if material_assoc.is_a("IfcMaterial"):
                            # Ищем стиль через материал
                            if hasattr(material_assoc, "HasRepresentation"):
                                for rep in material_assoc.HasRepresentation:
                                    if rep.is_a("IfcMaterialDefinitionRepresentation"):
                                        for rep_item in rep.Representations:
                                            if rep_item.is_a("IfcStyledRepresentation"):
                                                for styled_item in rep_item.Items:
                                                    if styled_item.is_a(
                                                        "IfcStyledItem"
                                                    ):
                                                        for style in styled_item.Styles:
                                                            color = self.extract_color_from_style_entity(
                                                                style
                                                            )
                                                            if color:
                                                                return color

                        # Если использован IfcMaterialList (IFC2X3)
                        if material_assoc.is_a("IfcMaterialList"):
                            for mat in material_assoc.Materials:
                                # Рекурсивно ищем цвет для каждого материала в списке
                                if hasattr(mat, "HasRepresentation"):
                                    for rep in mat.HasRepresentation:
                                        if rep.is_a(
                                            "IfcMaterialDefinitionRepresentation"
                                        ):
                                            for rep_item in rep.Representations:
                                                if rep_item.is_a(
                                                    "IfcStyledRepresentation"
                                                ):
                                                    for styled_item in rep_item.Items:
                                                        if styled_item.is_a(
                                                            "IfcStyledItem"
                                                        ):
                                                            for (
                                                                style
                                                            ) in styled_item.Styles:
                                                                color = self.extract_color_from_style_entity(
                                                                    style
                                                                )
                                                                if color:
                                                                    return color
        except Exception as e:
            pass

        return None

    def extract_color_from_style_entity(self, style_entity):
        """Извлечение цвета из IfcSurfaceStyle"""
        try:
            if style_entity.is_a("IfcSurfaceStyle"):
                for style_elem in style_entity.Styles:
                    # IfcSurfaceStyleRendering содержит цвет
                    if style_elem.is_a("IfcSurfaceStyleRendering"):
                        colour = style_elem.SurfaceColour
                        if colour and colour.is_a("IfcColourRgb"):
                            return (colour.Red, colour.Green, colour.Blue)

                    # IfcSurfaceStyleShading тоже содержит цвет
                    if style_elem.is_a("IfcSurfaceStyleShading"):
                        colour = style_elem.SurfaceColour
                        if colour and colour.is_a("IfcColourRgb"):
                            return (colour.Red, colour.Green, colour.Blue)

            # Проверяем IfcColourRgb напрямую
            if style_entity.is_a("IfcColourRgb"):
                return (style_entity.Red, style_entity.Green, style_entity.Blue)

        except Exception as e:
            pass

        return None

    def get_element_color_with_material_list(self, element):
        """Получение цвета через IfcMaterialList (для IFC2X3)"""
        try:
            # Ищем IfcRelAssociatesMaterial
            if hasattr(element, "HasAssociations"):
                for rel in element.HasAssociations:
                    if rel.is_a("IfcRelAssociatesMaterial"):
                        material_assoc = rel.RelatingMaterial

                        # Если это IfcMaterialList
                        if material_assoc.is_a("IfcMaterialList"):
                            for material in material_assoc.Materials:
                                # Пытаемся найти цвет для этого материала
                                if hasattr(material, "HasRepresentation"):
                                    for rep in material.HasRepresentation:
                                        if rep.is_a(
                                            "IfcMaterialDefinitionRepresentation"
                                        ):
                                            for rep_item in rep.Representations:
                                                if rep_item.is_a(
                                                    "IfcStyledRepresentation"
                                                ):
                                                    for styled_item in rep_item.Items:
                                                        if styled_item.is_a(
                                                            "IfcStyledItem"
                                                        ):
                                                            for (
                                                                style
                                                            ) in styled_item.Styles:
                                                                color = self.extract_color_from_style_entity(
                                                                    style
                                                                )
                                                                if color:
                                                                    return color
        except Exception as e:
            pass

        return None

    def extract_color_from_style(self, style):
        """Извлечение RGB цвета из стиля IFC"""
        try:
            # Проверяем IfcSurfaceStyle
            log("цвет:  " + style.Styles[0])
            if style.is_a("IfcSurfaceStyle"):
                for style_elem in style.Styles:
                    # IfcSurfaceStyleRendering содержит цвет
                    if style_elem.is_a("IfcSurfaceStyleRendering"):
                        color = style_elem.SurfaceColour
                        if color.is_a("IfcColourRgb"):
                            return (color.Red, color.Green, color.Blue)

                    # IfcSurfaceStyleShading тоже содержит цвет
                    if style_elem.is_a("IfcSurfaceStyleShading"):
                        color = style_elem.SurfaceColour
                        if color.is_a("IfcColourRgb"):
                            return (color.Red, color.Green, color.Blue)

            # Проверяем IfcColourRgb напрямую
            if style.is_a("IfcColourRgb"):
                return (style.Red, style.Green, style.Blue)

        except Exception as e:
            pass

        return None

    def get_default_color_by_type(self, element):
        """Определение цвета по типу элемента IFC (RGB кортеж от 0 до 1)"""
        elem_type = element.is_a()

        # Цветовая схема для разных типов элементов (RGB от 0 до 1)
        colors = {
            "IfcWall": (0.678, 0.847, 0.902),  # LightBlue
            "IfcWallStandardCase": (0.678, 0.847, 0.902),
            "IfcSlab": (0.753, 0.753, 0.753),  # LightGray
            "IfcBeam": (0.647, 0.165, 0.165),  # Brown
            "IfcColumn": (0.663, 0.663, 0.663),  # DarkGray
            "IfcDoor": (1.000, 0.647, 0.000),  # Orange
            "IfcWindow": (0.000, 1.000, 1.000),  # Cyan
            "IfcRoof": (1.000, 0.000, 0.000),  # Red
            "IfcStair": (0.000, 0.502, 0.000),  # Green
            "IfcRamp": (0.133, 0.545, 0.133),  # DarkGreen
            "IfcPlate": (0.753, 0.753, 0.753),  # Silver
            "IfcCovering": (0.961, 0.961, 0.863),  # Beige
            "IfcCurtainWall": (0.678, 0.847, 0.902),  # SkyBlue
            "IfcBuildingElementProxy": (0.800, 0.600, 1.000),  # Purple
            "IfcMember": (1.000, 0.843, 0.000),  # Gold
            "IfcFooting": (0.545, 0.271, 0.075),  # SaddleBrown
            "IfcPile": (0.804, 0.522, 0.247),  # Peru
            "IfcRailing": (0.000, 0.000, 0.545),  # DarkBlue
            "IfcFurniture": (0.600, 0.400, 0.200),  # Brown
            "IfcWindow": (0.000, 0.800, 0.800),  # Light Cyan
        }

        for key in colors:
            if key in elem_type:
                return colors[key]

        return (0.800, 0.800, 0.800)  # LightGray для неизвестных типов

    def color_to_pyvista_format(self, color):
        """Конвертация цвета в формат PyVista"""
        if isinstance(color, tuple) and len(color) == 3:
            # Для RGB значений от 0 до 1
            if max(color) <= 1.0:
                return color
            # Для RGB значений от 0 до 255
            else:
                return (color[0] / 255, color[1] / 255, color[2] / 255)
        elif isinstance(color, str):
            return color  # Имя цвета
        else:
            return (0.7, 0.7, 0.8)  # Цвет по умолчанию

    def visualize_model(self):
        """Визуализация всех элементов модели IFC с сохранением каждого элемента отдельно"""
        if not self.ifc_file:
            self.log("Нет загруженной модели для визуализации")
            return

        try:
            import ifcopenshell.geom
            import numpy as np

            self.log("Начинаем извлечение геометрии из IFC...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            # Настройки для извлечения геометрии
            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)

            # Получаем все элементы, которые имеют геометрию
            elements_to_process = []

            # Типы элементов, которые обычно имеют геометрию
            geometry_types = [
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

            # Собираем все элементы указанных типов
            for elem_type in geometry_types:
                try:
                    elements = self.ifc_file.by_type(elem_type)
                    if elements:
                        elements_to_process.extend(elements)
                        self.log(f"Найдено {len(elements)} элементов типа {elem_type}")
                except:
                    pass

            # Если не нашли специфические типы, берем все IfcProduct
            if not elements_to_process:
                elements_to_process = self.ifc_file.by_type("IfcProduct")
                self.log(f"Найдено продуктов: {len(elements_to_process)}")

            total_elements = len(elements_to_process)
            self.log(f"Всего элементов для визуализации: {total_elements}")

            # Очищаем словарь для хранения элементов
            self.element_actors = {}

            # Статистика
            success_count = 0
            color_found_count = 0

            # Очищаем предыдущую сцену
            self.plotter.clear()
            self.plotter.set_background("silver")

            # Обрабатываем каждый элемент отдельно
            for i, element in enumerate(elements_to_process):
                progress = int((i / total_elements) * 90)
                if i % 10 == 0:
                    self.progress_bar.setValue(progress)
                    self.log(
                        f"Обработка: {i + 1}/{total_elements} (добавлено: {success_count})"
                    )
                    QApplication.processEvents()

                try:
                    # Создаем геометрию элемента
                    shape = ifcopenshell.geom.create_shape(settings, element)

                    if shape and shape.geometry:
                        # Получаем вершины и грани
                        verts = np.array(shape.geometry.verts).reshape(-1, 3)
                        faces = shape.geometry.faces

                        if len(verts) > 0 and len(faces) > 0:
                            # Преобразуем грани в формат PyVista
                            pv_faces = []
                            for j in range(0, len(faces), 3):
                                pv_faces.append(3)
                                pv_faces.append(int(faces[j]))
                                pv_faces.append(int(faces[j + 1]))
                                pv_faces.append(int(faces[j + 2]))

                            # Создаем mesh
                            mesh = pv.PolyData(verts, np.array(pv_faces))

                            # Получаем цвет элемента
                            color = self.get_element_color_from_shape(shape, element)
                            if color:
                                color_found_count += 1
                            else:
                                color = self.get_default_color_by_type(element)

                            # Получаем ID элемента
                            try:
                                elem_id = (
                                    element.GlobalId
                                    if hasattr(element, "GlobalId")
                                    else str(element.id())
                                )
                            except:
                                elem_id = f"elem_{i}"

                            # Получаем имя элемента
                            elem_name = getattr(element, "Name", f"Unnamed_{elem_id}")
                            elem_type = element.is_a()

                            # Добавляем mesh на сцену ОТДЕЛЬНО (не объединяем)
                            actor = self.plotter.add_mesh(
                                mesh,
                                color=color,
                                show_edges=False,
                                opacity=0.7,
                                lighting=True,
                                smooth_shading=True,
                                name=f"element_{elem_id}",
                            )

                            # Сохраняем информацию об элементе
                            self.element_actors[elem_id] = {
                                "actor": actor,
                                "color": color,
                                "name": elem_name,
                                "type": elem_type,
                                "id": elem_id,
                            }

                            success_count += 1

                except Exception as e:
                    # Пропускаем элементы с ошибками
                    continue

            self.progress_bar.setValue(95)
            self.log(
                f"Геометрия извлечена. Успешно добавлено: {success_count} элементов, цветов найдено: {color_found_count}"
            )

            if success_count == 0:
                self.log("Не удалось извлечь геометрию ни одного элемента")
                self.show_demo_geometry()
                self.progress_bar.setVisible(False)
                return

            # Добавляем информационный текст
            self.plotter.add_text(
                f"IFC Model\nElements loaded: {success_count}\nColors found: {color_found_count}",
                position="upper_left",
                font_size=12,
                font="arial",
                color="black",
            )

            # Добавляем оси для ориентации
            self.plotter.show_axes()

            # Настраиваем камеру
            self.plotter.reset_camera()
            self.plotter.show()

            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.log(
                f"Визуализация завершена. Отображено {success_count} отдельных элементов"
            )

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.log(f"Ошибка визуализации: {str(e)}")
            import traceback

            self.log(traceback.format_exc())
            self.show_demo_geometry()

    def get_element_color(self, element):
        """Определение цвета элемента на основе его типа IFC"""
        elem_type = element.is_a()

        # Цветовая схема для разных типов элементов
        colors = {
            "IfcWall": "lightblue",
            "IfcWallStandardCase": "lightblue",
            "IfcSlab": "lightgray",
            "IfcBeam": "brown",
            "IfcColumn": "darkgray",
            "IfcDoor": "orange",
            "IfcWindow": "cyan",
            "IfcRoof": "red",
            "IfcStair": "green",
            "IfcRamp": "darkgreen",
            "IfcPlate": "silver",
            "IfcCovering": "beige",
            "IfcCurtainWall": "skyblue",
            "IfcBuildingElementProxy": "purple",
            "IfcMember": "gold",
            "IfcFooting": "saddlebrown",
            "IfcPile": "peru",
            "IfcRailing": "darkblue",
        }

        # Пытаемся получить цвет из материала элемента
        try:
            # Проверяем, есть ли у элемента материалы
            if hasattr(element, "HasAssociations"):
                for rel in element.HasAssociations:
                    if rel.is_a("IfcRelAssociatesMaterial"):
                        material = rel.RelatingMaterial
                        if material.is_a("IfcMaterial"):
                            # Здесь можно извлечь реальный цвет из материала
                            pass
        except:
            pass

        # Возвращаем цвет по умолчанию для этого типа
        for key in colors:
            if key in elem_type:
                return colors[key]

        return "lightgreen"  # Цвет для неизвестных типов

    def show_demo_geometry(self):
        """Отображение демо-геометрии без цикла событий"""
        self.log(
            "Отображение демонстрационной геометрии (так как IFC геометрия не загрузилась)"
        )
        self.plotter.clear()
        self.plotter.set_background("silver")

        # Создаем тестовую геометрию с подсказкой
        cube = pv.Cube()
        self.plotter.add_mesh(cube, color="lightblue", show_edges=True, opacity=0.7)

        # Добавляем пояснительный текст
        self.plotter.add_text(
            "DEMO MODE\nCould not extract geometry from IFC\nCheck that IFC contains 3D data\n\nPossible solutions:\n1. Export IFC with tessellated geometry\n2. Check IFC version (IFC2X3 or IFC4)\n3. Try different IFC file",
            position="upper_left",
            font_size=12,
            font="arial",
            color="red",
        )

        self.plotter.show()
        self.progress_bar.setVisible(False)

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

    def on_tree_item_clicked(self, item, column):
        """Обработка клика по элементу дерева с подсветкой в 3D"""
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if data:
            # Отображаем атрибуты
            self.attributes_table.setRowCount(0)

            if isinstance(data, dict):
                row = 0
                for key, value in data.items():
                    if key != "children":
                        self.attributes_table.insertRow(row)
                        self.attributes_table.setItem(
                            row, 0, QTableWidgetItem("Элемент")
                        )
                        self.attributes_table.setItem(
                            row, 1, QTableWidgetItem(str(key))
                        )
                        self.attributes_table.setItem(
                            row, 2, QTableWidgetItem(str(value))
                        )
                        row += 1

                # Получаем ID элемента
                element_id = data.get("global_id") or data.get("id")
                element_name = data.get("name", "Unknown")

                self.log(f"Выделен элемент: {element_name} (ID: {element_id})")

                # Снимаем предыдущую подсветку
                if hasattr(self, "highlighted_actor") and self.highlighted_actor:
                    try:
                        # Ищем сохраненный оригинальный цвет
                        for elem_id, elem_info in self.element_actors.items():
                            if elem_info["actor"] == self.highlighted_actor:
                                original_color = elem_info["color"]
                                self.highlighted_actor.GetProperty().SetColor(
                                    original_color
                                )
                                self.highlighted_actor.GetProperty().SetLineWidth(1)
                                break
                    except:
                        pass

                # Подсвечиваем новый элемент
                if (
                    hasattr(self, "element_actors")
                    and str(element_id) in self.element_actors
                ):
                    actor_info = self.element_actors[str(element_id)]
                    actor = actor_info["actor"]

                    # Подсвечиваем красным цветом
                    actor.GetProperty().SetColor(
                        1.0, 0.0, 0.0
                    )  # Красный цвет подсветки
                    actor.GetProperty().SetLineWidth(3)
                    actor.GetProperty().SetEdgeVisibility(True)

                    self.highlighted_actor = actor

                    # Фокусируем камеру на элементе
                    try:
                        bounds = actor.GetBounds()
                        if bounds and len(bounds) == 6:
                            center_x = (bounds[0] + bounds[1]) / 2
                            center_y = (bounds[2] + bounds[3]) / 2
                            center_z = (bounds[4] + bounds[5]) / 2

                            # Устанавливаем камеру на элемент
                            self.plotter.camera_position = [
                                (center_x, center_y, center_z + 10),
                                (center_x, center_y, center_z),
                                (0, 0, 1),
                            ]
                            self.plotter.reset_camera()
                            self.plotter.render()

                            self.log(f"Камера сфокусирована на элементе {element_name}")
                    except Exception as e:
                        self.log(f"Ошибка фокусировки камеры: {str(e)}")
                else:
                    self.log(
                        f"3D модель для элемента {element_name} не найдена в сцене"
                    )

    def show_message(self, button_name):
        """Показ сообщения о нажатии кнопки"""
        self.log(f"Нажата кнопка: {button_name}")

    def log(self, message):
        """Вывод сообщения в лог"""
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        # Автопрокрутка вниз
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)


def main():
    app = QApplication(sys.argv)

    # Устанавливаем глобальные стили
    app.setStyle("Fusion")

    viewer = IFCViewer()
    viewer.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
