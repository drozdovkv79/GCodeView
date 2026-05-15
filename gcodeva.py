#!/usr/bin/env python3
"""
GCode View and Analytics
Приложение для просмотра и анализа GCode файлов
Python 3.13, PyQt6, PyVista для macOS
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pyvista as pv
import vtk
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor
from scipy import interpolate


class GCodeAnalyzer:
    """Класс для анализа GCode файлов"""

    def __init__(self):
        self.points = []
        self.layers = defaultdict(list)
        self.current_layer = 0
        self.feed_rate = 0
        self.extruder_pos = 0
        self.absolute_extruder = False
        self.extrusion_points = []  # Точки с экструзией (G1)
        self.travel_points = []  # Точки перемещения (G0)

    def parse_file_from_lines(self, lines, progress_callback=None):
        """Парсинг GCode из списка строк с прогрессом по проценту"""
        # Используем списки Python только на время парсинга
        points_list = []
        extrusion_list = []
        travel_list = []
        layers_dict = defaultdict(list)

        self.current_layer = 0

        x, y, z = np.float32(0.0), np.float32(0.0), np.float32(0.0)
        e = np.float32(0.0)
        last_z = np.float32(0.0)
        point_index = 0
        layer_threshold = np.float32(1.0)

        total_lines = len(lines)
        last_progress_pct = 20

        for line_num, line in enumerate(lines):
            line = line.strip()

            if not line or line.startswith(";"):
                continue

            if "M82" in line:
                self.absolute_extruder = True
                continue
            elif "M83" in line:
                self.absolute_extruder = False
                continue

            if line.startswith(("G0 ", "G1 ", "G0\t", "G1\t")):
                x_match = re.search(r"X([-\d.]+)", line)
                y_match = re.search(r"Y([-\d.]+)", line)
                z_match = re.search(r"Z([-\d.]+)", line)
                e_match = re.search(r"E([-\d.]+)", line)
                f_match = re.search(r"F([-\d.]+)", line)

                if x_match:
                    x = np.float32(x_match.group(1))
                if y_match:
                    y = np.float32(y_match.group(1))
                if z_match:
                    z = np.float32(z_match.group(1))
                    if abs(z - last_z) > layer_threshold:
                        self.current_layer += 1
                        last_z = z
                if e_match:
                    e = np.float32(e_match.group(1))
                if f_match:
                    self.feed_rate = np.float32(f_match.group(1))

                is_g1 = line.startswith(("G1 ", "G1\t"))
                has_extrusion = e_match is not None and is_g1 and e > 0

                # Храним как numpy массив для экономии памяти
                point = np.array(
                    [
                        x,
                        y,
                        z,
                        e,
                        self.feed_rate,
                        self.current_layer,
                        is_g1 and has_extrusion,
                        point_index,
                    ],
                    dtype=np.float32,
                )

                points_list.append(point)

                if has_extrusion:
                    extrusion_list.append(point)
                else:
                    travel_list.append(point)

                layers_dict[self.current_layer].append(point)
                point_index += 1

            # Обновление прогресса
            if progress_callback and total_lines > 0:
                current_pct = 20 + int(50 * (line_num + 1) / total_lines)
                if current_pct != last_progress_pct:
                    progress_callback(current_pct)
                    last_progress_pct = current_pct

        if progress_callback:
            progress_callback(70)

        # Конвертируем в numpy массивы float32
        self.points = (
            np.array(points_list, dtype=np.float32)
            if points_list
            else np.empty((0, 8), dtype=np.float32)
        )
        self.extrusion_points = (
            np.array(extrusion_list, dtype=np.float32)
            if extrusion_list
            else np.empty((0, 8), dtype=np.float32)
        )
        self.travel_points = (
            np.array(travel_list, dtype=np.float32)
            if travel_list
            else np.empty((0, 8), dtype=np.float32)
        )

        # Конвертируем слои
        self.layers = {}
        for layer_num, layer_points in layers_dict.items():
            self.layers[layer_num] = np.array(layer_points, dtype=np.float32)

        return self.points

    def parse_file(self, filepath):
        """Парсинг GCode файла"""
        self.points = []
        self.layers = defaultdict(list)
        self.extrusion_points = []
        self.travel_points = []
        self.current_layer = 0

        x, y, z = 0.0, 0.0, 0.0
        e = 0.0
        last_z = 0.0
        point_index = 0
        layer_threshold = 1.0  # Порог смены слоя по Z в мм

        with open(filepath, "r") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()

            # Пропускаем комментарии и пустые строки
            if not line or line.startswith(";"):
                continue

            # Установка режима экструдера
            if "M82" in line:
                self.absolute_extruder = True
                continue
            elif "M83" in line:
                self.absolute_extruder = False
                continue

            # Обработка G0 и G1 команд
            if line.startswith(("G0 ", "G1 ", "G0\t", "G1\t")):
                # Извлечение координат
                x_match = re.search(r"X([-\d.]+)", line)
                y_match = re.search(r"Y([-\d.]+)", line)
                z_match = re.search(r"Z([-\d.]+)", line)
                e_match = re.search(r"E([-\d.]+)", line)
                f_match = re.search(r"F([-\d.]+)", line)

                if x_match:
                    x = float(x_match.group(1))
                if y_match:
                    y = float(y_match.group(1))
                if z_match:
                    z = float(z_match.group(1))
                if e_match:
                    e = float(e_match.group(1))
                if f_match:
                    self.feed_rate = float(f_match.group(1))

                # Определение смены слоя по изменению Z
                if z_match and abs(z - last_z) > layer_threshold:
                    self.current_layer += 1
                    last_z = z

                is_g1 = line.startswith(("G1 ", "G1\t"))
                has_extrusion = e_match is not None and is_g1 and e > 0

                point = {
                    "x": x,
                    "y": y,
                    "z": z,
                    "e": e,
                    "feed_rate": self.feed_rate,
                    "layer": self.current_layer,
                    "is_extrusion": is_g1 and has_extrusion,
                    "index": point_index,
                }

                self.points.append(point)

                if point["is_extrusion"]:
                    self.extrusion_points.append(point)
                else:
                    self.travel_points.append(point)

                self.layers[self.current_layer].append(point)
                point_index += 1

        return self.points

    def get_statistics(self):
        """Получение статистики по файлу (оптимизированная для float32)"""
        if len(self.points) == 0:
            return None

        stats = {}
        ext_pts = self.extrusion_points

        stats["total_points"] = len(self.points)
        stats["extrusion_points"] = len(ext_pts)
        stats["travel_points"] = len(self.travel_points)

        if len(ext_pts) == 0:
            return stats

        # Извлекаем координаты как float32
        xs = ext_pts[:, 0].astype(np.float32)
        ys = ext_pts[:, 1].astype(np.float32)
        zs = ext_pts[:, 2].astype(np.float32)

        # Размеры модели
        stats["width"] = float(xs.max() - xs.min())
        stats["length"] = float(ys.max() - ys.min())
        stats["height"] = float(zs.max() - zs.min())

        # Расстояния между точками
        if len(xs) > 1:
            x_diffs = np.abs(np.diff(xs))
            x_diffs = x_diffs[x_diffs > 0]
            if len(x_diffs) > 0:
                stats["min_distance_x"] = float(x_diffs.min())
                stats["max_distance_x"] = float(x_diffs.max())
            else:
                stats["min_distance_x"] = stats["max_distance_x"] = 0.0

            y_diffs = np.abs(np.diff(ys))
            y_diffs = y_diffs[y_diffs > 0]
            if len(y_diffs) > 0:
                stats["min_distance_y"] = float(y_diffs.min())
                stats["max_distance_y"] = float(y_diffs.max())
            else:
                stats["min_distance_y"] = stats["max_distance_y"] = 0.0

            z_diffs = np.abs(np.diff(zs))
            z_diffs = z_diffs[z_diffs > 0]
            if len(z_diffs) > 0:
                stats["min_distance_z"] = float(z_diffs.min())
                stats["max_distance_z"] = float(z_diffs.max())
            else:
                stats["min_distance_z"] = stats["max_distance_z"] = 0.0
        else:
            stats["min_distance_x"] = stats["max_distance_x"] = 0.0
            stats["min_distance_y"] = stats["max_distance_y"] = 0.0
            stats["min_distance_z"] = stats["max_distance_z"] = 0.0

        # Количество слоёв
        layers_with_extrusion = [
            l for l in self.layers if np.any(self.layers[l][:, 6] > 0)
        ]
        stats["num_layers"] = len(layers_with_extrusion)

        # Точки на слое
        points_per_layer = [
            np.sum(self.layers[l][:, 6] > 0) for l in layers_with_extrusion
        ]
        if points_per_layer:
            stats["min_points_per_layer"] = int(min(points_per_layer))
            stats["max_points_per_layer"] = int(max(points_per_layer))
            stats["avg_points_per_layer"] = float(np.mean(points_per_layer))
        else:
            stats["min_points_per_layer"] = stats["max_points_per_layer"] = stats[
                "avg_points_per_layer"
            ] = 0

        # Количество материала
        e_values = ext_pts[ext_pts[:, 3] > 0][:, 3].astype(np.float32)
        total_e = float(e_values.sum()) if len(e_values) > 0 else 0.0
        stats["total_material"] = total_e

        # Материал по слоям
        material_per_layer = []
        for l in layers_with_extrusion:
            l_e = float(
                np.sum(
                    self.layers[l][
                        (self.layers[l][:, 6] > 0) & (self.layers[l][:, 3] > 0)
                    ][:, 3]
                )
            )
            material_per_layer.append(l_e)

        if material_per_layer:
            stats["min_material_per_layer"] = float(min(material_per_layer))
            stats["max_material_per_layer"] = float(max(material_per_layer))
            stats["avg_material_per_layer"] = float(np.mean(material_per_layer))
        else:
            stats["min_material_per_layer"] = stats["max_material_per_layer"] = stats[
                "avg_material_per_layer"
            ] = 0.0

        # Материал на точку
        if len(e_values) > 0:
            stats["min_material_per_point"] = float(e_values.min())
            stats["max_material_per_point"] = float(e_values.max())
        else:
            stats["min_material_per_point"] = stats["max_material_per_point"] = 0.0

        # Объём
        filament_diameter = np.float32(1.75)
        filament_area = np.pi * (filament_diameter / 2) ** 2
        stats["volume"] = float(total_e * filament_area)

        # Экстремумы
        stats["extremes"] = self._find_extremes_fast(xs, ys, zs, ext_pts)

        return stats

    def _find_extremes_fast(self, xs, ys, zs, ext_pts):
        """Быстрый поиск экстремумов с float32"""
        extremes = {}
        if len(ext_pts) == 0:
            return extremes

        max_z_idx = np.argmax(zs)
        extremes["max_z"] = {
            "x": float(ext_pts[max_z_idx, 0]),
            "y": float(ext_pts[max_z_idx, 1]),
            "z": float(ext_pts[max_z_idx, 2]),
        }

        speeds = ext_pts[:, 4].astype(np.float32)
        max_speed_idx = np.argmax(speeds)
        extremes["max_speed"] = {"feed_rate": float(ext_pts[max_speed_idx, 4])}

        e_vals = ext_pts[:, 3].astype(np.float32)
        max_e_idx = np.argmax(e_vals)
        extremes["max_extrusion"] = {"e": float(ext_pts[max_e_idx, 3])}

        extremes["num_sharp_corners"] = 0

        return extremes

    def _find_extremes(self):
        """Поиск экстремумов и проблемных зон"""
        extremes = {
            "max_z": None,
            "max_speed": None,
            "max_extrusion": None,
            "sharp_corners": [],
        }

        if not self.extrusion_points:
            return extremes

        # Максимальная высота
        max_z = max(self.extrusion_points, key=lambda p: p["z"])
        extremes["max_z"] = max_z

        # Максимальная скорость
        max_speed = max(self.extrusion_points, key=lambda p: p["feed_rate"])
        extremes["max_speed"] = max_speed

        # Максимальная экструзия
        max_extr = max(self.extrusion_points, key=lambda p: p["e"])
        extremes["max_extrusion"] = max_extr

        # Поиск острых углов (изменение направления > 120 градусов)
        for i in range(1, len(self.extrusion_points) - 1):
            p1 = self.extrusion_points[i - 1]
            p2 = self.extrusion_points[i]
            p3 = self.extrusion_points[i + 1]

            # Проверка только в пределах одного слоя
            if p1["layer"] == p2["layer"] == p3["layer"]:
                v1 = np.array([p2["x"] - p1["x"], p2["y"] - p1["y"]])
                v2 = np.array([p3["x"] - p2["x"], p3["y"] - p2["y"]])

                norm1 = np.linalg.norm(v1)
                norm2 = np.linalg.norm(v2)

                if norm1 > 0 and norm2 > 0:
                    cos_angle = np.dot(v1, v2) / (norm1 * norm2)
                    angle = np.arccos(np.clip(cos_angle, -1, 1))
                    angle_deg = np.degrees(angle)

                    if angle_deg > 120:
                        extremes["sharp_corners"].append(
                            {"point": p2, "angle": angle_deg}
                        )

        extremes["num_sharp_corners"] = len(extremes["sharp_corners"])
        return extremes


class GCodeLoader(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(object, object)
    error = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            analyzer = GCodeAnalyzer()
            self.progress.emit(10)

            # Читаем все строки
            with open(self.filepath, "r") as f:
                lines = f.readlines()
            self.progress.emit(20)

            # Парсим с прогрессом: в callback передаётся процент (20..70)
            points = analyzer.parse_file_from_lines(
                lines, progress_callback=self.progress.emit
            )
            self.progress.emit(70)

            stats = analyzer.get_statistics()
            self.progress.emit(100)
            self.finished.emit(points, stats)

        except Exception as e:
            self.error.emit(str(e))


class VisualizationWorker(QThread):
    """Поток для создания визуализации"""

    progress = pyqtSignal(int)
    message = pyqtSignal(str)  # Новый сигнал для сообщений в лог
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, extrusion_points, color_scheme, tube_diameter=0.4):
        super().__init__()
        self.extrusion_points = extrusion_points
        self.color_scheme = color_scheme
        self.tube_diameter = tube_diameter

    def uniform_sampling(self, points, max_points=1000):
        """Оставляет не более max_points точек с равномерным шагом"""
        if len(points) <= max_points:
            return points

        step = len(points) // max_points
        filtered_points = points[::step]

        # Всегда добавляем последнюю точку
        # if filtered_points[-1] != points[-1]:
        #    filtered_points = np.vstack([filtered_points, points[-1]])

        return filtered_points

    def remove_collinear_points(self, points, angle_threshold_deg=175):
        """
        Удаление коллинеарных точек по углу между векторами
        angle_threshold_deg: порог угла в градусах (175 = почти прямая линия)
        """
        # Конвертируем в numpy массив
        points = np.asarray(points, dtype=np.float32)

        if len(points) <= 2:
            return points

        # Нормализуем размерность до 3D
        if points.shape[1] == 2:
            points = np.column_stack([points, np.zeros(len(points))])
        elif points.shape[1] == 1:
            points = np.column_stack([points, np.zeros((len(points), 2))])

        # Начинаем с первой точки
        filtered = [points[0]]

        for i in range(1, len(points) - 1):
            # Получаем три последовательные точки
            p_prev = filtered[-1]  # Последняя сохраненная точка
            p_curr = points[i]  # Текущая точка
            p_next = points[i + 1]  # Следующая точка

            # Векторы
            v1 = p_curr - p_prev
            v2 = p_next - p_curr

            # Нормы векторов
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)

            if norm1 < 1e-10 or norm2 < 1e-10:
                # Точки совпадают, пропускаем текущую
                continue

            # Нормализуем
            v1 = v1 / norm1
            v2 = v2 / norm2

            # Вычисляем угол между векторами
            dot = np.clip(np.dot(v1, v2), -1, 1)
            angle = np.degrees(np.arccos(dot))

            # Если угол меньше порога (не коллинеарны), сохраняем точку
            if angle > angle_threshold_deg:
                filtered.append(p_curr)

        # Добавляем последнюю точку
        filtered.append(points[-1])

        return np.array(filtered, dtype=np.float32)

    def run(self):
        try:
            import vtk

            self.progress.emit(10)

            if len(self.extrusion_points) == 0:
                self.error.emit("Нет точек для визуализации")
                return

            # Группировка точек по слоям
            layers = defaultdict(list)
            for point in self.extrusion_points:
                layer_num = int(point[5])  # Индекс слоя в структуре
                layers[layer_num].append(point)

            self.progress.emit(30)

            all_meshes = []
            tube_radius = self.tube_diameter / np.float32(2.0)

            total_layers = len(layers)
            for idx, (layer_num, layer_points) in enumerate(sorted(layers.items())):
                if len(layer_points) < 2:
                    continue

                max_points = int(len(layer_points) / 2)
                # Использование
                layer_points1 = self.remove_collinear_points(
                    layer_points, angle_threshold_deg=5
                )

                # layer_points1 = self.uniform_sampling(
                #    layer_points, max_points=max_points
                # )
                self.message.emit(
                    f"Слой {layer_num}: точек {len(layer_points1)} ,было {max_points * 2}"
                )

                # Конвертируем в numpy массив координат float32
                points_array = np.array(
                    [[p[0], p[1], p[2]] for p in layer_points1], dtype=np.float32
                )

                # Создаем PolyData для слоя
                spl = pv.PolyData(points_array)
                n_pts = len(points_array)

                # Создаем непрерывную линию
                lines = np.hstack([[n_pts], np.arange(n_pts)]).astype(np.int32)
                spl.lines = lines

                # vtkTubeFilter для непрерывной трубы
                tube_filter = vtk.vtkTubeFilter()
                tube_filter.SetInputData(spl)
                tube_filter.SetRadius(float(tube_radius))
                tube_filter.SetNumberOfSides(8)
                tube_filter.SetCapping(1)
                tube_filter.Update()

                tube = tube_filter.GetOutput()
                all_meshes.append(tube)

                progress = 30 + int(60 * (idx + 1) / total_layers)
                self.progress.emit(progress)

            self.progress.emit(90)

            if not all_meshes:
                self.error.emit("Не удалось создать визуализацию")
                return

            # Быстрое объединение через vtkAppendPolyData
            append_filter = vtk.vtkAppendPolyData()
            for mesh in all_meshes:
                append_filter.AddInputData(mesh)
            append_filter.Update()

            combined = pv.wrap(append_filter.GetOutput())

            self.progress.emit(100)
            self.finished.emit(combined)

        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GCode View and Analytics")
        self.setGeometry(100, 100, 1600, 900)

        # Установка шрифта
        self.font = QFont("Arial", 12)
        self.setFont(self.font)

        # Переменные
        self.current_directory = None
        self.current_gcode_file = None
        self.extrusion_points = []
        self.current_mesh = None
        self.color_scheme = "Матовый"
        self.plotter = None

        # Цветовые схемы
        self.color_schemes = {
            "Матовый": "#e9e5ce",  # e9e5ce
            "Пластик": "#4A90E2",
            "Гипс": "#FFFFFF",
            "Сталь": "#808080",
            "Стекло": "#87CEEB",
        }

        # Инициализация UI
        self.init_ui()

    def init_ui(self):
        """Инициализация интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Главный layout
        main_layout = QHBoxLayout(central_widget)

        # Создание разделителя
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель с элементами управления
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)

        # Центральная панель с 3D визуализацией
        center_panel = self.create_center_panel()
        splitter.addWidget(center_panel)

        # Правая панель с вкладками
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)

        # Установка размеров
        splitter.setSizes([250, 800, 450])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        main_layout.addWidget(splitter)

    def create_left_panel(self):
        """Создание левой панели управления"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Выбор директории
        dir_group = QGroupBox("Директория")
        dir_layout = QVBoxLayout()

        self.btn_select_dir = QPushButton("Выбрать директорию")
        self.btn_select_dir.clicked.connect(self.select_directory)
        dir_layout.addWidget(self.btn_select_dir)

        self.dir_label = QLabel("Директория не выбрана")
        self.dir_label.setWordWrap(True)
        dir_layout.addWidget(self.dir_label)

        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # Список файлов
        files_group = QGroupBox("Файлы GCode")
        files_layout = QVBoxLayout()

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.on_file_selected)
        files_layout.addWidget(self.file_list)

        files_group.setLayout(files_layout)
        layout.addWidget(files_group)

        # Прогресс бар
        progress_group = QGroupBox("Прогресс")
        progress_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Готов")
        progress_layout.addWidget(self.progress_label)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # Кнопки действий
        actions_group = QGroupBox("Действия")
        actions_layout = QVBoxLayout()

        self.btn_analyze = QPushButton("Анализировать")
        self.btn_analyze.clicked.connect(self.analyze_gcode)
        self.btn_analyze.setEnabled(False)
        actions_layout.addWidget(self.btn_analyze)

        self.btn_visualize = QPushButton("Визуализировать")
        self.btn_visualize.clicked.connect(self.visualize_gcode)
        self.btn_visualize.setEnabled(False)
        actions_layout.addWidget(self.btn_visualize)

        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        # Кнопки видов
        views_group = QGroupBox("Виды")
        views_layout = QVBoxLayout()

        # Ортогональные виды
        ortho_views = [
            ("Верх", self.view_top),
            ("Низ", self.view_bottom),
            ("Перед", self.view_front),
            ("Зад", self.view_back),
            ("Лево", self.view_left),
            ("Право", self.view_right),
        ]

        for view_name, handler in ortho_views:
            btn = QPushButton(view_name)
            btn.clicked.connect(handler)
            btn.setEnabled(False)
            views_layout.addWidget(btn)
            if not hasattr(self, "view_buttons"):
                self.view_buttons = []
            self.view_buttons.append(btn)

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        views_layout.addWidget(separator)

        # Изометрические виды
        iso_views = [
            ("ISO 1", lambda: self.view_iso(0)),
            ("ISO 2", lambda: self.view_iso(1)),
            ("ISO 3", lambda: self.view_iso(2)),
            ("ISO 4", lambda: self.view_iso(3)),
        ]

        for view_name, handler in iso_views:
            btn = QPushButton(view_name)
            btn.clicked.connect(handler)
            btn.setEnabled(False)
            views_layout.addWidget(btn)
            self.view_buttons.append(btn)

        views_group.setLayout(views_layout)
        layout.addWidget(views_group)

        # Кнопки экспорта
        export_group = QGroupBox("Экспорт")
        export_layout = QVBoxLayout()

        self.btn_photo = QPushButton("Фото")
        self.btn_photo.clicked.connect(self.take_photos)
        self.btn_photo.setEnabled(False)
        export_layout.addWidget(self.btn_photo)

        self.btn_video = QPushButton("Видео")
        self.btn_video.clicked.connect(self.create_video)
        self.btn_video.setEnabled(False)
        export_layout.addWidget(self.btn_video)

        self.btn_export = QPushButton("Экспорт модели")
        self.btn_export.clicked.connect(self.export_model)
        self.btn_export.setEnabled(False)
        export_layout.addWidget(self.btn_export)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        layout.addStretch()

        return panel

    def create_center_panel(self):
        """Создание центральной панели с 3D визуализацией"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Создание frame для 3D view
        self.viz_frame = QFrame()
        self.viz_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        viz_layout = QVBoxLayout(self.viz_frame)
        viz_layout.setContentsMargins(0, 0, 0, 0)

        # PyVista plotter будет создан при инициализации
        self.viz_widget = QLabel("3D визуализация\n(загрузите и визуализируйте файл)")
        self.viz_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viz_widget.setStyleSheet("background-color: #505050;")
        viz_layout.addWidget(self.viz_widget)

        layout.addWidget(self.viz_frame)

        return panel

    def create_right_panel(self):
        """Создание правой панели с вкладками"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Создание вкладок
        self.tab_widget = QTabWidget()

        # Вкладка Аналитика
        self.analytics_text = QTextEdit()
        self.analytics_text.setReadOnly(True)
        self.analytics_text.setFont(QFont("Arial", 12))
        self.tab_widget.addTab(self.analytics_text, "Аналитика")

        # Вкладка Параметры
        self.settings_tab = self.create_settings_tab()
        self.tab_widget.addTab(self.settings_tab, "Параметры")

        # Вкладка Лог
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Arial", 10))
        self.tab_widget.addTab(self.log_text, "Лог")

        layout.addWidget(self.tab_widget)

        return panel

    def create_settings_tab(self):
        """Создание вкладки параметров"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Группа выбора цвета
        color_group = QGroupBox("Цвет материала")
        color_layout = QVBoxLayout()

        self.color_buttons = QButtonGroup()

        colors = ["Матовый", "Пластик", "Гипс", "Сталь", "Стекло"]
        for i, color_name in enumerate(colors):
            rb = QRadioButton(color_name)
            if i == 0:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, c=color_name: self.on_color_changed(c))
            self.color_buttons.addButton(rb)
            color_layout.addWidget(rb)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Группа параметров визуализации
        viz_group = QGroupBox("Параметры визуализации")
        viz_layout = QVBoxLayout()

        # Группа выбора цвета модели
        model_color_group = QGroupBox("Цвет модели")
        model_color_layout = QVBoxLayout()

        # Кнопка выбора цвета
        self.btn_choose_color = QPushButton("Выбрать цвет модели")
        self.btn_choose_color.clicked.connect(self.choose_model_color)
        model_color_layout.addWidget(self.btn_choose_color)

        # Превью выбранного цвета
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(60, 30)
        self.color_preview.setStyleSheet(
            "background-color: #e9e5ce; border: 1px solid #999;"
        )
        model_color_layout.addWidget(self.color_preview)

        # Текущий цвет в тексте
        self.color_value_label = QLabel("#e9e5ce")
        model_color_layout.addWidget(self.color_value_label)

        # Кнопка сброса на цвет по умолчанию
        self.btn_reset_color = QPushButton("Сбросить цвет")
        self.btn_reset_color.clicked.connect(self.reset_model_color)
        model_color_layout.addWidget(self.btn_reset_color)

        model_color_group.setLayout(model_color_layout)
        layout.addWidget(model_color_group)

        # Диаметр трубы
        tube_layout = QHBoxLayout()
        tube_label = QLabel("Диаметр трубы (мм):")
        self.tube_diameter_spinbox = QDoubleSpinBox()
        self.tube_diameter_spinbox.setRange(1, 10.0)
        self.tube_diameter_spinbox.setValue(4)  # Значение по умолчанию
        self.tube_diameter_spinbox.setSingleStep(0.5)
        self.tube_diameter_spinbox.setDecimals(1)
        self.tube_diameter_spinbox.setSuffix(" мм")
        tube_layout.addWidget(tube_label)
        tube_layout.addWidget(self.tube_diameter_spinbox)
        viz_layout.addLayout(tube_layout)

        # Кнопка обновления
        self.btn_update_viz = QPushButton("Обновить визуализацию")
        self.btn_update_viz.clicked.connect(self.update_visualization)
        self.btn_update_viz.setEnabled(False)
        viz_layout.addWidget(self.btn_update_viz)

        viz_group.setLayout(viz_layout)
        layout.addWidget(viz_group)

        layout.addStretch()

        return widget

    def log_message(self, message):
        """Добавление сообщения в лог"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def select_directory(self):
        """Выбор директории с GCode файлами"""
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите директорию с GCode файлами"
        )

        if directory:
            self.current_directory = directory
            self.dir_label.setText(directory)
            self.load_gcode_files()
            self.log_message(f"Выбрана директория: {directory}")

    def load_gcode_files(self):
        """Загрузка списка GCode файлов"""
        if not self.current_directory:
            return

        self.file_list.clear()

        gcode_files = list(Path(self.current_directory).glob("*.gcode"))
        gcode_files.extend(Path(self.current_directory).glob("*.GCODE"))
        gcode_files.extend(Path(self.current_directory).glob("*.nc"))
        gcode_files.extend(Path(self.current_directory).glob("*.NGC"))

        for file_path in gcode_files:
            self.file_list.addItem(file_path.name)

        self.log_message(f"Найдено {len(gcode_files)} GCode файлов")

    def on_file_selected(self, item):
        """Обработчик выбора файла"""
        self.current_gcode_file = Path(self.current_directory) / item.text()
        self.btn_analyze.setEnabled(True)
        self.btn_visualize.setEnabled(True)
        self.log_message(f"Выбран файл: {item.text()}")

    def analyze_gcode(self):
        """Анализ выбранного GCode файла"""
        if not self.current_gcode_file:
            QMessageBox.warning(self, "Предупреждение", "Выберите файл для анализа")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Анализ файла...")

        self.log_message(f"Начало анализа файла: {self.current_gcode_file.name}")

        # Запуск анализа в отдельном потоке
        self.loader = GCodeLoader(str(self.current_gcode_file))
        self.loader.progress.connect(self.progress_bar.setValue)
        self.loader.finished.connect(self.on_analysis_finished)
        self.loader.error.connect(self.on_analysis_error)
        self.loader.start()

    def on_analysis_finished(self, points, stats):
        """Обработчик завершения анализа"""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Анализ завершен")

        # Сохранение точек экструзии для визуализации
        # Теперь points - это numpy массив, где колонка 6 содержит признак экструзии
        if len(points) > 0:
            # Фильтруем точки с экструзией (колонка 6 > 0)
            self.extrusion_points = points[points[:, 6] > 0]
        else:
            self.extrusion_points = np.empty((0, 8), dtype=np.float32)

        # Отображение статистики
        self.display_statistics(stats)
        self.log_message("Анализ успешно завершен")

        self.btn_photo.setEnabled(True)
        self.btn_video.setEnabled(True)
        self.btn_export.setEnabled(True)

    def on_analysis_error(self, error_msg):
        """Обработчик ошибки анализа"""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Ошибка анализа")
        QMessageBox.critical(self, "Ошибка", f"Ошибка при анализе файла: {error_msg}")
        self.log_message(f"Ошибка анализа: {error_msg}")

    def display_statistics(self, stats):
        """Отображение статистики"""
        if not stats:
            self.analytics_text.setText("Нет данных для анализа")
            return

        file_size = os.path.getsize(str(self.current_gcode_file))

        text = f"""=== АНАЛИЗ GCODE ФАЙЛА ===

