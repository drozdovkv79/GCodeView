#!/usr/bin/env python3
"""
E57/LAS Viewer - Оптимизированный просмотрщик облаков точек
Поддержка E57 и LAS/LAZ форматов с детальным прогрессом
"""

import sys
import os
import gc
import time
import numpy as np
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QGroupBox, QProgressBar,
    QMessageBox, QFileDialog, QComboBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QFont

# Импорты PyVista
import pyvista as pv
from pyvistaqt import QtInteractor

# Импорт pye57
try:
    import pye57
    E57_AVAILABLE = True
except ImportError:
    E57_AVAILABLE = False
    print("⚠️ pye57 не установлен (pip install pye57)")

# Импорт laspy для LAS/LAZ
try:
    import laspy
    LASPY_AVAILABLE = True
except ImportError:
    LASPY_AVAILABLE = False
    print("⚠️ laspy не установлен (pip install laspy)")


class PointCloudReader(QThread):
    """Поток для чтения облаков точек (E57 и LAS) с чанковой загрузкой"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(object, object, object, object, int)
    error = pyqtSignal(str)
    memory_warning = pyqtSignal(float)
    log_message = pyqtSignal(str)

    def __init__(self, file_path, step=100, chunk_size=100000, use_colors=True):
        super().__init__()
        self.file_path = file_path
        self.step = step
        self.chunk_size = chunk_size
        self.use_colors = use_colors
        self.is_running = True
        self.start_time = None
        self.file_ext = os.path.splitext(file_path)[1].lower()

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}"
        self.log_message.emit(log_entry)
        print(log_entry)

    def stop(self):
        self.is_running = False

    def get_memory_usage(self):
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024**3)
        except:
            return 0

    def read_las_chunked(self, file_path):
        """Чтение LAS/LAZ файла по частям с детальным прогрессом"""
        self.log("📖 Чтение LAS/LAZ файла...")

        try:
            # Открываем LAS файл
            las = laspy.read(file_path)

            # Получаем общее количество точек
            total_points = len(las.points)
            self.log(f"📊 Всего точек в файле: {total_points:,}")

            # Получаем данные и конвертируем в numpy массивы
            self.log("🔄 Конвертация данных в numpy...")
            x = np.array(las.x, dtype=np.float64)
            y = np.array(las.y, dtype=np.float64)
            z = np.array(las.z, dtype=np.float64)

            # Цвета (если есть)
            has_colors = self.use_colors and hasattr(las, 'red') and las.red is not None
            if has_colors:
                r = np.array(las.red, dtype=np.uint16)
                g = np.array(las.green, dtype=np.uint16)
                b = np.array(las.blue, dtype=np.uint16)
                self.log(f"🎨 Цвета найдены (16-bit)")
            else:
                r = g = b = None
                self.log(f"⚠️ Цветов нет")

            # Рассчитываем сколько точек будет после фильтрации
            filtered_total = total_points // self.step
            if filtered_total == 0:
                filtered_total = total_points
            self.log(f"📊 После фильтрации (1:{self.step}): ~{filtered_total:,} точек")

            # Читаем чанками с фильтрацией
            all_x, all_y, all_z = [], [], []
            all_r, all_g, all_b = [], [], []

            processed = 0
            step = self.step

            # Отправляем начальный прогресс
            self.progress.emit(5)

            chunk_index = 0
            total_chunks = (total_points + self.chunk_size - 1) // self.chunk_size

            for start_idx in range(0, total_points, self.chunk_size):
                if not self.is_running:
                    return None, None, None, None, 0

                chunk_index += 1
                end_idx = min(start_idx + self.chunk_size, total_points)
                chunk_size_actual = end_idx - start_idx

                # Фильтрация
                if step > 1:
                    mask = np.arange(0, chunk_size_actual, step)

                    chunk_x = x[start_idx:end_idx][mask]
                    chunk_y = y[start_idx:end_idx][mask]
                    chunk_z = z[start_idx:end_idx][mask]

                    if has_colors:
                        chunk_r = r[start_idx:end_idx][mask]
                        chunk_g = g[start_idx:end_idx][mask]
                        chunk_b = b[start_idx:end_idx][mask]
                else:
                    chunk_x = x[start_idx:end_idx]
                    chunk_y = y[start_idx:end_idx]
                    chunk_z = z[start_idx:end_idx]

                    if has_colors:
                        chunk_r = r[start_idx:end_idx]
                        chunk_g = g[start_idx:end_idx]
                        chunk_b = b[start_idx:end_idx]

                # Добавляем данные (конвертируем в float32)
                all_x.extend(chunk_x.astype(np.float32))
                all_y.extend(chunk_y.astype(np.float32))
                all_z.extend(chunk_z.astype(np.float32))

                if has_colors and len(chunk_r) > 0:
                    all_r.extend(chunk_r.astype(np.float32))
                    all_g.extend(chunk_g.astype(np.float32))
                    all_b.extend(chunk_b.astype(np.float32))

                # Обновляем прогресс (5% - 95%)
                processed += chunk_size_actual
                progress = 5 + int((processed / total_points) * 90)
                progress = min(progress, 95)
                self.progress.emit(progress)

                # Логируем каждые 10 чанков
                if chunk_index % 10 == 0 or chunk_index == total_chunks:
                    self.log(f"  📊 Чанк {chunk_index}/{total_chunks}: {len(chunk_x):,} точек (прогресс: {progress}%)")

                # Освобождаем память от чанка
                del chunk_x, chunk_y, chunk_z
                if has_colors:
                    del chunk_r, chunk_g, chunk_b

                # Проверка памяти
                if processed % (self.chunk_size * 5) == 0:
                    mem_usage = self.get_memory_usage()
                    if mem_usage > 8.0:
                        self.memory_warning.emit(mem_usage)
                        gc.collect()

                # Периодическая сборка мусора
                if processed % (self.chunk_size * 10) == 0:
                    gc.collect()

            # Формируем результат
            self.log("🔧 Финальная обработка данных...")
            self.progress.emit(96)

            x_final = np.array(all_x, dtype=np.float32)
            y_final = np.array(all_y, dtype=np.float32)
            z_final = np.array(all_z, dtype=np.float32)

            colors = None
            if all_r and len(all_r) > 0:
                self.log("🎨 Обработка цветов...")
                colors = np.column_stack((all_r, all_g, all_b))
                # LAS использует 16-bit (0-65535)
                if colors.max() > 255:
                    colors = colors / 65535.0
                elif colors.max() > 1.0:
                    colors = colors / 255.0
                self.log(f"✅ Цвета обработаны: {colors.shape}")
            else:
                self.log("⚠️ Цветов нет")

            count = len(x_final)
            self.log(f"📊 Итого после фильтрации: {count:,} точек")

            # Освобождаем память
            del all_x, all_y, all_z
            if all_r:
                del all_r, all_g, all_b
            del x, y, z
            if has_colors:
                del r, g, b

            self.progress.emit(100)
            self.log(f"✅ LAS загружен: {count:,} точек")

            return x_final, y_final, z_final, colors, count

        except Exception as e:
            self.log(f"❌ Ошибка чтения LAS: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    def read_e57_chunked(self, file_path):
        """Чтение E57 файла с чанковой загрузкой"""
        self.log("📖 Чтение E57 файла...")

        try:
            e57_file = pye57.E57(file_path)
            scan_count = e57_file.scan_count
            self.log(f"📊 Найдено сканов: {scan_count}")

            if scan_count == 0:
                raise Exception("Файл не содержит сканов")

            # Получаем информацию о сканах
            total_points_estimate = 0
            scan_info_list = []

            self.log("📊 Получение информации о сканах...")
            for scan_idx in range(scan_count):
                if not self.is_running:
                    return None, None, None, None, 0
                try:
                    info = e57_file.scan_info(scan_idx)
                    count = info.get('point_count', 0)
                    scan_info_list.append(count)
                    total_points_estimate += count // self.step
                    self.log(f"  Скан {scan_idx + 1}: {count:,} точек")
                except:
                    scan_info_list.append(0)

            if total_points_estimate == 0:
                total_points_estimate = 1000000 // self.step

            self.log(f"📊 Приблизительное количество точек после фильтрации: {total_points_estimate:,}")
            self.progress.emit(5)

            # Читаем сканы
            all_x, all_y, all_z = [], [], []
            all_r, all_g, all_b = [], [], []

            processed = 0
            step = self.step

            for scan_idx in range(scan_count):
                if not self.is_running:
                    return None, None, None, None, 0

                scan_start = time.time()
                self.log(f"  📖 Чтение скана {scan_idx + 1}/{scan_count}...")
                self.progress.emit(10 + int((scan_idx / scan_count) * 10))

                try:
                    scan_data = e57_file.read_scan(
                        scan_idx,
                        colors=self.use_colors,
                        intensity=False,
                        ignore_missing_fields=True
                    )
                except Exception as e:
                    self.log(f"  ❌ Ошибка чтения скана: {str(e)}")
                    continue

                x = scan_data.get('cartesianX')
                y = scan_data.get('cartesianY')
                z = scan_data.get('cartesianZ')

                if x is None or len(x) == 0:
                    self.log(f"  ⚠️ Скан {scan_idx + 1} пуст")
                    continue

                point_count = len(x)
                self.log(f"  📊 Скан содержит {point_count:,} точек")

                has_colors = self.use_colors and all(
                    key in scan_data for key in ['colorRed', 'colorGreen', 'colorBlue']
                )

                if has_colors:
                    r = scan_data['colorRed']
                    g = scan_data['colorGreen']
                    b = scan_data['colorBlue']
                    self.log(f"  🎨 Цвета найдены")
                else:
                    r = g = b = None

                # Обрабатываем чанками
                chunk_index = 0
                total_chunks = (point_count + self.chunk_size - 1) // self.chunk_size

                for start_idx in range(0, point_count, self.chunk_size):
                    if not self.is_running:
                        return None, None, None, None, 0

                    chunk_index += 1
                    end_idx = min(start_idx + self.chunk_size, point_count)

                    if step > 1:
                        chunk_size_actual = end_idx - start_idx
                        mask = np.arange(0, chunk_size_actual, step)

                        chunk_x = x[start_idx:end_idx][mask]
                        chunk_y = y[start_idx:end_idx][mask]
                        chunk_z = z[start_idx:end_idx][mask]

                        if has_colors:
                            chunk_r = r[start_idx:end_idx][mask]
                            chunk_g = g[start_idx:end_idx][mask]
                            chunk_b = b[start_idx:end_idx][mask]
                    else:
                        chunk_x = x[start_idx:end_idx]
                        chunk_y = y[start_idx:end_idx]
                        chunk_z = z[start_idx:end_idx]

                        if has_colors:
                            chunk_r = r[start_idx:end_idx]
                            chunk_g = g[start_idx:end_idx]
                            chunk_b = b[start_idx:end_idx]

                    all_x.extend(chunk_x.astype(np.float32))
                    all_y.extend(chunk_y.astype(np.float32))
                    all_z.extend(chunk_z.astype(np.float32))

                    if has_colors:
                        all_r.extend(chunk_r.astype(np.float32))
                        all_g.extend(chunk_g.astype(np.float32))
                        all_b.extend(chunk_b.astype(np.float32))

                    processed += len(chunk_x)
                    if total_points_estimate > 0:
                        progress = 20 + int((processed / total_points_estimate) * 75)
                        progress = min(progress, 95)
                        self.progress.emit(progress)

                    del chunk_x, chunk_y, chunk_z
                    if has_colors:
                        del chunk_r, chunk_g, chunk_b

                    if processed % (self.chunk_size * 5) == 0:
                        mem_usage = self.get_memory_usage()
                        if mem_usage > 8.0:
                            self.memory_warning.emit(mem_usage)
                            gc.collect()

                    if processed % (self.chunk_size * 10) == 0:
                        gc.collect()

                del scan_data, x, y, z
                if has_colors:
                    del r, g, b
                gc.collect()

                self.log(f"  ✅ Скан {scan_idx + 1} обработан за {time.time() - scan_start:.2f}с")

            # Формируем результат
            self.log("🔧 Финальная обработка данных...")
            self.progress.emit(96)

            if not all_x:
                raise Exception("Не удалось прочитать точки")

            x_final = np.array(all_x, dtype=np.float32)
            y_final = np.array(all_y, dtype=np.float32)
            z_final = np.array(all_z, dtype=np.float32)

            colors = None
            if all_r and len(all_r) > 0:
                colors = np.column_stack((all_r, all_g, all_b))
                if colors.max() > 1.0:
                    colors = colors / 255.0

            count = len(x_final)

            del all_x, all_y, all_z
            if all_r:
                del all_r, all_g, all_b

            self.progress.emit(100)
            self.log(f"✅ E57 загружен: {count:,} точек")

            return x_final, y_final, z_final, colors, count

        except Exception as e:
            self.log(f"❌ Ошибка чтения E57: {str(e)}")
            raise

    def run(self):
        """Основной метод чтения"""
        self.start_time = time.time()
        self.log(f"🚀 Начало загрузки: {os.path.basename(self.file_path)}")
        self.log(f"📊 Параметры: шаг=1:{self.step}, чанк={self.chunk_size}, цвета={self.use_colors}")

        try:
            # Выбираем метод чтения в зависимости от расширения
            if self.file_ext in ['.las', '.laz']:
                if not LASPY_AVAILABLE:
                    self.error.emit("Библиотека laspy не установлена! Установите: pip install laspy")
                    return
                x, y, z, colors, count = self.read_las_chunked(self.file_path)
            elif self.file_ext == '.e57':
                if not E57_AVAILABLE:
                    self.error.emit("Библиотека pye57 не установлена! Установите: pip install pye57")
                    return
                x, y, z, colors, count = self.read_e57_chunked(self.file_path)
            else:
                self.error.emit(f"Неподдерживаемый формат: {self.file_ext}")
                return

            if x is None or len(x) == 0:
                self.error.emit("Не удалось прочитать точки")
                return

            self.log(f"📊 Итого точек: {count:,}")

            total_time = time.time() - self.start_time
            self.log(f"🎉 Загрузка завершена! Общее время: {total_time:.2f}с")

            self.finished.emit(x, y, z, colors, count)

        except Exception as e:
            self.log(f"❌ Ошибка: {str(e)}")
            self.error.emit(f"Ошибка: {str(e)}")
        finally:
            gc.collect()


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("E57/LAS Viewer - Оптимизированный просмотрщик")
        self.setGeometry(50, 50, 1400, 900)

        self.current_file = None
        self.points = None
        self.colors = None
        self.point_count = 0
        self.reader_thread = None
        self.is_loading = False
        self.plotter = None

        self.point_size = 1
        self.post_filter_step = 1
        self.current_visualization_points = None
        self.current_visualization_colors = None

        # Проверяем наличие библиотек
        if not E57_AVAILABLE and not LASPY_AVAILABLE:
            QMessageBox.critical(
                self,
                "Ошибка",
                "Ни одна библиотека для чтения не установлена!\n"
                "Установите: pip install pye57 laspy"
            )
            sys.exit(1)

        self.init_ui()
        self.setup_optimizations()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)

        control_panel = self.create_control_panel()
        main_layout.addLayout(control_panel)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumHeight(25)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Готов к работе | Выберите E57 или LAS файл")
        self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #f0f0f0; border: 1px solid #ccc; }")
        main_layout.addWidget(self.status_label)

        self.plotter = QtInteractor(self)
        self.plotter.set_background('white')
        main_layout.addWidget(self.plotter.interactor)

        self.create_menu()

    def create_control_panel(self):
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)

        # Параметры загрузки
        filter_group = QGroupBox("Параметры загрузки")
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        filter_layout.addWidget(QLabel("Шаг:"))
        self.step_spinbox = QSpinBox()
        self.step_spinbox.setRange(1, 100000)
        self.step_spinbox.setValue(100)
        self.step_spinbox.setMinimumWidth(80)
        filter_layout.addWidget(self.step_spinbox)

        filter_layout.addWidget(QLabel("Чанк:"))
        self.chunk_combo = QComboBox()
        self.chunk_combo.addItems(["10k", "25k", "50k", "100k", "250k"])
        self.chunk_combo.setCurrentText("50k")
        filter_layout.addWidget(self.chunk_combo)

        self.color_checkbox = QCheckBox("Цвета")
        self.color_checkbox.setChecked(True)
        filter_layout.addWidget(self.color_checkbox)

        filter_group.setLayout(filter_layout)
        control_layout.addWidget(filter_group)

        # Параметры визуализации
        vis_group = QGroupBox("Визуализация")
        vis_layout = QHBoxLayout()
        vis_layout.setSpacing(8)

        vis_layout.addWidget(QLabel("Размер:"))
        self.size_spinbox = QSpinBox()
        self.size_spinbox.setRange(1, 10)
        self.size_spinbox.setValue(1)
        self.size_spinbox.setMinimumWidth(60)
        vis_layout.addWidget(self.size_spinbox)

        vis_layout.addWidget(QLabel("Прореживание:"))
        self.post_filter_spinbox = QSpinBox()
        self.post_filter_spinbox.setRange(1, 1000)
        self.post_filter_spinbox.setValue(1)
        self.post_filter_spinbox.setMinimumWidth(80)
        vis_layout.addWidget(self.post_filter_spinbox)

        vis_group.setLayout(vis_layout)
        control_layout.addWidget(vis_group)

        # Кнопки
        btn_group = QGroupBox("Управление")
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.load_btn = QPushButton("📂 Загрузить")
        self.load_btn.setMinimumHeight(35)
        self.load_btn.clicked.connect(self.load_file)
        btn_layout.addWidget(self.load_btn)

        self.visualize_btn = QPushButton("👁️ Визуализировать")
        self.visualize_btn.clicked.connect(self.visualize_points)
        self.visualize_btn.setEnabled(False)
        btn_layout.addWidget(self.visualize_btn)

        self.clear_btn = QPushButton("🗑️ Очистить")
        self.clear_btn.clicked.connect(self.clear_scene)
        self.clear_btn.setEnabled(False)
        btn_layout.addWidget(self.clear_btn)

        btn_group.setLayout(btn_layout)
        control_layout.addWidget(btn_group)

        # Информация
        info_group = QGroupBox("Информация")
        info_layout = QHBoxLayout()

        self.info_label = QLabel("Точек: 0")
        self.info_label.setStyleSheet("QLabel { font-weight: bold; color: #0066cc; }")
        info_layout.addWidget(self.info_label)

        self.memory_label = QLabel("Память: 0 ГБ")
        self.memory_label.setStyleSheet("QLabel { font-weight: bold; color: #cc6600; }")
        info_layout.addWidget(self.memory_label)

        self.color_status = QLabel("Цвета: Нет")
        self.color_status.setStyleSheet("QLabel { font-weight: bold; color: #666666; }")
        info_layout.addWidget(self.color_status)

        info_group.setLayout(info_layout)
        control_layout.addWidget(info_group)

        return control_layout

    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&Файл")

        open_action = QAction("&Открыть E57/LAS...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.load_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("&Выход", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Меню Вид
        view_menu = menubar.addMenu("&Вид")
        reset_action = QAction("&Сбросить вид", self)
        reset_action.triggered.connect(self.reset_view)
        view_menu.addAction(reset_action)

    def reset_view(self):
        if self.plotter:
            self.plotter.camera_position = 'xy'
            self.plotter.render()
            self.status_label.setText("🔄 Вид сброшен")

    def setup_optimizations(self):
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["NUMEXPR_NUM_THREADS"] = "1"
        gc.set_threshold(500, 5, 5)

    def get_memory_usage(self):
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024**3)
        except:
            return 0

    def get_chunk_size(self):
        value = self.chunk_combo.currentText()
        if value.endswith('k'):
            return int(value[:-1]) * 1000
        return 50000

    def load_file(self):
        if self.is_loading:
            QMessageBox.warning(self, "Предупреждение", "Загрузка уже выполняется")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл облака точек",
            "",
            "Все поддерживаемые (*.e57 *.las *.laz);;E57 Files (*.e57);;LAS Files (*.las);;LAZ Files (*.laz)"
        )

        if not file_path:
            return

        try:
            file_size = os.path.getsize(file_path) / (1024**3)
            if file_size > 5:
                reply = QMessageBox.question(
                    self,
                    "Большой файл",
                    f"Размер файла: {file_size:.1f} ГБ\n\n"
                    f"Рекомендации:\n"
                    f"• Используйте шаг 100-1000\n"
                    f"• Размер чанка 10k-50k\n\n"
                    f"Продолжить?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        except:
            pass

        self.start_loading(file_path)

    def start_loading(self, file_path):
        self.current_file = file_path
        self.is_loading = True
        self.load_btn.setEnabled(False)
        self.visualize_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.clear_data()

        step = self.step_spinbox.value()
        chunk_size = self.get_chunk_size()
        use_colors = self.color_checkbox.isChecked()

        self.status_label.setText(f"Загрузка: {os.path.basename(file_path)}")

        self.reader_thread = PointCloudReader(file_path, step, chunk_size, use_colors)
        self.reader_thread.progress.connect(self.update_progress)
        self.reader_thread.finished.connect(self.on_loading_finished)
        self.reader_thread.error.connect(self.on_loading_error)
        self.reader_thread.memory_warning.connect(self.on_memory_warning)
        self.reader_thread.log_message.connect(self.on_log_message)
        self.reader_thread.start()

    def on_log_message(self, message):
        # Показываем только важные сообщения в статусе
        if not message.startswith("  "):
            self.status_label.setText(message)

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        if value % 10 == 0:
            mem = self.get_memory_usage()
            self.memory_label.setText(f"Память: {mem:.2f} ГБ")

    def on_memory_warning(self, mem_usage):
        self.status_label.setText(f"⚠️ Память: {mem_usage:.1f} ГБ, увеличьте шаг")
        self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #ffcccc; }")

    def on_loading_finished(self, x, y, z, colors, count):
        self.points = np.column_stack((x, y, z))
        self.colors = colors
        self.point_count = count

        if colors is not None:
            self.color_status.setText("Цвета: Есть ✅")
            self.color_status.setStyleSheet("QLabel { font-weight: bold; color: #00aa00; }")
        else:
            self.color_status.setText("Цвета: Нет ❌")
            self.color_status.setStyleSheet("QLabel { font-weight: bold; color: #ff0000; }")

        del x, y, z
        gc.collect()

        self.is_loading = False
        self.load_btn.setEnabled(True)
        self.visualize_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        self.update_info()
        self.visualize_points()

        self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #f0f0f0; border: 1px solid #ccc; }")

        mem = self.get_memory_usage()
        self.status_label.setText(f"✅ Загружено: {count:,} точек | Память: {mem:.2f} ГБ")
        gc.collect()

    def on_loading_error(self, error_msg):
        self.is_loading = False
        self.load_btn.setEnabled(True)
        self.visualize_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

        self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #ffcccc; }")
        self.status_label.setText(f"❌ Ошибка: {error_msg}")
        QMessageBox.critical(self, "Ошибка загрузки", error_msg)

        if self.reader_thread:
            self.reader_thread = None
        gc.collect()

    def visualize_points(self):
        if self.points is None or len(self.points) == 0:
            QMessageBox.warning(self, "Предупреждение", "Нет точек для визуализации")
            return

        try:
            point_size = self.size_spinbox.value()
            post_step = self.post_filter_spinbox.value()

            if post_step > 1:
                mask = np.arange(0, len(self.points), post_step)
                vis_points = self.points[mask]
                vis_colors = self.colors[mask] if self.colors is not None else None
            else:
                vis_points = self.points
                vis_colors = self.colors

            if vis_points is None or len(vis_points) == 0:
                QMessageBox.warning(self, "Предупреждение", "После фильтрации нет точек")
                return

            self.plotter.clear()
            points_mesh = pv.PolyData(vis_points)

            if vis_colors is not None and len(vis_colors) > 0:
                if vis_colors.max() > 1.0:
                    colors_norm = vis_colors / 255.0
                else:
                    colors_norm = vis_colors

                self.plotter.add_mesh(
                    points_mesh,
                    point_size=point_size,
                    rgb=True,
                    scalars=colors_norm,
                    render_points_as_spheres=False,
                    show_scalar_bar=False,
                    opacity=1.0
                )
            else:
                self.plotter.add_mesh(
                    points_mesh,
                    point_size=point_size,
                    color='blue',
                    render_points_as_spheres=False,
                    opacity=1.0
                )

            self.plotter.add_axes()
            try:
                self.plotter.show_grid()
            except:
                pass

            self.plotter.camera_position = 'xy'
            self.plotter.render()

            mem = self.get_memory_usage()
            self.status_label.setText(
                f"👁️ Визуализация: {len(vis_points):,} точек | "
                f"Размер: {point_size} | Память: {mem:.2f} ГБ"
            )

        except Exception as e:
            QMessageBox.critical(self, "Ошибка визуализации", str(e))

    def clear_scene(self):
        self.plotter.clear()
        self.plotter.render()
        self.clear_data()
        mem = self.get_memory_usage()
        self.status_label.setText(f"🗑️ Сцена очищена | Память: {mem:.2f} ГБ")

    def clear_data(self):
        if self.points is not None:
            del self.points
        if self.colors is not None:
            del self.colors
        self.points = None
        self.colors = None
        self.point_count = 0
        self.visualize_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.color_status.setText("Цвета: Нет")
        self.color_status.setStyleSheet("QLabel { font-weight: bold; color: #666666; }")
        self.update_info()
        gc.collect()

    def update_info(self):
        if self.point_count > 0:
            self.info_label.setText(f"Точек: {self.point_count:,}")
            mem = self.get_memory_usage()
            self.memory_label.setText(f"Память: {mem:.2f} ГБ")
        else:
            self.info_label.setText("Точек: 0")
            self.memory_label.setText("Память: 0 ГБ")

    def closeEvent(self, event):
        if self.reader_thread and self.reader_thread.isRunning():
            self.reader_thread.stop()
            self.reader_thread.wait()
        self.clear_data()
        if self.plotter:
            self.plotter.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
