#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GCODE Wave Generator - С вкладками для удобства
Вкладка 1: Математические волны
Вкладка 2: Карта высот
Вкладка 3: Генерация и лог
"""

import math
import os
import re
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Для работы с изображениями
try:
    import numpy as np
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ============================================
# ПАРАМЕТРЫ ПАНЕЛИ
# ============================================
PANEL_WIDTH = 1200  # мм по оси X
PANEL_HEIGHT = 3100  # мм по оси Z
PANEL_DEPTH = 40  # мм по оси Y
WORKING_THRESHOLD = 15  # Рабочая зона: Y < 15 мм

DEFAULT_HM_WIDTH_RATIO = 0.9
DEFAULT_HM_HEIGHT_RATIO = 0.9

PANEL_SIDE_FRONT = 0
PANEL_SIDE_BACK = 1


# ============================================
# КЛАСС ДЛЯ КАРТЫ ВЫСОТ
# ============================================


class HeightMap:
    def __init__(
        self,
        image_path,
        panel_width=PANEL_WIDTH,
        panel_height=PANEL_HEIGHT,
        width_mm=None,
        height_mm=None,
        offset_x_mm=None,
        offset_z_mm=None,
        keep_aspect=True,
        invert=False,
        mirror_x=False,
        mirror_z=False,
        panel_side=PANEL_SIDE_FRONT,
    ):
        self.image_path = image_path
        self.panel_width = panel_width
        self.panel_height = panel_height
        self.panel_side = panel_side

        # Размеры карты на панели (мм)
        self.width_mm = (
            width_mm if width_mm is not None else panel_width * DEFAULT_HM_WIDTH_RATIO
        )
        self.height_mm = (
            height_mm
            if height_mm is not None
            else panel_height * DEFAULT_HM_HEIGHT_RATIO
        )

        # Смещение карты (центрируем по умолчанию)
        self.offset_x_mm = (
            offset_x_mm
            if offset_x_mm is not None
            else (panel_width - self.width_mm) / 2
        )
        self.offset_z_mm = (
            offset_z_mm
            if offset_z_mm is not None
            else (panel_height - self.height_mm) / 2
        )

        self.keep_aspect = keep_aspect
        self.invert = invert
        self.mirror_x = mirror_x
        self.mirror_z = mirror_z
        self.height_data = None
        self.img_width = 0
        self.img_height = 0
        self.preview_pixmap = None
        self.load_image()

    def load_image(self):
        if not PIL_AVAILABLE:
            raise ImportError("Установите Pillow: pip install Pillow")

        img = Image.open(self.image_path)
        original_width, original_height = img.size
        img_ratio = original_width / original_height

        # Сохраняем запрошенные размеры до коррекции
        requested_width = self.width_mm
        requested_height = self.height_mm

        if self.keep_aspect:
            target_ratio = requested_width / requested_height

            if img_ratio > target_ratio:
                # Изображение шире - подгоняем по ширине
                self.width_mm = requested_width
                self.height_mm = requested_width / img_ratio
                # Центрируем по высоте
                self.offset_z_mm = (self.panel_height - self.height_mm) / 2
            else:
                # Изображение выше - подгоняем по высоте
                self.height_mm = requested_height
                self.width_mm = requested_height * img_ratio
                # Центрируем по ширине
                self.offset_x_mm = (self.panel_width - self.width_mm) / 2

        # Применяем зеркалирование до конвертации в серый
        if self.mirror_x:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self.mirror_z:
            img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        # Конвертируем в оттенки серого
        if img.mode != "L":
            img = img.convert("L")

        self.img_width, self.img_height = img.size

        # Получаем массив значений (0-1)
        self.height_data = np.array(img, dtype=np.float32) / 255.0

        # Инвертируем если нужно
        if self.invert:
            self.height_data = 1.0 - self.height_data

        # Создаём превью
        self.create_preview()

        # Для отладки - выводим реальные размеры
        print(
            f"Изображение: {original_width}x{original_height} px, соотношение: {img_ratio:.3f}"
        )
        print(f"Запрошено: {requested_width:.1f}x{requested_height:.1f} мм")
        print(f"Реально: {self.width_mm:.1f}x{self.height_mm:.1f} мм")
        print(f"Позиция: X={self.offset_x_mm:.1f}, Z={self.offset_z_mm:.1f}")

    def create_preview(self, preview_size=(300, 300)):
        img_data = (self.height_data * 255).astype(np.uint8)
        img = Image.fromarray(img_data)
        img = img.resize(preview_size, Image.Resampling.LANCZOS)
        data = img.tobytes("raw", "L")
        qimage = QImage(
            data,
            preview_size[0],
            preview_size[1],
            preview_size[0],
            QImage.Format.Format_Grayscale8,
        )
        self.preview_pixmap = self.apply_false_colors(qimage)

    def apply_false_colors(self, qimage):
        result = QPixmap(qimage.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        for x in range(qimage.width()):
            for y in range(qimage.height()):
                intensity = QColor(qimage.pixelColor(x, y)).red() / 255.0
                if intensity < 0.5:
                    r = 0
                    g = int(255 * intensity * 2)
                    b = 255 - g
                else:
                    r = int(255 * (intensity - 0.5) * 2)
                    g = 255 - r
                    b = 0
                painter.setPen(QColor(r, g, b))
                painter.drawPoint(x, y)
        painter.end()
        return result

    def get_height(self, x_mm, z_mm, amplitude):
        # Для тыльной стороны зеркалим координаты
        if self.panel_side == PANEL_SIDE_BACK:
            x_mm = self.panel_width - x_mm
            z_mm = self.panel_height - z_mm

        # Проверяем попадание в область карты
        if (
            x_mm < self.offset_x_mm
            or x_mm > self.offset_x_mm + self.width_mm
            or z_mm < self.offset_z_mm
            or z_mm > self.offset_z_mm + self.height_mm
        ):
            return 0

        # Нормализуем координаты (0..1) в пределах области карты
        nx = (x_mm - self.offset_x_mm) / self.width_mm
        nz = (z_mm - self.offset_z_mm) / self.height_mm

        # Преобразуем в пиксельные координаты
        px = int(nx * (self.img_width - 1))
        pz = int(nz * (self.img_height - 1))

        # Защита от выхода за границы
        px = max(0, min(px, self.img_width - 1))
        pz = max(0, min(pz, self.img_height - 1))

        # Получаем значение высоты (0-1) и масштабируем
        height_value = self.height_data[pz, px]
        # Преобразуем: 0 -> -amplitude/2, 1 -> +amplitude/2
        offset = (height_value - 0.5) * amplitude

        return offset

    def get_info_text(self):
        side_text = "Передняя" if self.panel_side == PANEL_SIDE_FRONT else "Тыльная"
        return (
            f"Сторона: {side_text}\n"
            f"Размер изображения: {self.img_width}×{self.img_height} px\n"
            f"Размер на панели: {self.width_mm:.1f}×{self.height_mm:.1f} мм\n"
            f"Позиция: X={self.offset_x_mm:.1f}, Z={self.offset_z_mm:.1f}\n"
            f"Инверсия: {'да' if self.invert else 'нет'}\n"
            f"Зеркало X/Z: {'да' if self.mirror_x else 'нет'}/{'да' if self.mirror_z else 'нет'}"
        )


# ============================================
# ПРЕДПРОСМОТР КАРТЫ ВЫСОТ
# ============================================


class HeightMapPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 250)
        self.setMaximumSize(350, 350)
        self.pixmap = None
        self.setStyleSheet(
            "background-color: #2b2b2b; border: 2px solid #555; border-radius: 5px;"
        )

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        if self.pixmap:
            painter = QPainter(self)
            scaled = self.pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(43, 43, 43))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Загрузите изображение"
            )


# ============================================
# МАТЕМАТИЧЕСКИЕ ФУНКЦИИ ВОЛН
# ============================================


class WaveFunctions:
    @staticmethod
    def get_wave_types():
        return {
            "water": {
                "name": "💧 Круги на воде",
                "default_params": {
                    "amplitude": 6.0,
                    "wavelength": 80.0,
                    "decay": 600.0,
                },
            },
            "sand": {
                "name": "🏜️ Песчаные дюны",
                "default_params": {"amplitude": 8.0, "spacing": 100.0, "ripple": 25.0},
            },
            "sound": {
                "name": "🎵 Звуковая волна",
                "default_params": {"amplitude": 7.0, "frequency": 0.08, "decay": 800.0},
            },
            "mercury": {
                "name": "💎 Жидкий металл",
                "default_params": {"amplitude": 5.0, "wavelength": 60.0},
            },
            "glitch": {
                "name": "📺 Цифровой глитч",
                "default_params": {"amplitude": 10.0, "density": 0.02},
            },
            "waves": {
                "name": "🌊 Океанские волны",
                "default_params": {"amplitude": 12.0, "wavelength": 150.0},
            },
            "diamond": {
                "name": "💠 Алмазная грань",
                "default_params": {"amplitude": 4.0, "spacing": 80.0},
            },
        }

    @staticmethod
    def water_ripples(
        x, z, y, amplitude, wavelength, decay, center_x=600, center_z=1550
    ):
        centers = [
            (center_x, center_z, 1.0),
            (center_x + 200, center_z + 250, 0.5),
            (center_x - 180, center_z + 200, 0.5),
            (center_x + 150, center_z - 250, 0.4),
            (center_x - 200, center_z - 200, 0.4),
        ]
        total = 0
        for cx, cz, intensity in centers:
            dx, dz = x - cx, z - cz
            r = math.sqrt(dx * dx + dz * dz)
            if r < 10:
                continue
            total += (
                amplitude
                * intensity
                * math.sin(2 * math.pi * r / wavelength)
                * math.exp(-r / decay)
            )
        return total / len(centers) * 1.5

    @staticmethod
    def sand_dunes(x, z, y, amplitude, spacing, ripple, **kwargs):
        main = amplitude * (math.sin(x / spacing) + 0.3 * math.sin(3 * x / spacing))
        asym = amplitude * 0.4 * (2 / math.pi) * math.atan(3 * math.sin(x / spacing))
        rip = 2.0 * math.sin(x / ripple) * math.sin(z / (ripple * 1.2))
        mod = 1.5 * math.sin(z / 400) * math.sin(x / 80)
        return main + asym + rip + mod

    @staticmethod
    def sound_wave(x, z, y, amplitude, frequency, decay, **kwargs):
        main = (
            amplitude
            * math.sin(frequency * x)
            * math.exp(-abs(x - PANEL_WIDTH / 2) / decay)
        )
        harm = (
            2.0
            * math.sin(3 * frequency * x)
            * math.exp(-abs(x - PANEL_WIDTH / 2) / (decay * 1.5))
        )
        env = 1 + 0.5 * math.sin(z / 300)
        noise = 1.0 * math.sin(x / 45) * math.cos(z / 60)
        return (main + harm) * env + noise

    @staticmethod
    def liquid_mercury(x, z, y, amplitude, wavelength, **kwargs):
        radial = 0
        centers = [(600, 1550), (300, 800), (900, 2300), (200, 2000), (1000, 1000)]
        for cx, cz in centers:
            r = math.sqrt((x - cx) ** 2 + (z - cz) ** 2) / wavelength
            radial += math.sin(r) / (1 + r * 0.2)
        cross = (
            0.6 * math.sin(x / 45) * math.sin(z / 45)
            + 0.4 * math.sin(x / 25) * math.cos(z / 35)
            + 0.3 * math.sin((x + z) / 55)
        )
        nonlin = 1.5 * math.sin((x * z) / 15000)
        return amplitude * (radial / len(centers) + cross * 0.5 + nonlin * 0.3)

    @staticmethod
    def glitch_effect(x, z, y, amplitude, density, **kwargs):
        step = amplitude * math.floor(math.sin(x / 80) * 2.5) / 2.5
        glitch_zones = int(abs(x / 150)) % 8
        glitch = (
            amplitude * 0.7 * math.sin(x * 0.3) * (glitch_zones - 5) / 3
            if glitch_zones > 5
            else 0
        )
        tear = amplitude * 0.5 * math.sin(x / 40) if abs(math.sin(z / 200)) > 0.9 else 0
        drift = 2.5 * math.sin(x / 300)
        return step + glitch + tear + drift

    @staticmethod
    def ocean_waves(x, z, y, amplitude, wavelength, **kwargs):
        main = amplitude * math.sin(x / wavelength) * math.sin(z / 200)
        second = amplitude * 0.4 * math.sin(x / (wavelength * 0.7) + math.pi / 4)
        mod = 1.5 * math.sin(z / 250) * math.sin(x / 100)
        peaks = amplitude * 0.3 * abs(math.sin(x / wavelength)) ** 3
        return main + second + mod + peaks

    @staticmethod
    def diamond_pattern(x, z, y, amplitude, spacing, **kwargs):
        x1, z1 = (x + z) / math.sqrt(2), (x - z) / math.sqrt(2)
        wave1 = amplitude * math.sin(x1 / spacing) * math.cos(z1 / spacing)
        wave2 = amplitude * 0.6 * math.sin((x1 + z1) / (spacing * 0.7))
        diamond = wave1 * wave2 / amplitude
        convex = amplitude * 0.2 * math.sin(x / 500) * math.sin(z / 500)
        return diamond + convex


# ============================================
# ПОТОК ОБРАБОТКИ GCODE
# ============================================


class GCodeProcessor(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        input_file,
        output_file,
        wave_type,
        params,
        use_heightmap=False,
        heightmap=None,
        heightmap_amplitude=10.0,
        blend_mode="add",
    ):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.wave_type = wave_type
        self.params = params
        self.use_heightmap = use_heightmap
        self.heightmap = heightmap
        self.heightmap_amplitude = heightmap_amplitude
        self.blend_mode = blend_mode
        if "amplitude" in self.params:
            self.params["amplitude"] = min(self.params["amplitude"], PANEL_DEPTH * 0.8)

    def get_wave_function(self):
        funcs = {
            "water": WaveFunctions.water_ripples,
            "sand": WaveFunctions.sand_dunes,
            "sound": WaveFunctions.sound_wave,
            "mercury": WaveFunctions.liquid_mercury,
            "glitch": WaveFunctions.glitch_effect,
            "waves": WaveFunctions.ocean_waves,
            "diamond": WaveFunctions.diamond_pattern,
        }
        return funcs.get(self.wave_type, WaveFunctions.water_ripples)

    def get_offset(self, x, z, y):
        wave = 0
        if self.wave_type != "none":
            wave = self.get_wave_function()(x, z, y, **self.params)

        hm = 0
        if self.use_heightmap and self.heightmap:
            hm = self.heightmap.get_height(x, z, self.heightmap_amplitude)

        if self.blend_mode == "add":
            return wave + hm
        elif self.blend_mode == "multiply":
            return wave * (1 + hm / self.heightmap_amplitude)
        elif self.blend_mode == "max":
            return max(wave, hm)
        return wave + hm

    def run(self):
        try:
            self.process_gcode()
        except Exception as e:
            self.error.emit(str(e))

    def process_gcode(self):
        total = 0
        with open(self.input_file, "r") as f:
            for line in f:
                if re.match(r"^G[01]\s", line):
                    total += 1

        if total == 0:
            self.error.emit("Не найдено команд перемещения")
            return

        processed = 0
        with (
            open(self.input_file, "r") as infile,
            open(self.output_file, "w") as outfile,
        ):
            for line in infile:
                if re.match(r"^G[01]\s", line):
                    xm = re.search(r"X([+-]?\d*\.?\d+)", line)
                    ym = re.search(r"Y([+-]?\d*\.?\d+)", line)
                    zm = re.search(r"Z([+-]?\d*\.?\d+)", line)
                    em = re.search(r"E([+-]?\d*\.?\d+)", line)
                    fm = re.search(r"F(\d+)", line)

                    x = float(xm.group(1)) if xm else 0
                    y = float(ym.group(1)) if ym else 0
                    z = float(zm.group(1)) if zm else 0

                    if y < WORKING_THRESHOLD:
                        y += self.get_offset(x, z, y)

                    parts = ["G1"]
                    if xm:
                        parts.append(f"X{x:.4f}")
                    if ym:
                        parts.append(f"Y{y:.4f}")
                    if zm:
                        parts.append(f"Z{z:.4f}")
                    if em:
                        parts.append(f"E{float(em.group(1)):.4f}")
                    if fm:
                        parts.append(f"F{fm.group(1)}")

                    outfile.write(" ".join(parts) + "\n")
                    processed += 1
                    if processed % 1000 == 0:
                        self.progress.emit(
                            int(processed / total * 100),
                            f"Обработано {processed} из {total}",
                        )
                else:
                    outfile.write(line)

        self.progress.emit(100, "Готово!")
        self.finished.emit(self.output_file)


# ============================================
# ГЛАВНОЕ ОКНО С ВКЛАДКАМИ
# ============================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.input_file = None
        self.heightmap = None
        self.processor = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GCODE Wave Generator")
        self.setMinimumSize(900, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Заголовок
        title = QLabel("🌊 GCODE Wave Generator")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Подзаголовок
        subtitle = QLabel(
            f"Панель: {PANEL_WIDTH}×{PANEL_HEIGHT} мм | Рабочая зона: Y < {WORKING_THRESHOLD} мм"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #555; font-size: 12px;")
        main_layout.addWidget(subtitle)

        # Вкладки
        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # Вкладка 1: Математические волны
        wave_tab = QWidget()
        tabs.addTab(wave_tab, "🌊 Математические волны")
        wave_layout = QVBoxLayout(wave_tab)

        # Вкладка 2: Карта высот
        hm_tab = QWidget()
        tabs.addTab(hm_tab, "🗺️ Карта высот")
        hm_layout = QVBoxLayout(hm_tab)

        # Вкладка 3: Генерация
        gen_tab = QWidget()
        tabs.addTab(gen_tab, "🚀 Генерация")
        gen_layout = QVBoxLayout(gen_tab)

        # ========== ВКЛАДКА 1: МАТЕМАТИЧЕСКИЕ ВОЛНЫ ==========

        # Выбор файла
        file_group = QGroupBox("📁 Файл GCODE")
        file_layout = QHBoxLayout(file_group)
        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet(
            "color: gray; padding: 5px; border: 1px solid #ccc; border-radius: 3px;"
        )
        select_btn = QPushButton("Выбрать")
        select_btn.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_label, 1)
        file_layout.addWidget(select_btn)
        wave_layout.addWidget(file_group)

        # Тип волны
        wave_type_group = QGroupBox("Тип волны")
        wt_layout = QGridLayout(wave_type_group)
        self.wave_combo = QComboBox()
        for key, info in WaveFunctions.get_wave_types().items():
            self.wave_combo.addItem(info["name"], key)
        self.wave_combo.addItem("⛔ Нет волны", "none")
        self.wave_combo.currentIndexChanged.connect(self.update_wave_params)
        wt_layout.addWidget(QLabel("Выберите тип:"), 0, 0)
        wt_layout.addWidget(self.wave_combo, 0, 1)
        wave_layout.addWidget(wave_type_group)

        # Параметры волны
        params_group = QGroupBox("Параметры волны")
        params_layout = QGridLayout(params_group)

        params_layout.addWidget(QLabel("Амплитуда (мм):"), 0, 0)
        self.amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.amp_slider.setRange(10, 350)
        self.amp_slider.setValue(80)
        self.amp_slider.valueChanged.connect(
            lambda: self.amp_label.setText(f"{self.amp_slider.value() / 10:.1f} мм")
        )
        params_layout.addWidget(self.amp_slider, 0, 1)
        self.amp_label = QLabel("8.0 мм")
        params_layout.addWidget(self.amp_label, 0, 2)

        params_layout.addWidget(QLabel("Длина волны (мм):"), 1, 0)
        self.wave_slider = QSlider(Qt.Orientation.Horizontal)
        self.wave_slider.setRange(30, 300)
        self.wave_slider.setValue(100)
        self.wave_slider.valueChanged.connect(
            lambda: self.wave_label.setText(f"{self.wave_slider.value()} мм")
        )
        params_layout.addWidget(self.wave_slider, 1, 1)
        self.wave_label = QLabel("100 мм")
        params_layout.addWidget(self.wave_label, 1, 2)

        params_layout.addWidget(QLabel("Затухание:"), 2, 0)
        self.decay_slider = QSlider(Qt.Orientation.Horizontal)
        self.decay_slider.setRange(200, 1500)
        self.decay_slider.setValue(600)
        self.decay_slider.valueChanged.connect(
            lambda: self.decay_label.setText(f"{self.decay_slider.value()}")
        )
        params_layout.addWidget(self.decay_slider, 2, 1)
        self.decay_label = QLabel("600")
        params_layout.addWidget(self.decay_label, 2, 2)

        params_layout.addWidget(QLabel("Рябь / Плотность:"), 3, 0)
        self.density_slider = QSlider(Qt.Orientation.Horizontal)
        self.density_slider.setRange(10, 80)
        self.density_slider.setValue(25)
        self.density_slider.valueChanged.connect(
            lambda: self.density_label.setText(f"{self.density_slider.value()}")
        )
        params_layout.addWidget(self.density_slider, 3, 1)
        self.density_label = QLabel("25")
        params_layout.addWidget(self.density_label, 3, 2)

        wave_layout.addWidget(params_group)

        # Центр волны
        center_group = QGroupBox("Центр волны (для круговых волн)")
        center_layout = QHBoxLayout(center_group)
        center_layout.addWidget(QLabel("Центр X:"))
        self.center_x = QSpinBox()
        self.center_x.setRange(0, PANEL_WIDTH)
        self.center_x.setValue(PANEL_WIDTH // 2)
        center_layout.addWidget(self.center_x)
        center_layout.addWidget(QLabel("Центр Z:"))
        self.center_z = QSpinBox()
        self.center_z.setRange(0, PANEL_HEIGHT)
        self.center_z.setValue(PANEL_HEIGHT // 2)
        center_layout.addWidget(self.center_z)
        wave_layout.addWidget(center_group)

        wave_layout.addStretch()

        # ========== ВКЛАДКА 2: КАРТА ВЫСОТ ==========

        # Использовать карту
        self.use_hm_cb = QCheckBox("Использовать карту высот")
        self.use_hm_cb.toggled.connect(self.toggle_heightmap)
        hm_layout.addWidget(self.use_hm_cb)

        # Загрузка файла
        hm_file_group = QGroupBox("Загрузка изображения")
        hm_file_layout = QHBoxLayout(hm_file_group)
        self.hm_file_label = QLabel("Файл не выбран")
        self.hm_file_label.setStyleSheet(
            "color: gray; padding: 5px; border: 1px solid #ccc; border-radius: 3px;"
        )
        self.hm_select_btn = QPushButton("Загрузить")
        self.hm_select_btn.clicked.connect(self.select_heightmap)
        self.hm_select_btn.setEnabled(False)
        hm_file_layout.addWidget(self.hm_file_label, 1)
        hm_file_layout.addWidget(self.hm_select_btn)
        hm_layout.addWidget(hm_file_group)

        # Сторона панели
        side_layout = QHBoxLayout()
        side_layout.addWidget(QLabel("Сторона панели:"))
        self.side_combo = QComboBox()
        self.side_combo.addItems(["Передняя", "Тыльная"])
        self.side_combo.setEnabled(False)
        side_layout.addWidget(self.side_combo)
        hm_layout.addLayout(side_layout)

        # Разделитель для предпросмотра и настроек
        hm_splitter = QSplitter(Qt.Orientation.Horizontal)
        hm_layout.addWidget(hm_splitter)

        # Левая часть - предпросмотр
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.addWidget(QLabel("Предпросмотр:"))
        self.preview = HeightMapPreview()
        preview_layout.addWidget(self.preview)
        hm_splitter.addWidget(preview_widget)

        # Правая часть - настройки
        hm_settings = QWidget()
        hm_settings_layout = QVBoxLayout(hm_settings)

        # Размеры
        size_group = QGroupBox("Размеры и положение")
        size_layout = QGridLayout(size_group)
        size_layout.addWidget(QLabel("Ширина (мм):"), 0, 0)
        self.hm_width = QDoubleSpinBox()
        self.hm_width.setRange(10, PANEL_WIDTH)
        self.hm_width.setValue(PANEL_WIDTH * DEFAULT_HM_WIDTH_RATIO)
        self.hm_width.setEnabled(False)
        size_layout.addWidget(self.hm_width, 0, 1)
        size_layout.addWidget(QLabel("Высота (мм):"), 1, 0)
        self.hm_height = QDoubleSpinBox()
        self.hm_height.setRange(10, PANEL_HEIGHT)
        self.hm_height.setValue(PANEL_HEIGHT * DEFAULT_HM_HEIGHT_RATIO)
        self.hm_height.setEnabled(False)
        size_layout.addWidget(self.hm_height, 1, 1)
        size_layout.addWidget(QLabel("Позиция X (мм):"), 2, 0)
        self.hm_off_x = QDoubleSpinBox()
        self.hm_off_x.setRange(0, PANEL_WIDTH)
        self.hm_off_x.setValue((PANEL_WIDTH - PANEL_WIDTH * DEFAULT_HM_WIDTH_RATIO) / 2)
        self.hm_off_x.setEnabled(False)
        size_layout.addWidget(self.hm_off_x, 2, 1)
        size_layout.addWidget(QLabel("Позиция Z (мм):"), 3, 0)
        self.hm_off_z = QDoubleSpinBox()
        self.hm_off_z.setRange(0, PANEL_HEIGHT)
        self.hm_off_z.setValue(
            (PANEL_HEIGHT - PANEL_HEIGHT * DEFAULT_HM_HEIGHT_RATIO) / 2
        )
        self.hm_off_z.setEnabled(False)
        size_layout.addWidget(self.hm_off_z, 3, 1)
        self.keep_aspect = QCheckBox("Сохранять пропорции")
        self.keep_aspect.setChecked(True)
        self.keep_aspect.setEnabled(False)
        size_layout.addWidget(self.keep_aspect, 4, 0, 1, 2)
        hm_settings_layout.addWidget(size_group)

        # Обработка
        proc_group = QGroupBox("Обработка")
        proc_layout = QGridLayout(proc_group)
        self.invert_cb = QCheckBox("Инвертировать высоты")
        self.invert_cb.setEnabled(False)
        proc_layout.addWidget(self.invert_cb, 0, 0)
        self.mirror_x_cb = QCheckBox("Зеркало по X")
        self.mirror_x_cb.setEnabled(False)
        proc_layout.addWidget(self.mirror_x_cb, 1, 0)
        self.mirror_z_cb = QCheckBox("Зеркало по Z")
        self.mirror_z_cb.setEnabled(False)
        proc_layout.addWidget(self.mirror_z_cb, 2, 0)
        hm_settings_layout.addWidget(proc_group)

        # Параметры
        hm_params_group = QGroupBox("Параметры")
        hm_params_layout = QGridLayout(hm_params_group)
        hm_params_layout.addWidget(QLabel("Амплитуда (мм):"), 0, 0)
        self.hm_amp = QDoubleSpinBox()
        self.hm_amp.setRange(1, 30)
        self.hm_amp.setValue(10)
        self.hm_amp.setEnabled(False)
        hm_params_layout.addWidget(self.hm_amp, 0, 1)
        hm_params_layout.addWidget(QLabel("Режим смешивания:"), 1, 0)
        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Сложение", "Умножение", "Максимум"])
        self.blend_combo.setEnabled(False)
        hm_params_layout.addWidget(self.blend_combo, 1, 1)
        hm_settings_layout.addWidget(hm_params_group)

        # Информация
        self.hm_info = QLabel("")
        self.hm_info.setWordWrap(True)
        self.hm_info.setStyleSheet(
            "color: #666; font-size: 10px; background: #f5f5f5; padding: 5px; border-radius: 3px;"
        )
        hm_settings_layout.addWidget(self.hm_info)

        hm_splitter.addWidget(hm_settings)
        hm_splitter.setSizes([300, 400])

        hm_layout.addStretch()

        # ========== ВКЛАДКА 3: ГЕНЕРАЦИЯ ==========

        # Инфо о текущих настройках
        info_group = QGroupBox("Текущие настройки")
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel("Настройки не заданы")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        info_layout.addWidget(self.info_label)
        gen_layout.addWidget(info_group)

        # Кнопка генерации
        self.generate_btn = QPushButton("🚀 Сгенерировать GCODE")
        self.generate_btn.setMinimumHeight(50)
        self.generate_btn.setStyleSheet(
            "font-size: 14px; font-weight: bold; background-color: #4CAF50; color: white;"
        )
        self.generate_btn.clicked.connect(self.generate_gcode)
        self.generate_btn.setEnabled(False)
        gen_layout.addWidget(self.generate_btn)

        # Прогресс
        self.progress_bar = QProgressBar()
        gen_layout.addWidget(self.progress_bar)

        # Лог
        log_label = QLabel("Лог операций:")
        gen_layout.addWidget(log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        gen_layout.addWidget(self.log_text)

        # Статусбар
        self.statusBar().showMessage("Готов")

        # Проверка PIL
        if not PIL_AVAILABLE:
            self.log(
                "⚠️ Pillow не установлен. Карта высот недоступна. Установите: pip install Pillow"
            )
            self.use_hm_cb.setEnabled(False)

    def toggle_heightmap(self, enabled):
        self.hm_select_btn.setEnabled(enabled)
        self.side_combo.setEnabled(enabled)
        self.hm_width.setEnabled(enabled)
        self.hm_height.setEnabled(enabled)
        self.hm_off_x.setEnabled(enabled)
        self.hm_off_z.setEnabled(enabled)
        self.keep_aspect.setEnabled(enabled)
        self.invert_cb.setEnabled(enabled)
        self.mirror_x_cb.setEnabled(enabled)
        self.mirror_z_cb.setEnabled(enabled)
        self.hm_amp.setEnabled(enabled)
        self.blend_combo.setEnabled(enabled)
        if not enabled:
            self.hm_file_label.setText("Файл не выбран")
            self.hm_file_label.setStyleSheet(
                "color: gray; padding: 5px; border: 1px solid #ccc; border-radius: 3px;"
            )
            self.heightmap = None
            self.preview.set_pixmap(None)
            self.hm_info.setText("")
        self.update_info()

    def update_wave_params(self):
        wave_key = self.wave_combo.currentData()
        if wave_key != "none":
            params = (
                WaveFunctions.get_wave_types()
                .get(wave_key, {})
                .get("default_params", {})
            )
            self.amp_slider.setValue(int(params.get("amplitude", 8) * 10))
            if "wavelength" in params:
                self.wave_slider.setValue(int(params["wavelength"]))
            elif "frequency" in params:
                self.wave_slider.setValue(int(params["frequency"] * 1000))
            self.decay_slider.setValue(int(params.get("decay", 600)))
            self.density_slider.setValue(
                int(params.get("ripple", params.get("density", 25) * 100))
            )
        self.update_info()

    def update_info(self):
        wave_key = self.wave_combo.currentData()
        wave_name = self.wave_combo.currentText()
        info = f"📁 Файл: {os.path.basename(self.input_file) if self.input_file else 'не выбран'}\n"
        info += f"🌊 Волна: {wave_name}\n"
        info += f"   Амплитуда: {self.amp_slider.value() / 10:.1f} мм\n"

        if wave_key == "water":
            info += f"   Длина волны: {self.wave_slider.value()} мм\n"
            info += f"   Затухание: {self.decay_slider.value()}\n"
            info += f"   Центр: X={self.center_x.value()}, Z={self.center_z.value()}\n"
        elif wave_key == "sand":
            info += f"   Расстояние: {self.wave_slider.value()} мм\n"
            info += f"   Рябь: {self.density_slider.value()}\n"
        elif wave_key == "sound":
            info += f"   Частота: {self.wave_slider.value() / 1000:.3f}\n"
            info += f"   Затухание: {self.decay_slider.value()}\n"
        elif wave_key == "mercury":
            info += f"   Длина волны: {self.wave_slider.value()} мм\n"
        elif wave_key == "glitch":
            info += f"   Плотность: {self.density_slider.value() / 100:.3f}\n"
        elif wave_key == "waves":
            info += f"   Длина волны: {self.wave_slider.value()} мм\n"
        elif wave_key == "diamond":
            info += f"   Шаг: {self.wave_slider.value()} мм\n"

        if self.use_hm_cb.isChecked() and self.heightmap:
            info += f"\n🗺️ Карта высот: {os.path.basename(self.heightmap.image_path)}\n"
            info += f"   Сторона: {'Передняя' if self.side_combo.currentIndex() == 0 else 'Тыльная'}\n"
            info += f"   Размер: {self.heightmap.width_mm:.1f}×{self.heightmap.height_mm:.1f} мм\n"
            info += f"   Амплитуда: {self.hm_amp.value()} мм\n"
            info += f"   Режим: {self.blend_combo.currentText()}\n"

        self.info_label.setText(info)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите GCODE файл", "", "GCODE files (*.gcode *.gco *.nc)"
        )
        if path:
            self.input_file = path
            self.file_label.setText(os.path.basename(path))
            self.file_label.setStyleSheet(
                "color: green; padding: 5px; border: 1px solid green; border-radius: 3px;"
            )
            self.generate_btn.setEnabled(True)
            self.log(f"✅ Выбран файл: {path}")
            self.update_info()

    def select_heightmap(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите изображение", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            try:
                self.heightmap = HeightMap(
                    path,
                    PANEL_WIDTH,
                    PANEL_HEIGHT,
                    self.hm_width.value(),
                    self.hm_height.value(),
                    self.hm_off_x.value(),
                    self.hm_off_z.value(),
                    self.keep_aspect.isChecked(),
                    self.invert_cb.isChecked(),
                    self.mirror_x_cb.isChecked(),
                    self.mirror_z_cb.isChecked(),
                    PANEL_SIDE_FRONT
                    if self.side_combo.currentIndex() == 0
                    else PANEL_SIDE_BACK,
                )
                self.hm_file_label.setText(os.path.basename(path))
                self.hm_file_label.setStyleSheet(
                    "color: green; padding: 5px; border: 1px solid green; border-radius: 3px;"
                )
                if self.heightmap.preview_pixmap:
                    self.preview.set_pixmap(self.heightmap.preview_pixmap)
                self.hm_info.setText(self.heightmap.get_info_text())
                self.log(f"✅ Загружена карта высот: {path}")
                self.update_info()
            except Exception as e:
                self.log(f"❌ Ошибка: {e}")

    def get_wave_params(self):
        wave_key = self.wave_combo.currentData()
        if wave_key == "none":
            return {"amplitude": 0}
        params = {"amplitude": self.amp_slider.value() / 10.0}
        if wave_key == "water":
            params.update(
                {
                    "wavelength": float(self.wave_slider.value()),
                    "decay": float(self.decay_slider.value()),
                    "center_x": self.center_x.value(),
                    "center_z": self.center_z.value(),
                }
            )
        elif wave_key == "sand":
            params.update(
                {
                    "spacing": float(self.wave_slider.value()),
                    "ripple": float(self.density_slider.value()),
                }
            )
        elif wave_key == "sound":
            params.update(
                {
                    "frequency": self.wave_slider.value() / 1000.0,
                    "decay": float(self.decay_slider.value()),
                }
            )
        elif wave_key == "mercury":
            params.update({"wavelength": float(self.wave_slider.value())})
        elif wave_key == "glitch":
            params.update({"density": self.density_slider.value() / 100.0})
        elif wave_key == "waves":
            params.update({"wavelength": float(self.wave_slider.value())})
        elif wave_key == "diamond":
            params.update({"spacing": float(self.wave_slider.value())})
        return params

    def log(self, msg):
        from datetime import datetime

        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def generate_gcode(self):
        if not self.input_file:
            QMessageBox.warning(self, "Ошибка", "Выберите GCODE файл")
            return

        wave_key = self.wave_combo.currentData()
        use_hm = self.use_hm_cb.isChecked()

        if wave_key == "none" and not use_hm:
            QMessageBox.warning(self, "Ошибка", "Выберите волну или карту высот")
            return

        if use_hm and not self.heightmap:
            QMessageBox.warning(self, "Ошибка", "Загрузите изображение")
            return

        if use_hm and self.heightmap:
            self.heightmap.width_mm = self.hm_width.value()
            self.heightmap.height_mm = self.hm_height.value()
            self.heightmap.offset_x_mm = self.hm_off_x.value()
            self.heightmap.offset_z_mm = self.hm_off_z.value()
            self.heightmap.keep_aspect = self.keep_aspect.isChecked()
            self.heightmap.invert = self.invert_cb.isChecked()
            self.heightmap.mirror_x = self.mirror_x_cb.isChecked()
            self.heightmap.mirror_z = self.mirror_z_cb.isChecked()
            self.heightmap.panel_side = (
                PANEL_SIDE_FRONT
                if self.side_combo.currentIndex() == 0
                else PANEL_SIDE_BACK
            )

        suffix = f"_{wave_key}" if wave_key != "none" else ""
        if use_hm:
            suffix += "_hm"

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить GCODE",
            f"wavy{suffix}_{os.path.basename(self.input_file)}",
            "GCODE files (*.gcode)",
        )
        if not out_path:
            return

        blend_map = {"Сложение": "add", "Умножение": "multiply", "Максимум": "max"}

        self.log(f"🚀 Генерация...")
        self.log(f"   Волна: {self.wave_combo.currentText()}")
        if use_hm:
            self.log(f"   Карта: {os.path.basename(self.heightmap.image_path)}")

        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self.processor = GCodeProcessor(
            self.input_file,
            out_path,
            wave_key,
            self.get_wave_params(),
            use_hm,
            self.heightmap if use_hm else None,
            self.hm_amp.value(),
            blend_map[self.blend_combo.currentText()],
        )
        self.processor.progress.connect(self.update_progress)
        self.processor.finished.connect(lambda f: self.on_finished(f, out_path))
        self.processor.error.connect(self.on_error)
        self.processor.start()

    def update_progress(self, val, msg):
        self.progress_bar.setValue(val)
        if val % 20 == 0 or val == 100:
            self.log(msg)

    def on_finished(self, result, out_path):
        self.generate_btn.setEnabled(True)
        self.log(f"✅ Готово: {out_path}")
        self.statusBar().showMessage(f"Сохранён: {os.path.basename(out_path)}")
        QMessageBox.information(self, "Готово", f"Файл сохранён:\n{out_path}")

    def on_error(self, msg):
        self.generate_btn.setEnabled(True)
        self.log(f"❌ Ошибка: {msg}")
        QMessageBox.critical(self, "Ошибка", msg)


# ============================================
# ЗАПУСК
# ============================================


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