1. Размер файла: {file_size:,} байт ({file_size / (1024 * 1024):.2f} МБ)

2. Количество точек:
   - Всего: {stats.get("total_points", 0):,}
   - С экструзией: {stats.get("extrusion_points", 0):,}
   - Перемещений: {stats.get("travel_points", 0):,}

3. Размеры модели:
   - Ширина (X): {stats.get("width", 0):.2f} мм
   - Длина (Y): {stats.get("length", 0):.2f} мм
   - Высота (Z): {stats.get("height", 0):.2f} мм

4. Расстояния между точками:
   - По X: мин {stats.get("min_distance_x", 0):.4f} мм, макс {stats.get("max_distance_x", 0):.4f} мм
   - По Y: мин {stats.get("min_distance_y", 0):.4f} мм, макс {stats.get("max_distance_y", 0):.4f} мм
   - По Z: мин {stats.get("min_distance_z", 0):.4f} мм, макс {stats.get("max_distance_z", 0):.4f} мм

5. Количество слоев: {stats.get("num_layers", 0)}

6. Точки на слое:
   - Минимум: {stats.get("min_points_per_layer", 0):,}
   - Максимум: {stats.get("max_points_per_layer", 0):,}
   - Среднее: {stats.get("avg_points_per_layer", 0):.1f}

