import sys
import os
import traceback
import numpy as np
import laspy
import pyvista as pv
from pyvistaqt import QtInteractor
import vtk
import threading
from matplotlib.path import Path
from collections import defaultdict

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QGroupBox,
                             QScrollArea, QProgressBar, QTextEdit, QFileDialog, QMessageBox,
                             QSizePolicy, QColorDialog, QSplitter)
from PyQt6.QtCore import QTimer, Qt, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor


# ==============================================================================
# КЛАССЫ ДЛЯ ЛОГИРОВАНИЯ И ПОТОКОВ
# ==============================================================================

class WorkerSignals(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    warning = pyqtSignal(str)
    success = pyqtSignal(str)
    log = pyqtSignal(str, str)


class Logger:
    def __init__(self, signal_callback):
        self.signal_callback = signal_callback

    def log(self, message, level="INFO"):
        func_name = traceback.extract_stack()[-2].name
        full_msg = f"[{level}] {func_name}: {message}"
        self.signal_callback.emit(full_msg, level)


# ==============================================================================
# ОСНОВНОЙ КЛАСС ПРИЛОЖЕНИЯ
# ==============================================================================

class LASViewerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAS Viewer & Selector (PyQt6 Embedded)")
        self.setGeometry(100, 100, 1800, 950)

        # Переменные состояния
        self.filepath = None
        self.las_header = None
        self.total_points = 0
        self.all_points = None
        self.all_colors = None
        self.current_points = None
        self.current_colors = None

        self.polygons = []
        self.current_poly_verts = []
        self.selected_indices = None

        self.cloud_actor = None
        self.selected_actor = None
        self.polyline_actor = None
        self.poly_actors = []

        self.is_selecting = False
        self.is_processing = False

        self.new_z_value = None
        self.local_z_map = None

        # Кэши для ускорения
        self._cached_cell_size = None
        self._cached_grid_z_map = None

        # Сигналы и логгер
        self.signals = WorkerSignals()
        self.signals.progress.connect(self.update_progress)
        self.signals.error.connect(self.on_error)  # ДОБАВЛЕНО: обработчик ошибок
        self.signals.warning.connect(lambda w: (self.add_to_log(f"ВНИМАНИЕ: {w}", "WARNING"),
                                                QMessageBox.warning(self, "Внимание", w)))
        self.signals.success.connect(lambda s: (self.add_to_log(f"УСПЕХ: {s}", "INFO"),
                                                QMessageBox.information(self, "Успех", s)))
        self.signals.finished.connect(self.cleanup_after_processing)
        self.signals.log.connect(self.add_to_log)

        self.logger = Logger(self.signals.log)

        self.setup_ui()

        # Таймер для обработки событий VTK
        self.vtk_timer = QTimer(self)
        self.vtk_timer.timeout.connect(self.update_vtk_loop)
        self.vtk_timer.start(10)

        # Очистка начальных данных
        self.clear_all_data()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # === ВЕРХНЯЯ ПАНЕЛЬ С ПРОГРЕСС-БАРОМ ===
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(5)

        self.progress = QProgressBar()
        self.progress.setMaximumHeight(18)
        self.progress.hide()
        top_layout.addWidget(self.progress, stretch=1)

        self.progress_label = QLabel("")
        self.progress_label.hide()
        top_layout.addWidget(self.progress_label)

        main_layout.addWidget(top_panel)

        # === ОСНОВНОЙ КОНТЕНТ (левая панель + 3D + логи) ===
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(5)

        # Левая панель (скролл)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(350)
        scroll.setMinimumWidth(300)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        scroll_widget = QWidget()
        self.left_layout = QVBoxLayout(scroll_widget)
        self.left_layout.setSpacing(4)
        self.left_layout.setContentsMargins(4, 4, 4, 4)

        # Стиль для компактности групп
        group_style = """
            QGroupBox {
                font-weight: bold;
                margin-top: 6px;
                padding-top: 0px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px 0 5px;
            }
        """

        # --- Группа "Файл и статистика" ---
        grp_file = QGroupBox("Файл и статистика")
        grp_file.setStyleSheet(group_style)
        lay_file = QVBoxLayout(grp_file)
        lay_file.setSpacing(3)
        lay_file.setContentsMargins(6, 12, 6, 6)

        btn_sel = QPushButton("Выбрать LAS")
        btn_sel.setFixedHeight(24)
        btn_sel.clicked.connect(self.select_las_file)
        lay_file.addWidget(btn_sel)

        btn_bg = QPushButton("Цвет фона")
        btn_bg.setFixedHeight(24)
        btn_bg.clicked.connect(self.change_background)
        lay_file.addWidget(btn_bg)

        self.left_layout.addWidget(grp_file)

        # --- Группа "Плотность" ---
        grp_den = QGroupBox("Плотность отображения")
        grp_den.setStyleSheet(group_style)
        lay_den = QHBoxLayout(grp_den)
        lay_den.setSpacing(3)
        lay_den.setContentsMargins(6, 12, 6, 6)

        lay_den.addWidget(QLabel("Каждая:"))
        self.density_var = QLineEdit("1")
        self.density_var.setFixedWidth(40)
        self.density_var.setFixedHeight(22)
        lay_den.addWidget(self.density_var)
        lay_den.addWidget(QLabel("тчк"))

        self.load_btn = QPushButton("Загрузить")
        self.load_btn.setFixedHeight(24)
        self.load_btn.clicked.connect(self.start_loading_thread)
        lay_den.addWidget(self.load_btn)

        self.left_layout.addWidget(grp_den)

        # --- Группа "Проекция" ---
        grp_proj = QGroupBox("Проекция")
        grp_proj.setStyleSheet(group_style)
        lay_proj = QVBoxLayout(grp_proj)
        lay_proj.setSpacing(3)
        lay_proj.setContentsMargins(6, 12, 6, 6)

        h1 = QHBoxLayout()
        h1.setSpacing(3)
        for txt, cmd in [("Сверху", 'top'), ("Снизу", 'bottom')]:
            b = QPushButton(txt)
            b.setFixedHeight(22)
            b.clicked.connect(lambda _, c=cmd: self.set_view(c))
            h1.addWidget(b)

        h2 = QHBoxLayout()
        h2.setSpacing(3)
        for txt, cmd in [("Слева", 'left'), ("Справа", 'right')]:
            b = QPushButton(txt)
            b.setFixedHeight(22)
            b.clicked.connect(lambda _, c=cmd: self.set_view(c))
            h2.addWidget(b)

        lay_proj.addLayout(h1)
        lay_proj.addLayout(h2)

        btn_persp = QPushButton("Перспектива (3D)")
        btn_persp.setFixedHeight(24)
        btn_persp.clicked.connect(lambda: self.set_view('persp'))
        lay_proj.addWidget(btn_persp)

        self.left_layout.addWidget(grp_proj)

        # --- Группа "Выделение" ---
        grp_sel = QGroupBox("Выделение областей")
        grp_sel.setStyleSheet(group_style)
        lay_sel = QVBoxLayout(grp_sel)
        lay_sel.setSpacing(3)
        lay_sel.setContentsMargins(6, 12, 6, 6)

        self.select_btn = QPushButton("Начать выделение (ПКМ)")
        self.select_btn.setFixedHeight(24)
        self.select_btn.clicked.connect(self.toggle_selection)
        lay_sel.addWidget(self.select_btn)

        btn_save_poly = QPushButton("Сохранить полигон")
        btn_save_poly.setFixedHeight(24)
        btn_save_poly.clicked.connect(self.save_polygon)
        lay_sel.addWidget(btn_save_poly)

        btn_del_poly = QPushButton("Удалить последний")
        btn_del_poly.setFixedHeight(24)
        btn_del_poly.clicked.connect(self.delete_last_polygon)
        lay_sel.addWidget(btn_del_poly)

        btn_clear = QPushButton("Очистить всё")
        btn_clear.setFixedHeight(24)
        btn_clear.clicked.connect(self.clear_selection)
        lay_sel.addWidget(btn_clear)

        self.poly_count_label = QLabel("Полигонов: 0 | Точек: 0")
        self.poly_count_label.setWordWrap(True)
        lay_sel.addWidget(self.poly_count_label)

        self.left_layout.addWidget(grp_sel)

        # --- Группа "Изменение высоты" ---
        grp_z = QGroupBox("Изменение высоты (Z)")
        grp_z.setStyleSheet(group_style)
        lay_z = QVBoxLayout(grp_z)
        lay_z.setSpacing(3)
        lay_z.setContentsMargins(6, 12, 6, 6)

        h_z = QHBoxLayout()
        h_z.setSpacing(3)
        h_z.addWidget(QLabel("Единая Z:"))
        self.z_var = QLineEdit("")
        self.z_var.setFixedWidth(60)
        self.z_var.setFixedHeight(22)
        h_z.addWidget(self.z_var)
        h_z.addWidget(QLabel("(пусто=сброс)"))
        lay_z.addLayout(h_z)

        btn_apply_z = QPushButton("Применить Z")
        btn_apply_z.setFixedHeight(24)
        btn_apply_z.clicked.connect(self.apply_z_height)
        lay_z.addWidget(btn_apply_z)

        lay_z.addWidget(QLabel("--- Усечённая медиана по тайлам ---"))

        h_grid = QHBoxLayout()
        h_grid.setSpacing(3)
        h_grid.addWidget(QLabel("Тайл (м):"))
        self.grid_size_var = QLineEdit("5")
        self.grid_size_var.setFixedWidth(40)
        self.grid_size_var.setFixedHeight(22)
        h_grid.addWidget(self.grid_size_var)
        lay_z.addLayout(h_grid)

        h_trim = QHBoxLayout()
        h_trim.setSpacing(3)
        h_trim.addWidget(QLabel("Усеч. (%):"))
        self.trim_pct_var = QLineEdit("33")
        self.trim_pct_var.setFixedWidth(40)
        self.trim_pct_var.setFixedHeight(22)
        h_trim.addWidget(self.trim_pct_var)
        lay_z.addLayout(h_trim)

        h_diff = QHBoxLayout()
        h_diff.setSpacing(3)
        h_diff.addWidget(QLabel("Перепад (м):"))
        self.ground_diff_var = QLineEdit("1.5")
        self.ground_diff_var.setFixedWidth(40)
        self.ground_diff_var.setFixedHeight(22)
        h_diff.addWidget(self.ground_diff_var)
        h_diff.addWidget(QLabel("(опуск. крон)"))
        lay_z.addLayout(h_diff)

        h_neigh = QHBoxLayout()
        h_neigh.setSpacing(3)
        h_neigh.addWidget(QLabel("Соседи (тайлы):"))
        self.neigh_rad_var = QLineEdit("1")
        self.neigh_rad_var.setFixedWidth(40)
        self.neigh_rad_var.setFixedHeight(22)
        h_neigh.addWidget(self.neigh_rad_var)
        h_neigh.addWidget(QLabel("(1=3x3)"))
        lay_z.addLayout(h_neigh)

        btn_trim = QPushButton("Выровнять по тайлам и опустить кроны")
        btn_trim.setFixedHeight(24)
        btn_trim.clicked.connect(self.apply_trimmed_median_z)
        lay_z.addWidget(btn_trim)

        self.left_layout.addWidget(grp_z)

        # --- Группа "Экспорт" ---
        grp_exp = QGroupBox("Экспорт")
        grp_exp.setStyleSheet(group_style)
        lay_exp = QVBoxLayout(grp_exp)
        lay_exp.setSpacing(3)
        lay_exp.setContentsMargins(6, 12, 6, 6)

        btn_exp1 = QPushButton("Выделенные точки (быстро)")
        btn_exp1.setFixedHeight(24)
        btn_exp1.clicked.connect(self.open_export_dialog)
        lay_exp.addWidget(btn_exp1)

        btn_exp2 = QPushButton("Все точки (с изменённой Z)")
        btn_exp2.setFixedHeight(24)
        btn_exp2.clicked.connect(self.start_full_export_with_mod_thread)
        lay_exp.addWidget(btn_exp2)

        self.left_layout.addWidget(grp_exp)

        # --- Группа "Информация о файле" ---
        grp_info = QGroupBox("Информация о файле")
        grp_info.setStyleSheet(group_style)
        lay_info = QVBoxLayout(grp_info)
        lay_info.setSpacing(3)
        lay_info.setContentsMargins(6, 12, 6, 6)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(100)
        self.info_text.setStyleSheet("font-size: 11px;")
        lay_info.addWidget(self.info_text)

        self.left_layout.addWidget(grp_info)

        self.left_layout.addStretch()
        scroll.setWidget(scroll_widget)
        content_layout.addWidget(scroll)

        # === ЦЕНТРАЛЬНАЯ И ПРАВАЯ ПАНЕЛИ (3D + ЛОГИ) ===
        splitter_v = QSplitter(Qt.Orientation.Vertical)

        # 3D Окно
        self.frame_3d = QWidget()
        self.frame_3d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay_3d = QVBoxLayout(self.frame_3d)
        lay_3d.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self.frame_3d)
        self.plotter.set_background("black")
        lay_3d.addWidget(self.plotter.interactor)
        self.plotter.iren.interactor.AddObserver("RightButtonPressEvent", self.on_right_click)

        splitter_v.addWidget(self.frame_3d)

        # Панель логов
        log_group = QWidget()
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(0, 5, 0, 0)
        log_layout.setSpacing(2)

        log_label = QLabel("Лог выполнения:")
        log_label.setStyleSheet("font-weight: bold;")
        log_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        log_layout.addWidget(self.log_text)

        splitter_v.addWidget(log_group)
        splitter_v.setSizes([700, 150])

        content_layout.addWidget(splitter_v, stretch=1)

        main_layout.addWidget(content)

        # Прогресс-бар и лейбл уже добавлены в верхнюю панель
        # Скрываем их изначально
        self.progress.hide()
        self.progress_label.hide()

    # -------------------------------------------------------------------
    # ЛОГИРОВАНИЕ
    # -------------------------------------------------------------------

    def add_to_log(self, message, level="INFO"):
        colors = {
            "INFO": "#d4d4d4",
            "WARNING": "#dcdcaa",
            "ERROR": "#f44747",
            "DEBUG": "#569cd6"
        }
        color = colors.get(level, "#d4d4d4")
        self.log_text.append(f'<span style="color:{color};">{message}</span>')
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    # -------------------------------------------------------------------
    # УПРАВЛЕНИЕ ДАННЫМИ И ОЧИСТКА
    # -------------------------------------------------------------------

    def clear_all_data(self):
        """Полная очистка всех данных и акторов при загрузке нового файла"""
        # Сбрасываем флаг обработки, чтобы разрешить новую загрузку
        self.is_processing = False  # ДОБАВЛЕНО

        # Удаляем все акторы
        self.safe_remove_actor(self.cloud_actor)
        self.cloud_actor = None
        self.safe_remove_actor(self.selected_actor)
        self.selected_actor = None
        self.safe_remove_actor(self.polyline_actor)
        self.polyline_actor = None
        for actor in self.poly_actors:
            self.safe_remove_actor(actor)
        self.poly_actors.clear()
        self.plotter.remove_actor("temp_poly_verts")

        # Сбрасываем данные
        self.filepath = None
        self.las_header = None
        self.total_points = 0
        self.all_points = None
        self.all_colors = None
        self.current_points = None
        self.current_colors = None
        self.polygons.clear()
        self.current_poly_verts.clear()
        self.selected_indices = None
        self.new_z_value = None
        self.local_z_map = None
        self.is_selecting = False
        self.select_btn.setText("Начать выделение (ПКМ)")

        # Сбрасываем кэши
        self._cached_cell_size = None
        self._cached_grid_z_map = None

        self.info_text.clear()
        self.poly_count_label.setText("Полигонов: 0 | Точек: 0")
        self.z_var.clear()

        # Принудительно обновляем сцену
        self.plotter.render()  # ДОБАВЛЕНО

        self.add_to_log("Все данные очищены", "DEBUG")

    def safe_remove_actor(self, actor):
        if actor is not None:
            try:
                self.plotter.remove_actor(actor)
            except Exception:
                pass

    def update_vtk_loop(self):
        try:
            self.plotter.iren.process_events()
        except Exception:
            pass

    # -------------------------------------------------------------------
    # ВЫБОР ФАЙЛА И ЗАГРУЗКА
    # -------------------------------------------------------------------

    def select_las_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Выбрать LAS", "", "LAS Files (*.las);;All Files (*)")
        if not filepath:
            return

        # Очищаем все старые данные перед загрузкой нового файла
        self.clear_all_data()

        self.filepath = filepath
        try:
            with laspy.open(filepath) as f:
                self.las_header = f.header
                self.total_points = f.header.point_count
                min_b = np.array(f.header.mins)
                max_b = np.array(f.header.maxs)
                size = max_b - min_b
            self.info_text.setPlainText(
                f"Файл: {filepath.split('/')[-1]}\n"
                f"Всего точек: {self.total_points:,}\n"
                f"Размер X: {size[0]:.2f} м\n"
                f"Размер Y: {size[1]:.2f} м\n"
                f"Размер Z: {size[2]:.2f} м\n"
                f"Мин: {min_b[0]:.2f}, {min_b[1]:.2f}, {min_b[2]:.2f}\n"
                f"Макс: {max_b[0]:.2f}, {max_b[1]:.2f}, {max_b[2]:.2f}\n"
            )
            self.add_to_log(f"Выбран файл: {filepath.split('/')[-1]} ({self.total_points:,} точек)", "INFO")
        except Exception as e:
            self.add_to_log(f"Ошибка чтения заголовка: {e}", "ERROR")
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать заголовок:\n{e}")

    def start_loading_thread(self):
        if not self.filepath:
            QMessageBox.warning(self, "Внимание", "Сначала выберите файл LAS.")
            return
        if self.is_processing:
            return
        self.is_processing = True
        #self.load_btn.setEnabled(False)
        self.progress.show()
        self.progress_label.show()
        self.progress.setValue(0)
        self.add_to_log("Запуск потока загрузки точек...", "DEBUG")
        threading.Thread(target=self.load_points_chunked, daemon=True).start()

    def load_points_chunked(self):
        try:
            step = max(1, int(self.density_var.text()))
            points_list, colors_list, chunk_size, processed = [], [], 1_000_000, 0
            self.signals.log.emit(f"Параметры: шаг={step}, размер чанка={chunk_size:,}", "DEBUG")

            with laspy.open(self.filepath) as f:
                for chunk in f.chunk_iterator(chunk_size):
                    num_pts = len(chunk.x)
                    if num_pts == 0:
                        continue
                    start_idx = (step - (processed % step)) % step
                    local_indices = np.arange(start_idx, num_pts, step)

                    pts_chunk = np.vstack((
                        chunk.x[local_indices],
                        chunk.y[local_indices],
                        chunk.z[local_indices]
                    )).transpose()
                    points_list.append(pts_chunk)

                    if 'red' in chunk.point_format.dimension_names:
                        r, g, b = chunk.red[local_indices], chunk.green[local_indices], chunk.blue[local_indices]
                        max_val = max(np.max(r), np.max(g), np.max(b)) if len(r) > 0 else 255
                        colors_list.append(np.vstack((r, g, b)).transpose() / (255.0 if max_val <= 255 else 65535.0))

                    processed += num_pts
                    percent = min(100.0, (processed / self.total_points) * 100)
                    self.signals.progress.emit(int(percent), f"Загрузка... {processed:,} / {self.total_points:,}")

            if not points_list:
                self.signals.warning.emit("Нет точек для отображения.")
                return

            self.all_points = np.vstack(points_list)
            valid_colors = [c for c in colors_list if len(c) > 0]
            self.all_colors = np.vstack(valid_colors) if valid_colors else None

            self.current_points = self.all_points
            self.current_colors = self.all_colors

            self.signals.log.emit(f"Загружено в память: {len(self.current_points):,} точек", "INFO")
            self.signals.finished.emit()

        except Exception as e:
            err_msg = f"Ошибка в load_points_chunked: {str(e)}"
            self.signals.log.emit(err_msg, "ERROR")
            self.signals.error.emit(err_msg)

    def cleanup_after_processing(self):
        self.is_processing = False
        #self.load_btn.setEnabled(True)
        self.progress.hide()
        self.progress_label.hide()
        if self.current_points is not None and self.cloud_actor is None:
            self.plot_cloud()
        self.plotter.render()  # ДОБАВЛЕНО для принудительного обновления

    def on_error(self, msg):  # ДОБАВЛЕННЫЙ ОБРАБОТЧИК
        self.is_processing = False
        self.progress.hide()
        self.progress_label.hide()
        self.add_to_log(f"ОШИБКА: {msg}", "ERROR")
        QMessageBox.critical(self, "Ошибка", msg)

    def update_progress(self, percent, text):
        self.progress.setValue(percent)
        self.progress_label.setText(text)

    def change_background(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.plotter.set_background(color.name())
            self.plotter.update()

    def plot_cloud(self):
        self.safe_remove_actor(self.cloud_actor)
        self.cloud_actor = None

        pc = pv.PolyData(self.current_points)
        if self.current_colors is not None:
            pc['RGB'] = self.current_colors
            self.cloud_actor = self.plotter.add_mesh(
                pc, scalars='RGB', rgb=True, point_size=2, render_points_as_spheres=False, reset_camera=False
            )
        else:
            self.cloud_actor = self.plotter.add_mesh(
                pc, point_size=2, color="white", render_points_as_spheres=False, reset_camera=False
            )
        self.plotter.reset_camera()
        self.plotter.render()  # ДОБАВЛЕНО
        self.add_to_log("Облако точек отрисовано", "DEBUG")

    def set_view(self, view_type):
        views = {
            'top': (self.plotter.view_xy, []),
            'bottom': (self.plotter.view_xy, [True]),
            'left': (self.plotter.view_yz, []),
            'right': (self.plotter.view_yz, [True]),
            'persp': (self.plotter.reset_camera, [])
        }
        if view_type in views:
            views[view_type][0](*views[view_type][1])

    # -------------------------------------------------------------------
    # ВЫДЕЛЕНИЕ
    # -------------------------------------------------------------------

    def toggle_selection(self):
        self.is_selecting = not self.is_selecting
        if self.is_selecting:
            self.select_btn.setText("Режим выделения ВКЛ")
            self.current_poly_verts.clear()
            self.safe_remove_actor(self.polyline_actor)
            self.polyline_actor = None
            self.plotter.remove_actor("temp_poly_verts")
            self.add_to_log("Режим выделения включен", "DEBUG")
        else:
            self.select_btn.setText("Начать выделение (ПКМ)")

    def on_right_click(self, obj, event):
        if not self.is_selecting or self.current_points is None:
            return

        click_pos = self.plotter.iren.interactor.GetEventPosition()

        picker = vtk.vtkCellPicker()
        picker.Pick(click_pos[0], click_pos[1], 0, self.plotter.renderer)

        pick_pos = None
        if picker.GetPickPosition() != (0.0, 0.0, 0.0):
            pick_pos = np.array(picker.GetPickPosition())
        else:
            pick_pos = self._get_closest_point_to_click(click_pos)

        if pick_pos is not None:
            self.current_poly_verts.append(pick_pos)
            self.add_to_log(f"Добавлена вершина: X={pick_pos[0]:.2f}, Y={pick_pos[1]:.2f}, Z={pick_pos[2]:.2f}", "DEBUG")
            self.draw_temp_polyline()

    def _get_closest_point_to_click(self, click_screen_pos):
        try:
            renderer = self.plotter.renderer
            cam = renderer.GetActiveCamera()
            transform = vtk.vtkTransform()
            transform.SetMatrix(cam.GetCompositeProjectionTransformMatrix(
                renderer.GetTiledAspectRatio(), 0, 1
            ))

            bounds = self.current_points.min(axis=0), self.current_points.max(axis=0)
            corners = np.array([
                [bounds[0][0], bounds[0][1], bounds[0][2]],
                [bounds[1][0], bounds[0][1], bounds[0][2]],
                [bounds[0][0], bounds[1][1], bounds[0][2]],
                [bounds[0][0], bounds[0][1], bounds[1][2]]
            ])

            screen_corners = np.zeros((len(corners), 3))
            for i, pt in enumerate(corners):
                transform.TransformPoint(pt, screen_corners[i])

            min_sx, max_sx = screen_corners[:, 0].min(), screen_corners[:, 0].max()
            min_sy, max_sy = screen_corners[:, 1].min(), screen_corners[:, 1].max()

            margin = 100
            if not (min_sx - margin < click_screen_pos[0] < max_sx + margin and
                    min_sy - margin < click_screen_pos[1] < max_sy + margin):
                return None

            num_points = len(self.current_points)
            sample_size = min(50000, num_points)
            indices = np.random.choice(num_points, sample_size, replace=False)
            pts_3d = self.current_points[indices]

            screen_pts = np.zeros((len(pts_3d), 3))
            for i, pt in enumerate(pts_3d):
                transform.TransformPoint(pt, screen_pts[i])

            dx = screen_pts[:, 0] - click_screen_pos[0]
            dy = screen_pts[:, 1] - click_screen_pos[1]
            distances_sq = dx**2 + dy**2
            closest_sample_idx = np.argmin(distances_sq)

            if np.sqrt(distances_sq[closest_sample_idx]) > 500:
                return None

            return pts_3d[closest_sample_idx]

        except Exception as e:
            self.add_to_log(f"Ошибка поиска ближайшей точки: {e}", "WARNING")
            return None

    def draw_temp_polyline(self):
        if len(self.current_poly_verts) < 1:
            return
        self.plotter.remove_actor("temp_poly_verts")
        pts = np.array(self.current_poly_verts)
        self.safe_remove_actor(self.polyline_actor)
        self.polyline_actor = None

        if len(pts) >= 2:
            lines = np.full((len(pts)-1, 3), 2, dtype=np.int64)
            lines[:, 1] = np.arange(len(pts)-1)
            lines[:, 2] = np.arange(1, len(pts))
            self.polyline_actor = self.plotter.add_mesh(
                pv.PolyData(pts, lines=lines), color="yellow", line_width=3, reset_camera=False
            )
        self.plotter.add_mesh(
            pv.PolyData(pts), color="red", point_size=8,
            name="temp_poly_verts", reset_camera=False
        )

    def save_polygon(self):
        if len(self.current_poly_verts) < 3:
            QMessageBox.warning(self, "Ошибка", "Нужно минимум 3 точки.")
            return
        self.is_selecting = False
        self.select_btn.setText("Начать выделение (ПКМ)")
        pts = np.array(self.current_poly_verts)
        min_axis = np.argmin(np.var(pts, axis=0))
        mask = [i for i in range(3) if i != min_axis]
        self.polygons.append({'path': Path(pts[:, mask]), 'mask': mask, 'verts': pts})

        closed_pts = np.vstack([pts, pts[0:1]])
        lines = np.full((len(closed_pts)-1, 3), 2, dtype=np.int64)
        lines[:, 1] = np.arange(len(closed_pts)-1)
        lines[:, 2] = np.arange(1, len(closed_pts))
        self.poly_actors.append(
            self.plotter.add_mesh(pv.PolyData(closed_pts, lines=lines), color="cyan", line_width=2, reset_camera=False)
        )

        self.safe_remove_actor(self.polyline_actor)
        self.polyline_actor = None
        self.plotter.remove_actor("temp_poly_verts")
        self.current_poly_verts.clear()
        self.add_to_log(f"Полигон сохранен. Всего полигонов: {len(self.polygons)}", "INFO")
        self.recalculate_selected_points()

    def delete_last_polygon(self):
        if not self.polygons:
            return
        self.polygons.pop()
        if self.poly_actors:
            self.safe_remove_actor(self.poly_actors.pop())
        self.recalculate_selected_points()

    def recalculate_selected_points(self):
        if not self.polygons or self.current_points is None:
            self.selected_indices = np.array([], dtype=int)
            self.safe_remove_actor(self.selected_actor)
            self.selected_actor = None
            self.update_selection_info()
            return

        # Оптимизация: объединяем маски через OR для всех полигонов
        inside_total = np.zeros(len(self.current_points), dtype=bool)
        for poly in self.polygons:
            inside_total |= poly['path'].contains_points(self.current_points[:, poly['mask']])
        self.selected_indices = np.where(inside_total)[0]
        self.add_to_log(f"Пересчет выделения: найдено {len(self.selected_indices)} точек", "DEBUG")
        self.update_selected_visuals()
        self.update_selection_info()

    def update_selection_info(self):
        count = len(self.selected_indices) if self.selected_indices is not None else 0
        z_info = " | Z: ступенчатый" if self.local_z_map is not None else (
            f" | Z = {self.new_z_value}" if self.new_z_value is not None else ""
        )
        self.poly_count_label.setText(f"Полигонов: {len(self.polygons)} | Точек: {count}{z_info}")

    def update_selected_visuals(self):
        self.safe_remove_actor(self.selected_actor)
        self.selected_actor = None
        if self.selected_indices is not None and len(self.selected_indices) > 0:
            pts_to_show = self.current_points[self.selected_indices].copy()
            if self.local_z_map is not None:
                pts_to_show[:, 2] = self.local_z_map
            elif self.new_z_value is not None:
                pts_to_show[:, 2] = self.new_z_value
            self.selected_actor = self.plotter.add_mesh(
                pv.PolyData(pts_to_show), color="lime", point_size=4, reset_camera=False
            )

    # -------------------------------------------------------------------
    # ИЗМЕНЕНИЕ ВЫСОТЫ (ускоренная версия)
    # -------------------------------------------------------------------

    def apply_trimmed_median_z(self):
        if self.selected_indices is None or len(self.selected_indices) == 0:
            QMessageBox.warning(self, "Внимание", "Нет выделенных точек.")
            return

        try:
            grid_size = float(self.grid_size_var.text())
            if grid_size <= 0:
                raise ValueError
            percentile = float(self.trim_pct_var.text())
            if percentile < 0 or percentile > 50:
                raise ValueError("Процентиль должен быть от 0 до 50%")
            max_height_diff = float(self.ground_diff_var.text())
        except ValueError as e:
            QMessageBox.critical(self, "Ошибка", f"Введите корректные числа: {str(e)}")
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        pts = self.current_points[self.selected_indices]

        # Быстрая группировка по ячейкам с помощью словаря
        cell_x = (pts[:, 0] / grid_size).astype(int)
        cell_y = (pts[:, 1] / grid_size).astype(int)
        tiles_dict = defaultdict(list)
        for i, z in enumerate(pts[:, 2]):
            tiles_dict[(cell_x[i], cell_y[i])].append(z)

        tile_ground = {}
        for key, z_list in tiles_dict.items():
            z_array = np.sort(z_list)
            idx = int(len(z_array) * (percentile / 100.0))
            if idx < 1:
                idx = 1
            if idx > len(z_array):
                idx = len(z_array)
            ground_z = np.mean(z_array[:idx])
            if len(z_array) > 5:
                height_range = z_array[-1] - z_array[0]
                if height_range > max_height_diff * 2:
                    ground_z = z_array[0]
            tile_ground[key] = ground_z

        # ИСПРАВЛЕННАЯ интерполяция пропущенных ячеек
        final_tile_z = tile_ground.copy()
        for key, z in tile_ground.items():
            cx, cy = key
            neighbor_heights = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    n_key = (cx + dx, cy + dy)
                    if n_key in tile_ground:
                        neighbor_heights.append(tile_ground[n_key])

            # ИСПРАВЛЕНО: проверяем что есть хотя бы 3 соседа
            if len(neighbor_heights) >= 3:
                # Усредняем с соседями, с большим весом собственного значения
                final_tile_z[key] = (z * 2 + np.mean(neighbor_heights)) / 3
            elif len(neighbor_heights) >= 1:
                # Если мало соседей - просто усредняем с ними
                final_tile_z[key] = (z + np.mean(neighbor_heights)) / 2
            # иначе оставляем как есть

        tile_ground = final_tile_z

        # Применение высот
        z_vals = np.zeros(len(pts))
        for i, pt in enumerate(pts):
            key = (cell_x[i], cell_y[i])
            if key in tile_ground:
                z_vals[i] = tile_ground[key]
            else:
                # Поиск ближайшей ячейки
                min_dist = float('inf')
                nearest_z = pt[2]
                for k, z in tile_ground.items():
                    dist = abs(k[0] - key[0]) + abs(k[1] - key[1])
                    if dist < min_dist:
                        min_dist = dist
                        nearest_z = z
                z_vals[i] = nearest_z

        self.local_z_map = z_vals
        self.new_z_value = None
        self.z_var.setText("")
        self.update_selected_visuals()
        self.update_selection_info()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def apply_z_height(self):
        val = self.z_var.text().strip()
        if val == "":
            self.new_z_value = None
        else:
            try:
                self.new_z_value = float(val)
            except ValueError:
                QMessageBox.critical(self, "Ошибка", "Введите корректное число.")
                return
        self.local_z_map = None
        self.update_selected_visuals()
        self.update_selection_info()

    def clear_selection(self):
        self.polygons.clear()
        self.current_poly_verts.clear()
        self.selected_indices = None
        self.new_z_value = None
        self.local_z_map = None
        self.z_var.setText("")
        self.safe_remove_actor(self.polyline_actor)
        self.polyline_actor = None
        self.safe_remove_actor(self.selected_actor)
        self.selected_actor = None
        self.plotter.remove_actor("temp_poly_verts")
        for actor in self.poly_actors:
            self.safe_remove_actor(actor)
        self.poly_actors.clear()
        self.update_selection_info()

    # -------------------------------------------------------------------
    # ЭКСПОРТ
    # -------------------------------------------------------------------

    def open_export_dialog(self):
        if not self.polygons:
            QMessageBox.warning(self, "Ошибка", "Нет сохраненных областей.")
            return
        reply = QMessageBox.question(
            self, "Тип экспорта",
            "Нажмите 'Yes' для Быстрого (экран),\n'No' для Полного (из исходника).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        mode = 1 if reply == QMessageBox.StandardButton.Yes else 2
        self.start_export(mode)

    def start_export(self, mode):
        filepath, _ = QFileDialog.getSaveFileName(self, "Сохранить LAS", "", "LAS Files (*.las)")
        if not filepath:
            return
        if mode == 1:
            self.export_decimated(filepath)
        else:
            self.start_full_export_thread(filepath)

    def export_decimated(self, filepath):
        if self.selected_indices is None or len(self.selected_indices) == 0:
            return
        try:
            pts = self.current_points[self.selected_indices].copy()
            if self.local_z_map is not None:
                pts[:, 2] = self.local_z_map
            elif self.new_z_value is not None:
                pts[:, 2] = self.new_z_value
            header = laspy.LasHeader(point_format=3, version="1.2")
            header.scales = np.array([0.01, 0.01, 0.01])
            header.offsets = np.min(pts, axis=0)
            las = laspy.LasData(header)
            las.x, las.y, las.z = pts[:, 0], pts[:, 1], pts[:, 2]
            las.write(filepath)
            QMessageBox.information(self, "Успех", f"Экспорт завершен ({len(pts)} точек)")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def start_full_export_thread(self, filepath):
        if self.is_processing:
            return
        self.is_processing = True
        #self.load_btn.setEnabled(False)
        self.progress.show()
        self.progress_label.show()
        self.progress.setValue(0)
        threading.Thread(target=self.export_full_chunked, args=(filepath,), daemon=True).start()

    def export_full_chunked(self, filepath):
        try:
            has_z_mod = self.local_z_map is not None or self.new_z_value is not None
            if not has_z_mod and not self.polygons:
                self.signals.warning.emit("Нет изменений для экспорта.")
                return

            mask = self.polygons[0]['mask']
            paths = [p['path'] for p in self.polygons]
            chunk_size = 1_000_000
            processed = 0
            total_exported = 0

            # Предварительно строим сетку высот для быстрого доступа
            grid_z_map = None
            if self.local_z_map is not None:
                grid_z_map = defaultdict(list)
                sel_pts = self.current_points[self.selected_indices]
                cell_size = float(self.grid_size_var.text()) if self.grid_size_var.text() else 5.0
                for i, pt in enumerate(sel_pts):
                    key = (int(pt[0] // cell_size), int(pt[1] // cell_size))
                    grid_z_map[key].append((pt[0], pt[1], self.local_z_map[i]))

            with laspy.open(self.filepath) as f_in:
                with laspy.open(filepath, mode='w', header=f_in.header) as f_out:
                    for chunk in f_in.chunk_iterator(chunk_size):
                        num_pts = len(chunk.x)
                        if num_pts == 0:
                            continue

                        chunk_pts = np.vstack((chunk.x, chunk.y, chunk.z)).transpose()
                        chunk_2d = chunk_pts[:, mask]
                        inside = np.any([path.contains_points(chunk_2d) for path in paths], axis=0)

                        if np.any(inside):
                            # В export_full_chunked() и export_all_with_z_mod():
                            if self.local_z_map is not None and grid_z_map is not None:
                                cell_size = float(self.grid_size_var.text()) if self.grid_size_var.text() else 5.0
                                inside_indices = np.where(inside)[0]
                                new_z = chunk.z.copy()

                                # Предварительно кэшируем ячейки для ускорения
                                for idx in inside_indices:
                                    pt = chunk_pts[idx]
                                    key = (int(pt[0] // cell_size), int(pt[1] // cell_size))

                                    if key in grid_z_map:
                                        # Быстрый поиск ближайшей точки в ячейке
                                        cell_points = grid_z_map[key]
                                        # Оптимизация: если в ячейке одна точка - сразу берем её
                                        if len(cell_points) == 1:
                                            new_z[idx] = cell_points[0][2]
                                        else:
                                            # Ищем ближайшую
                                            best_dist = float('inf')
                                            best_z = pt[2]
                                            for gx, gy, gz in cell_points:
                                                d = (pt[0]-gx)**2 + (pt[1]-gy)**2
                                                if d < best_dist:
                                                    best_dist = d
                                                    best_z = gz
                                            new_z[idx] = best_z
                                    else:
                                        # ИСПРАВЛЕНО: если ячейки нет в карте, ищем ближайшую ячейку
                                        min_dist = float('inf')
                                        nearest_z = pt[2]
                                        # Проверяем только соседние ячейки для скорости
                                        for dx in (-1, 0, 1):
                                            for dy in (-1, 0, 1):
                                                search_key = (key[0] + dx, key[1] + dy)
                                                if search_key in grid_z_map:
                                                    # Берем первую точку из найденной ячейки как приближение
                                                    nearest_z = grid_z_map[search_key][0][2]
                                                    break
                                            if nearest_z != pt[2]:
                                                break
                                        new_z[idx] = nearest_z
                                chunk.z = new_z
                            elif self.new_z_value is not None:
                                chunk.z[inside] = self.new_z_value

                            f_out.write_points(chunk[inside])
                            total_exported += np.sum(inside)

                        processed += num_pts
                        percent = min(100.0, (processed / self.total_points) * 100)
                        self.signals.progress.emit(int(percent), f"Фильтрация... {processed:,} / {self.total_points:,}")

            self.signals.success.emit(f"Экспорт завершен ({total_exported:,} точек)")
        except Exception as e:
            self.signals.error.emit(str(e))

    def start_full_export_with_mod_thread(self):
        if not self.filepath:
            QMessageBox.warning(self, "Внимание", "Сначала выберите файл LAS.")
            return
        if self.is_processing:
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "Сохранить LAS", "", "LAS Files (*.las)")
        if not filepath:
            return

        has_mod = self.new_z_value is not None or self.local_z_map is not None
        if not has_mod and not self.polygons:
            QMessageBox.warning(self, "Внимание", "Нет изменений и нет полигонов. Экспорт бессмысленен.")
            return

        if not has_mod:
            reply = QMessageBox.question(
                self, "Внимание",
                "Z не задана. Сохранить все точки без изменений высоты?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.is_processing = True
        #self.load_btn.setEnabled(False)
        self.progress.show()
        self.progress_label.show()
        self.progress.setValue(0)
        threading.Thread(target=self.export_all_with_z_mod, args=(filepath,), daemon=True).start()

    def export_all_with_z_mod(self, filepath):
        try:
            has_polygons = len(self.polygons) > 0
            mask = self.polygons[0]['mask'] if has_polygons else None
            paths = [p['path'] for p in self.polygons] if has_polygons else []

            self.signals.log.emit("Начало полного экспорта всех точек...", "INFO")

            # Подготовка пространственной карты высот
            grid_z_map = None
            if self.local_z_map is not None and has_polygons:
                self.signals.log.emit("Построение пространственной сетки высот (Z-карты)...", "DEBUG")
                grid_z_map = defaultdict(list)
                sel_pts = self.current_points[self.selected_indices]
                cell_size = float(self.grid_size_var.text()) if self.grid_size_var.text() else 5.0
                for i, pt in enumerate(sel_pts):
                    key = (int(pt[0] // cell_size), int(pt[1] // cell_size))
                    grid_z_map[key].append((pt[0], pt[1], self.local_z_map[i]))
                self.signals.log.emit(f"Сетка высот построена. Ячеек: {len(grid_z_map):,}", "DEBUG")

            WRITE_BUFFER_LIMIT = 5_000_000
            READ_CHUNK_SIZE = 1_000_000

            processed = 0
            total_written = 0
            buffer_points = []

            with laspy.open(self.filepath) as f_in:
                header = f_in.header
                with laspy.open(filepath, mode='w', header=header) as f_out:

                    for chunk in f_in.chunk_iterator(READ_CHUNK_SIZE):
                        num_pts = len(chunk.x)
                        if num_pts == 0:
                            continue

                        if has_polygons and (self.new_z_value is not None or self.local_z_map is not None):
                            chunk_pts = np.vstack((chunk.x, chunk.y, chunk.z)).transpose()
                            chunk_2d = chunk_pts[:, mask]
                            inside = np.any([path.contains_points(chunk_2d) for path in paths], axis=0)

                            if np.any(inside):
                                inside_count = np.sum(inside)
                                self.signals.log.emit(
                                    f"Чанк {processed//READ_CHUNK_SIZE + 1}: найдено {inside_count:,} точек в области.",
                                    "INFO"
                                )

                                # В export_full_chunked() и export_all_with_z_mod():
                                if self.local_z_map is not None and grid_z_map is not None:
                                    cell_size = float(self.grid_size_var.text()) if self.grid_size_var.text() else 5.0
                                    inside_indices = np.where(inside)[0]
                                    new_z = chunk.z.copy()

                                    # Предварительно кэшируем ячейки для ускорения
                                    for idx in inside_indices:
                                        pt = chunk_pts[idx]
                                        key = (int(pt[0] // cell_size), int(pt[1] // cell_size))

                                        if key in grid_z_map:
                                            # Быстрый поиск ближайшей точки в ячейке
                                            cell_points = grid_z_map[key]
                                            # Оптимизация: если в ячейке одна точка - сразу берем её
                                            if len(cell_points) == 1:
                                                new_z[idx] = cell_points[0][2]
                                            else:
                                                # Ищем ближайшую
                                                best_dist = float('inf')
                                                best_z = pt[2]
                                                for gx, gy, gz in cell_points:
                                                    d = (pt[0]-gx)**2 + (pt[1]-gy)**2
                                                    if d < best_dist:
                                                        best_dist = d
                                                        best_z = gz
                                                new_z[idx] = best_z
                                        else:
                                            # ИСПРАВЛЕНО: если ячейки нет в карте, ищем ближайшую ячейку
                                            min_dist = float('inf')
                                            nearest_z = pt[2]
                                            # Проверяем только соседние ячейки для скорости
                                            for dx in (-1, 0, 1):
                                                for dy in (-1, 0, 1):
                                                    search_key = (key[0] + dx, key[1] + dy)
                                                    if search_key in grid_z_map:
                                                        # Берем первую точку из найденной ячейки как приближение
                                                        nearest_z = grid_z_map[search_key][0][2]
                                                        break
                                                if nearest_z != pt[2]:
                                                    break
                                            new_z[idx] = nearest_z
                                    chunk.z = new_z
                                elif self.new_z_value is not None:
                                    chunk.z[inside] = self.new_z_value

                        # Буферизация
                        buffer_points.append(chunk)
                        total_in_buffer = sum(len(p.x) for p in buffer_points)

                        if total_in_buffer >= WRITE_BUFFER_LIMIT:
                            for buf_chunk in buffer_points:
                                f_out.write_points(buf_chunk)
                                total_written += len(buf_chunk)
                            buffer_points.clear()
                            self.signals.log.emit(f"Буфер сброшен на диск. Записано: {total_written:,} / {self.total_points:,}", "DEBUG")

                        processed += num_pts
                        percent = min(100.0, (processed / self.total_points) * 100)
                        self.signals.progress.emit(int(percent), f"Обработка... {processed:,} / {self.total_points:,}")

                    # Остаток буфера
                    if buffer_points:
                        for buf_chunk in buffer_points:
                            f_out.write_points(buf_chunk)
                            total_written += len(buf_chunk)
                        self.signals.log.emit("Финальный буфер сброшен на диск.", "DEBUG")

            self.signals.log.emit(f"Экспорт успешно завершен. Всего записано: {total_written:,} точек.", "INFO")
            self.signals.success.emit(f"Полный экспорт завершен ({total_written:,} точек)")

        except Exception as e:
            err_trace = traceback.format_exc()
            self.signals.log.emit(f"КРИТИЧЕСКАЯ ОШИБКА В ПОТОКЕ ЭКСПОРТА:\n{err_trace}", "ERROR")
            self.signals.error.emit(f"Ошибка экспорта (см. лог):\n{str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LASViewerApp()
    window.show()
    sys.exit(app.exec())