7. Количество материала:
   - Всего: {stats.get("total_material", 0):.2f} мм
   - На слой: мин {stats.get("min_material_per_layer", 0):.4f} мм, макс {stats.get("max_material_per_layer", 0):.4f} мм
   - На точку: мин {stats.get("min_material_per_point", 0):.6f} мм, макс {stats.get("max_material_per_point", 0):.6f} мм

8. Объем материала: {stats.get("volume", 0):.2f} мм³ ({stats.get("volume", 0) / 1000:.2f} см³)

9. Анализ экстремумов и проблемных зон:
"""

        extremes = stats.get("extremes", {})
        if extremes:
            if extremes.get("max_z"):
                text += f"   - Максимальная высота: Z={extremes['max_z']['z']:.2f} мм\n"
            if extremes.get("max_speed"):
                text += f"   - Максимальная скорость: F={extremes['max_speed']['feed_rate']:.0f} мм/мин\n"
            if extremes.get("max_extrusion"):
                text += f"   - Максимальная экструзия: E={extremes['max_extrusion']['e']:.4f} мм\n"
            text += f"   - Количество острых углов (>120°): {extremes.get('num_sharp_corners', 0)}\n"

        self.analytics_text.setText(text)

    def visualize_gcode(self):
        """Визуализация GCode"""
        if not self.current_gcode_file:
            QMessageBox.warning(
                self, "Предупреждение", "Выберите файл для визуализации"
            )
            return

        if len(self.extrusion_points) == 0:
            # Сначала анализируем
            self.analyze_gcode()
            QMessageBox.information(
                self,
                "Информация",
                "Сначала выполняется анализ файла. Нажмите 'Визуализировать' еще раз после завершения анализа.",
            )
            return

        tube_diameter = self.tube_diameter_spinbox.value()

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Построение визуализации...")

        self.log_message("Начало построения 3D модели")

        # Запуск визуализации в отдельном потоке
        self.viz_worker = VisualizationWorker(
            self.extrusion_points, self.color_schemes[self.color_scheme], tube_diameter
        )
        self.viz_worker.progress.connect(self.progress_bar.setValue)
        self.viz_worker.finished.connect(self.on_visualization_finished)
        self.viz_worker.message.connect(self.log_message)  # Подключаем сообщения в лог
        self.viz_worker.error.connect(self.on_visualization_error)
        self.viz_worker.start()

    def on_visualization_finished(self, mesh):
        """Обработчик завершения визуализации"""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Визуализация завершена")

        self.current_mesh = mesh

        # Создание plotter
        self.setup_3d_view(mesh)
        self.log_message("3D модель построена успешно")

        # Активация кнопок
        self.btn_photo.setEnabled(True)
        self.btn_video.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_update_viz.setEnabled(True)

        # Активация кнопок видов
        for btn in self.view_buttons:
            btn.setEnabled(True)

    def update_visualization(self):
        """Обновление визуализации с новыми параметрами"""
        if len(self.extrusion_points) == 0:
            QMessageBox.warning(
                self, "Предупреждение", "Сначала загрузите и проанализируйте файл"
            )
            return

        tube_diameter = self.tube_diameter_spinbox.value()

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Обновление визуализации...")

        self.log_message(
            f"Обновление визуализации с диаметром трубы: {tube_diameter} мм"
        )

        # Запуск визуализации с новым диаметром
        self.viz_worker = VisualizationWorker(
            self.extrusion_points, self.color_schemes[self.color_scheme], tube_diameter
        )
        self.viz_worker.progress.connect(self.progress_bar.setValue)
        self.viz_worker.finished.connect(self.on_visualization_finished)
        self.viz_worker.message.connect(self.log_message)  # Подключаем сообщения в лог
        self.viz_worker.error.connect(self.on_visualization_error)
        self.viz_worker.start()

    def on_visualization_error(self, error_msg):
        """Обработчик ошибки визуализации"""
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Ошибка визуализации")
        QMessageBox.critical(self, "Ошибка", f"Ошибка при визуализации: {error_msg}")
        self.log_message(f"Ошибка визуализации: {error_msg}")

    def take_photos(self):
        """Создание фотографий модели с разных ракурсов"""
        if not self.plotter or not self.current_mesh:
            QMessageBox.warning(self, "Предупреждение", "Сначала визуализируйте модель")
            return

        # Выбор директории для сохранения
        save_dir = QFileDialog.getExistingDirectory(
            self, "Выберите директорию для сохранения фото"
        )

        if not save_dir:
            return

        self.log_message("Создание фотографий...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Подготовка к созданию фото...")
        QApplication.processEvents()

        # Определяем виды камеры
        # Определяем виды камеры
        views = {
            "front": {
                "position": [(0, 0, 100), (0, 0, 0), (0, 1, 0)],
                "description": "Спереди",
            },
            "back": {
                "position": [(0, 0, -100), (0, 0, 0), (0, 1, 0)],
                "description": "Сзади",
            },
            "left": {
                "position": [(-100, 0, 0), (0, 0, 0), (0, 0, 1)],
                "description": "Слева",
            },
            "right": {
                "position": [(100, 0, 0), (0, 0, 0), (0, 0, 1)],
                "description": "Справа",
            },
            "top": {
                "position": [(0, 100, 0), (0, 0, 0), (0, 0, -1)],
                "description": "Сверху",
            },
            "bottom": {
                "position": [(0, -100, 0), (0, 0, 0), (0, 0, 1)],
                "description": "Снизу",
            },
            "iso_front_right": {
                "position": [(70, 50, 70), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия спереди справа",
            },
            "iso_front_left": {
                "position": [(-70, 50, 70), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия спереди слева",
            },
            "iso_back_right": {
                "position": [(70, 50, -70), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия сзади справа",
            },
            "iso_back_left": {
                "position": [(-70, 50, -70), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия сзади слева",
            },
            "iso_front_top": {
                "position": [(50, 70, 50), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия спереди сверху",
            },
            "iso_front_bottom": {
                "position": [(50, -30, 50), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия спереди снизу",
            },
            "iso_back_top": {
                "position": [(-50, 70, -50), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия сзади сверху",
            },
            "iso_back_bottom": {
                "position": [(-50, -30, -50), (0, 0, 0), (0, 0, 1)],
                "description": "Изометрия сзади снизу",
            },
        }

        try:
            # Сохраняем исходную позицию камеры
            original_position = self.plotter.camera_position
            original_zoom = self.plotter.camera.zoom

            total_photos = len(views)
            photos_created = []

            for idx, (view_name, view_data) in enumerate(views.items()):
                # Устанавливаем позицию камеры
                self.plotter.camera_position = view_data["position"]

                # Масштабируем чтобы модель была видна полностью
                self.plotter.reset_camera()
                self.plotter.camera.zoom(1.2)  # Небольшой отступ

                self.plotter.render()

                # Даем время на обновление рендера
                QApplication.processEvents()

                # Создаем имя файла
                filename = Path(save_dir) / f"gcode_{view_name}.png"

                # Сохраняем скриншот
                self.plotter.screenshot(str(filename), return_img=False)

                photos_created.append(filename.name)

                # Обновляем прогресс
                progress = int(100 * (idx + 1) / total_photos)
                self.progress_bar.setValue(progress)
                self.progress_label.setText(
                    f"Создание фото: {view_data['description']} ({idx + 1}/{total_photos})"
                )

                self.log_message(
                    f"Фото сохранено: {filename.name} ({view_data['description']})"
                )

                # Обновляем интерфейс
                QApplication.processEvents()

            # Восстанавливаем исходную позицию камеры и зум
            self.plotter.camera_position = original_position
            self.plotter.camera.zoom = original_zoom
            self.plotter.render()

            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Фотографии созданы успешно")

            # Показываем результат
            result_message = f"Создано {len(photos_created)} фотографий:\n\n"
            result_message += "\n".join([f"• {photo}" for photo in photos_created[:10]])
            if len(photos_created) > 10:
                result_message += f"\n... и еще {len(photos_created) - 10} фото"

            self.log_message(f"Все фото сохранены в: {save_dir}")

            QMessageBox.information(
                self,
                "Успех",
                f"Фотографии успешно созданы\n\n"
                f"Директория: {save_dir}\n"
                f"Количество: {len(photos_created)}\n\n"
                f"{result_message}",
            )

        except Exception as e:
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Ошибка создания фото")
            self.log_message(f"Ошибка создания фото: {str(e)}")
            QMessageBox.critical(
                self, "Ошибка", f"Ошибка при создании фотографий:\n\n{str(e)}"
            )
            import traceback

            self.log_message(traceback.format_exc())

    def setup_3d_view(self, mesh):
        """Настройка 3D визуализации (первичное построение)"""
        try:
            if self.plotter:
                self.plotter.close()

            layout = self.viz_frame.layout()
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            self.plotter = QtInteractor(self.viz_frame)
            layout.addWidget(self.plotter)

            # Фон
            self.plotter.set_background("#101010")

            # Центрирование модели
            bounds = mesh.bounds
            center_x = (bounds[0] + bounds[1]) / 2
            center_y = (bounds[2] + bounds[3]) / 2
            mesh.translate([-center_x, -center_y, -bounds[4]], inplace=True)

            # Сохраняем mesh
            self.current_mesh = mesh

            # Освещение (один раз)
            self.plotter.enable_shadows()
            self.plotter.add_light(
                pv.Light(
                    position=(1, 1, 1),
                    light_type="scenelight",
                    intensity=0.8,
                    color="white",
                )
            )
            self.plotter.add_light(
                pv.Light(
                    position=(-0.5, -0.5, -0.5),
                    light_type="scenelight",
                    intensity=0.3,
                    color="white",
                )
            )
            self.plotter.add_light(
                pv.Light(
                    position=(0, -1, 0),
                    light_type="scenelight",
                    intensity=0.4,
                    color="white",
                )
            )

            # Эффекты один раз
            self.plotter.enable_depth_peeling(number_of_peels=40, occlusion_ratio=0.0)
            # self.plotter.enable_anti_aliasing("ssaa")
            # self.plotter.enable_ssao(radius=0.5, bias=0.005, kernel_size=128)

            # Добавляем модель и сохраняем актор
            self.model_actor = self.plotter.add_mesh(
                mesh,
                name="gcode_model",
                color="#E8E0D0",  # начальный цвет
                smooth_shading=True,
                show_edges=False,
                specular=0.1,
                specular_power=1,
                diffuse=0.9,
                ambient=0.2,
                # roughness=0.8,
                # metallic=0.0,
                pbr=True,
                # split_sharp_edges=True,
            )

            # Камера
            self.plotter.view_isometric()
            self.plotter.camera.zoom(1.5)
            self.plotter.show_axes()
            self.plotter.show_grid(
                color="#999999",
                # opacity=0.2,
                show_xlabels=False,
                show_ylabels=False,
                show_zlabels=False,
            )

            self.plotter.reset_camera()
            self.plotter.render()

        except Exception as e:
            self.log_message(f"Ошибка настройки 3D view: {str(e)}")

    def apply_material(self, material_name):
        """Мгновенное применение материала через изменение свойств актора"""
        if not hasattr(self, "model_actor") or not self.model_actor:
            return

        materials = {
            "Матовый": {
                "color": "#e9e5ce",
                "specular": 0.05,
                "specular_power": 5,
                "diffuse": 0.9,
                "ambient": 0.2,
                "roughness": 0.8,
                "metallic": 0.0,
                "opacity": 1.0,
            },
            "Пластик": {
                "color": "#4A90E2",
                "specular": 0.3,
                "specular_power": 20,
                "diffuse": 0.7,
                "ambient": 0.15,
                "roughness": 0.3,
                "metallic": 0.0,
                "opacity": 1.0,
            },
            "Гипс": {
                "color": "#F5F5F0",
                "specular": 0.02,
                "specular_power": 2,
                "diffuse": 0.95,
                "ambient": 0.25,
                "roughness": 0.9,
                "metallic": 0.0,
                "opacity": 1.0,
            },
            "Сталь": {
                "color": "#A8A8A8",
                "specular": 0.6,
                "specular_power": 80,
                "diffuse": 0.4,
                "ambient": 0.1,
                "roughness": 0.1,
                "metallic": 0.8,
                "opacity": 1.0,
            },
            "Стекло": {
                "color": "#B0E0E6",
                "specular": 0.8,
                "specular_power": 100,
                "diffuse": 0.2,
                "ambient": 0.1,
                "roughness": 0.05,
                "metallic": 0.1,
                "opacity": 0.7,
            },
        }

        s = materials.get(material_name, materials["Матовый"])
        prop = self.model_actor.GetProperty()

        # Если пользователь выбрал кастомный цвет, используем его
        if (
            hasattr(self, "color_value_label")
            and self.color_value_label.text() != s["color"]
        ):
            qc = QColor(self.color_value_label.text())
        else:
            qc = QColor(s["color"])

        prop.SetColor(qc.redF(), qc.greenF(), qc.blueF())
        prop.SetSpecular(s["specular"])
        prop.SetSpecularPower(s["specular_power"])
        prop.SetDiffuse(s["diffuse"])
        prop.SetAmbient(s["ambient"])
        prop.SetOpacity(s["opacity"])

        if hasattr(prop, "SetRoughness"):
            prop.SetRoughness(s["roughness"])
        if hasattr(prop, "SetMetallic"):
            prop.SetMetallic(s["metallic"])

        self.plotter.render()

    def view_top(self):
        """Вид сверху"""
        if self.plotter:
            self.plotter.view_xy()
            self.plotter.camera.Zoom(0.9)  # Масштабирование на 90%
            self.plotter.render()

    def view_bottom(self):
        """Вид снизу"""
        if self.plotter:
            self.plotter.view_xy(negative=True)
            self.plotter.camera.Zoom(0.9)
            self.plotter.render()

    def view_front(self):
        """Вид спереди"""
        if self.plotter:
            self.plotter.view_yz()
            self.plotter.camera.Zoom(0.9)
            self.plotter.render()

    def view_back(self):
        """Вид сзади"""
        if self.plotter:
            self.plotter.view_yz(negative=True)
            self.plotter.camera.Zoom(0.9)
            self.plotter.render()

    def view_left(self):
        """Вид слева"""
        if self.plotter:
            self.plotter.view_xz(negative=True)
            self.plotter.camera.Zoom(0.9)
            self.plotter.render()

    def view_right(self):
        """Вид справа"""
        if self.plotter:
            self.plotter.view_xz()
            self.plotter.camera.Zoom(0.9)
            self.plotter.render()

    def view_iso(self, position):
        """Изометрический вид"""
        if self.plotter:
            # 4 разных изометрических позиции
            iso_positions = [
                [(1, 1, 1), (0, 0, 0), (0, 0, 1)],  # ISO 1
                [(-1, 1, 1), (0, 0, 0), (0, 0, 1)],  # ISO 2
                [(-1, -1, 1), (0, 0, 0), (0, 0, 1)],  # ISO 3
                [(1, -1, 1), (0, 0, 0), (0, 0, 1)],  # ISO 4
            ]

            self.plotter.camera_position = iso_positions[position]
            self.plotter.reset_camera()  # Сначала сбросить камеру
            self.plotter.camera.Zoom(0.9)  # Затем масштабировать
            self.plotter.render()

    def choose_model_color(self):
        """Открыть диалог выбора цвета модели"""
        if not self.plotter or not hasattr(self, "model_actor"):
            QMessageBox.warning(self, "Предупреждение", "Сначала визуализируйте модель")
            return

        # Открываем диалог выбора цвета
        color = QColorDialog.getColor()

        if color.isValid():
            # Обновляем превью и текст
            self.color_preview.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #999;"
            )
            self.color_value_label.setText(color.name())

            # Применяем цвет к модели
            prop = self.model_actor.GetProperty()
            prop.SetColor(color.redF(), color.greenF(), color.blueF())
            self.plotter.render()

            self.log_message(f"Цвет модели изменен на: {color.name()}")

    def reset_model_color(self):
        """Сброс цвета модели на цвет текущего материала"""
        if not self.plotter or not hasattr(self, "model_actor"):
            return

        # Получаем цвет текущего материала
        material_colors = {
            "Матовый": "#e9e5ce",
            "Пластик": "#4A90E2",
            "Гипс": "#F5F5F0",
            "Сталь": "#A8A8A8",
            "Стекло": "#B0E0E6",
        }

        default_color = material_colors.get(self.color_scheme, "#e9e5ce")
        qc = QColor(default_color)

        # Обновляем превью
        self.color_preview.setStyleSheet(
            f"background-color: {default_color}; border: 1px solid #999;"
        )
        self.color_value_label.setText(default_color)

        # Применяем цвет
        prop = self.model_actor.GetProperty()
        prop.SetColor(qc.redF(), qc.greenF(), qc.blueF())
        self.plotter.render()

        self.log_message(f"Цвет модели сброшен на: {default_color}")

    def on_panel_color_changed(self, color_code):
        """Обработчик изменения цвета панели"""
        if self.plotter:
            from PyQt6.QtGui import QColor

            qc = QColor(color_code)
            # Создаем более светлый оттенок для верха
            lighter = qc.lighter(120)
            self.plotter.set_background(qc.name(), top=lighter.name())
            self.plotter.render()
            self.log_message(f"Цвет панели изменен на: {color_code}")

    def on_color_changed(self, color_name):
        """Обработчик выбора цвета (радиокнопки)"""
        self.color_scheme = color_name
        self.log_message(f"Цвет изменен на: {color_name}")
        self.apply_material(color_name)

    def create_video(self):
        """Создание видео облета модели с плавным вращением"""
        if not self.plotter or not self.current_mesh:
            QMessageBox.warning(self, "Предупреждение", "Сначала визуализируйте модель")
            return

        # Выбор файла для сохранения
        save_file, _ = QFileDialog.getSaveFileName(
            self, "Сохранить видео", "", "MP4 files (*.mp4)"
        )

        if not save_file:
            return

        if not save_file.endswith(".mp4"):
            save_file += ".mp4"

        self.log_message("Создание видео...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Подготовка к созданию видео...")

        try:
            import shutil
            import tempfile

            import cv2

            # Настройка параметров видео
            fps = 60  # Увеличиваем FPS для плавности
            duration = 15  # Увеличиваем длительность для более медленного вращения
            total_frames = fps * duration

            # Сохраняем текущую позицию камеры
            original_position = self.plotter.camera_position

            # Устанавливаем камеру в изометрическую позицию
            self.plotter.view_isometric()
            self.plotter.render()

            # Создаем временную директорию для кадров
            temp_dir = tempfile.mkdtemp()
            frames = []

            # Плавное вращение вокруг вертикальной оси
            angle_per_frame = 360.0 / total_frames

            self.progress_label.setText("Создание кадров видео...")
            QApplication.processEvents()

            # Предварительный рендеринг для инициализации
            self.plotter.render()

            for frame in range(total_frames):
                # Плавно вращаем камеру
                self.plotter.camera.azimuth = angle_per_frame * frame

                # Принудительный рендеринг с высоким качеством
                self.plotter.render()

                # Сохраняем кадр
                frame_path = os.path.join(temp_dir, f"frame_{frame:04d}.png")
                self.plotter.screenshot(
                    frame_path, return_img=False, transparent_background=False, scale=1
                )  # scale=1 для максимального качества
                frames.append(frame_path)

                # Обновляем прогресс каждый кадр, но не блокируем UI
                if frame % 5 == 0 or frame == total_frames - 1:
                    progress = int(100 * (frame + 1) / total_frames)
                    self.progress_bar.setValue(progress)
                    self.progress_label.setText(
                        f"Создание кадров... {frame + 1}/{total_frames}"
                    )
                    QApplication.processEvents()

            # Создаем видео из кадров
            if frames:
                self.progress_label.setText("Сглаживание кадров...")
                self.progress_bar.setValue(85)
                QApplication.processEvents()

                # Сглаживаем все кадры для устранения муара
                for i, frame_path in enumerate(frames):
                    img = cv2.imread(frame_path)
                    if img is not None:
                        # Увеличиваем разрешение
                        h, w = img.shape[:2]
                        img = cv2.resize(
                            img, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4
                        )

                        # Применяем сглаживающие фильтры
                        img = cv2.GaussianBlur(img, (5, 5), 0.8)  # Размытие
                        # img = cv2.bilateralFilter(img, 9, 75, 75)  # Сохраняет края

                        # Уменьшаем обратно с высоким качеством
                        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4)

                        # Сохраняем обработанный кадр
                        cv2.imwrite(frame_path, img, [cv2.IMWRITE_PNG_COMPRESSION, 3])

                    if i % 50 == 0:
                        smooth_progress = 85 + int(10 * (i + 1) / len(frames))
                        self.progress_bar.setValue(smooth_progress)
                        self.progress_label.setText(
                            f"Сглаживание кадров... {i + 1}/{len(frames)}"
                        )
                        QApplication.processEvents()

                self.progress_bar.setValue(95)
                self.progress_label.setText("Компиляция видео...")
                QApplication.processEvents()

                # Получаем размеры первого кадра
                first_frame = cv2.imread(frames[0])
                height, width = first_frame.shape[:2]

                # Используем более качественный кодек
                fourcc = cv2.VideoWriter_fourcc(*"avc1")  # H.264 для macOS
                video_writer = cv2.VideoWriter(save_file, fourcc, fps, (width, height))

                if not video_writer.isOpened():
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    video_writer = cv2.VideoWriter(
                        save_file, fourcc, fps, (width, height)
                    )

                if not video_writer.isOpened():
                    # Последняя попытка с другим кодеком
                    fourcc = cv2.VideoWriter_fourcc(*"XVID")
                    video_writer = cv2.VideoWriter(
                        save_file, fourcc, fps, (width, height)
                    )

                if not video_writer.isOpened():
                    raise Exception("Не удалось создать видео файл")

                # Добавляем кадры в видео
                for i, frame_path in enumerate(frames):
                    frame = cv2.imread(frame_path)
                    if frame is not None:
                        video_writer.write(frame)

                    if i % 50 == 0:
                        compile_progress = 95 + int(5 * (i + 1) / len(frames))
                        self.progress_bar.setValue(compile_progress)
                        self.progress_label.setText(
                            f"Компиляция видео... {i + 1}/{len(frames)}"
                        )
                        QApplication.processEvents()

                video_writer.release()

                # Очищаем временные файлы
                self.progress_label.setText("Очистка временных файлов...")
                QApplication.processEvents()
                shutil.rmtree(temp_dir, ignore_errors=True)

            # Восстановление исходной позиции камеры
            self.plotter.camera_position = original_position
            self.plotter.render()

            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Видео создано успешно")
            self.log_message(f"Видео сохранено: {save_file}")

            video_size = os.path.getsize(save_file) / (1024 * 1024)
            QMessageBox.information(
                self,
                "Успех",
                f"Видео успешно создано\n\n"
                f"Файл: {os.path.basename(save_file)}\n"
                f"Размер: {video_size:.1f} МБ\n"
                f"Кадров: {total_frames}\n"
                f"FPS: {fps}\n"
                f"Длительность: {duration} сек\n"
                f"Разрешение: {width}x{height}",
            )

        except ImportError:
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Ошибка: OpenCV не установлен")
            self.log_message("Ошибка: требуется установка opencv-python")
            QMessageBox.critical(
                self,
                "Ошибка",
                "Для создания видео требуется OpenCV.\n\n"
                "Выполните команду в терминале:\n"
                "pip install opencv-python",
            )
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Ошибка создания видео")
            self.log_message(f"Ошибка создания видео: {str(e)}")
            QMessageBox.critical(
                self, "Ошибка", f"Ошибка при создании видео:\n\n{str(e)}"
            )

    def export_model(self):
        """Экспорт модели в различные форматы"""
        if not self.current_mesh:
            QMessageBox.warning(self, "Предупреждение", "Сначала визуализируйте модель")
            return

        # Выбор формата и файла
        save_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт модели",
            "",
            "STL files (*.stl);;GLB files (*.glb);;PLY files (*.ply)",
        )

        if not save_file:
            return

        try:
            self.log_message(f"Экспорт модели в: {save_file}")
            self.current_mesh.save(save_file)
            self.log_message("Экспорт успешно завершен")
            QMessageBox.information(self, "Успех", "Модель успешно экспортирована")

        except Exception as e:
            self.log_message(f"Ошибка экспорта: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при экспорте: {str(e)}")


def main():
    """Основная функция"""
    app = QApplication(sys.argv)

    # Установка стиля
    app.setStyle("Fusion")

    # Установка шрифта по умолчанию
    font = QFont("Arial", 12)
    app.setFont(font)

    # Создание и отображение главного окна
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
