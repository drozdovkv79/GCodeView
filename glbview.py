import sys
import os
import numpy as np
import trimesh
import pyvista as pv
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QPushButton, QLabel, QFileDialog,
                            QStatusBar, QFrame, QMessageBox, QProgressDialog,
                            QTextEdit, QSplitter, QComboBox, QCheckBox,
                            QSpinBox, QGroupBox)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QDateTime
from PyQt6.QtGui import QFont, QPalette, QColor
from pyvistaqt import QtInteractor
import logging
import time
from datetime import datetime

# Настройка логирования
class LogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.append(msg)
        self.text_widget.ensureCursorVisible()

# Класс для загрузки в отдельном потоке
class LoaderThread(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, file_path, optimize=True, target_vertices=None):
        super().__init__()
        self.file_path = file_path
        self.optimize = optimize
        self.target_vertices = target_vertices

    def run(self):
        try:
            self.status.emit(f"Начало загрузки: {os.path.basename(self.file_path)}")
            self.progress.emit(10)

            self.status.emit("Загрузка PLY файла...")
            self.progress.emit(20)

            start_time = time.time()

            mesh = None

            # Метод 1: Стандартная загрузка через trimesh
            try:
                self.status.emit("Попытка загрузки через trimesh...")
                mesh = trimesh.load(
                    self.file_path,
                    force='mesh',
                    process=True,
                    validate=True
                )
            except Exception as e:
                self.status.emit(f"Метод 1 не удался: {str(e)[:100]}")

            # Метод 2: Загрузка через pyvista напрямую
            if mesh is None:
                try:
                    self.status.emit("Попытка загрузки через pyvista...")
                    pv_mesh = pv.read(self.file_path)

                    vertices = np.array(pv_mesh.points)
                    faces = np.array(pv_mesh.faces)

                    if len(faces) > 0:
                        face_list = []
                        i = 0
                        while i < len(faces):
                            n_points = faces[i]
                            if n_points == 3:
                                face_list.append(faces[i+1:i+4])
                            i += n_points + 1

                        if face_list:
                            faces_array = np.array(face_list)
                            mesh = trimesh.Trimesh(vertices=vertices, faces=faces_array)
                        else:
                            mesh = trimesh.Trimesh(vertices=vertices)
                    else:
                        mesh = trimesh.Trimesh(vertices=vertices)

                except Exception as e:
                    self.status.emit(f"Метод 2 не удался: {str(e)[:100]}")

            # Метод 3: Загрузка через numpy (ручной парсинг)
            if mesh is None:
                try:
                    self.status.emit("Попытка ручного парсинга PLY...")
                    mesh = self.parse_ply_manual(self.file_path)
                except Exception as e:
                    self.status.emit(f"Метод 3 не удался: {str(e)[:100]}")

            if mesh is None:
                raise Exception("Не удалось загрузить PLY файл ни одним методом")

            self.progress.emit(50)
            load_time = time.time() - start_time
            self.status.emit(f"Файл загружен за {load_time:.2f} сек")

            self.status.emit("Обработка геометрии...")
            self.progress.emit(60)

            if isinstance(mesh, trimesh.Scene):
                self.status.emit("Обнаружена сцена, объединение геометрий...")
                try:
                    meshes = []
                    total_vertices = 0
                    max_vertices = 2000000

                    for name, geom in mesh.geometry.items():
                        if isinstance(geom, trimesh.Trimesh):
                            if len(geom.vertices) + total_vertices < max_vertices:
                                meshes.append(geom)
                                total_vertices += len(geom.vertices)

                    if meshes:
                        if len(meshes) > 1:
                            self.status.emit(f"Объединение {len(meshes)} объектов...")
                            mesh_combined = trimesh.util.concatenate(meshes)
                        else:
                            mesh_combined = meshes[0]
                    else:
                        mesh_combined = mesh.dump(concatenate=True)

                except Exception as e:
                    self.status.emit(f"Ошибка объединения: {str(e)}")
                    mesh_combined = mesh.dump(concatenate=True)

            elif isinstance(mesh, trimesh.Trimesh):
                self.status.emit("Загружена отдельная модель")
                mesh_combined = mesh
            else:
                raise Exception(f"Неподдерживаемый тип: {type(mesh)}")

            original_vertices = len(mesh_combined.vertices)
            original_faces = len(mesh_combined.faces) if hasattr(mesh_combined, 'faces') else 0

            # Оптимизация модели
            if self.optimize and self.target_vertices is not None:
                if len(mesh_combined.vertices) > self.target_vertices:
                    self.status.emit(f"Оптимизация модели до {self.target_vertices} вершин...")
                    try:
                        # Вычисляем коэффициент уменьшения
                        reduction_ratio = self.target_vertices / len(mesh_combined.vertices)
                        if reduction_ratio < 0.1:
                            reduction_ratio = 0.1  # Минимум 10% от оригинальных вершин

                        mesh_combined = mesh_combined.simplify_quadric_decimation(
                            int(len(mesh_combined.vertices) * reduction_ratio)
                        )
                        self.status.emit(f"Оптимизация выполнена: {len(mesh_combined.vertices)} вершин")
                    except Exception as e:
                        self.status.emit(f"Ошибка оптимизации: {str(e)}")
                else:
                    self.status.emit(f"Модель уже оптимизирована ({len(mesh_combined.vertices)} <= {self.target_vertices})")
            elif self.optimize:
                # Автоматическая оптимизация для больших моделей
                if len(mesh_combined.vertices) > 500000:
                    self.status.emit("Автоматическая оптимизация большой модели...")
                    try:
                        # Уменьшаем до 500k вершин
                        reduction_ratio = 500000 / len(mesh_combined.vertices)
                        if reduction_ratio < 0.1:
                            reduction_ratio = 0.1

                        mesh_combined = mesh_combined.simplify_quadric_decimation(
                            int(len(mesh_combined.vertices) * reduction_ratio)
                        )
                        self.status.emit(f"Оптимизация выполнена: {len(mesh_combined.vertices)} вершин")
                    except Exception as e:
                        self.status.emit(f"Ошибка оптимизации: {str(e)}")
                else:
                    self.status.emit("Оптимизация не требуется")
            else:
                self.status.emit("Оптимизация отключена")

            self.progress.emit(80)

            self.status.emit("Конвертация в PyVista...")
            pv_mesh = self.convert_to_pyvista(mesh_combined)

            self.progress.emit(90)

            result = {
                'mesh': mesh,
                'mesh_combined': mesh_combined,
                'pv_mesh': pv_mesh,
                'is_scene': isinstance(mesh, trimesh.Scene),
                'load_time': load_time,
                'vertices': len(mesh_combined.vertices),
                'faces': len(mesh_combined.faces) if hasattr(mesh_combined, 'faces') else 0,
                'original_vertices': original_vertices,
                'original_faces': original_faces,
                'optimized': len(mesh_combined.vertices) < original_vertices
            }

            self.progress.emit(100)
            self.status.emit("Загрузка завершена")
            self.finished.emit(result)

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)

    def parse_ply_manual(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
                lines = content.split('\n')

                data_start = 0
                vertex_count = 0
                face_count = 0
                is_binary = False

                for i, line in enumerate(lines):
                    if 'format' in line.lower():
                        if 'binary' in line.lower():
                            is_binary = True
                    if 'element vertex' in line.lower():
                        vertex_count = int(line.split()[-1])
                    if 'element face' in line.lower():
                        face_count = int(line.split()[-1])
                    if 'end_header' in line.lower():
                        data_start = i + 1
                        break

                if vertex_count == 0:
                    raise Exception("Не найдены вершины в PLY файле")

                vertices = []
                for i in range(data_start, data_start + vertex_count):
                    if i < len(lines):
                        parts = lines[i].strip().split()
                        if len(parts) >= 3:
                            try:
                                x = float(parts[0])
                                y = float(parts[1])
                                z = float(parts[2])
                                vertices.append([x, y, z])
                            except:
                                continue

                vertices = np.array(vertices, dtype=np.float32)

                faces = []
                face_start = data_start + vertex_count
                for i in range(face_start, min(face_start + face_count, len(lines))):
                    if i < len(lines):
                        parts = lines[i].strip().split()
                        if len(parts) >= 4:
                            try:
                                n = int(parts[0])
                                if n == 3:
                                    f1 = int(parts[1])
                                    f2 = int(parts[2])
                                    f3 = int(parts[3])
                                    if f1 < len(vertices) and f2 < len(vertices) and f3 < len(vertices):
                                        faces.append([f1, f2, f3])
                            except:
                                continue

                if len(vertices) == 0:
                    raise Exception("Не удалось прочитать вершины")

                if faces:
                    return trimesh.Trimesh(vertices=vertices, faces=np.array(faces))
                else:
                    return trimesh.Trimesh(vertices=vertices)

        except Exception as e:
            raise Exception(f"Ошибка ручного парсинга: {str(e)}")

    def convert_to_pyvista(self, mesh):
        try:
            if mesh is None or len(mesh.vertices) == 0:
                raise Exception("Пустая геометрия")

            vertices = np.array(mesh.vertices, dtype=np.float32)

            if hasattr(mesh, 'faces') and len(mesh.faces) > 0:
                faces = np.array(mesh.faces)
                if len(faces.shape) == 2 and faces.shape[1] == 3:
                    faces_with_prefix = np.hstack([np.full((len(faces), 1), 3), faces])
                    faces_flat = faces_with_prefix.flatten().astype(np.int32)
                else:
                    faces_flat = faces.flatten().astype(np.int32)
            else:
                self.status.emit("Выполнение триангуляции...")
                try:
                    from scipy.spatial import Delaunay
                    tri = Delaunay(vertices[:, :2])
                    faces_flat = np.hstack([np.full((len(tri.simplices), 1), 3),
                                          tri.simplices]).flatten().astype(np.int32)
                except:
                    faces_flat = np.array([3, 0, 1, 2], dtype=np.int32)

            pv_mesh = pv.PolyData(vertices, faces_flat)

            return pv_mesh

        except Exception as e:
            raise Exception(f"Ошибка конвертации: {str(e)}")

class PLYViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PLY 3D Viewer - Optimized")
        self.setGeometry(100, 100, 1300, 800)

        self.set_dark_theme()

        self.current_file = None
        self.mesh = None
        self.pv_mesh = None
        self.is_scene = False
        self.loader_thread = None
        self.logger = None

        self.current_color = '#4fc3f7'
        self.show_edges = True
        self.display_mode = 'solid'

        # Настройки оптимизации
        self.optimize_enabled = True
        self.target_vertices = 200000  # Значение по умолчанию

        self.setup_ui()
        self.setup_logging()
        self.setup_pyvista()

        self.log_message("Программа запущена")

    def set_dark_theme(self):
        dark_palette = QPalette()

        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

        self.setPalette(dark_palette)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QPushButton {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #6a6a6a;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666666;
            }
            QLabel {
                color: #ffffff;
            }
            QFrame {
                background-color: #2b2b2b;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                font-family: 'Courier New';
                font-size: 10pt;
            }
            QStatusBar {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QProgressDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QMessageBox {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QSplitter::handle {
                background-color: #3c3c3c;
            }
            QComboBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 5px;
            }
            QComboBox:hover {
                border: 1px solid #6a6a6a;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QSpinBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 5px;
            }
            QSpinBox:hover {
                border: 1px solid #6a6a6a;
            }
        """)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Верхняя панель
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)

        # Кнопки
        self.open_btn = QPushButton("📂 Открыть PLY файл")
        self.open_btn.clicked.connect(self.open_file)
        self.open_btn.setMinimumHeight(35)
        toolbar_layout.addWidget(self.open_btn)

        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet("font-weight: bold; color: #4fc3f7;")
        toolbar_layout.addWidget(self.file_label)

        # Выбор цвета
        color_label = QLabel("Цвет:")
        color_label.setStyleSheet("color: #ffffff;")
        toolbar_layout.addWidget(color_label)

        self.color_combo = QComboBox()
        self.color_combo.addItems([
            'Голубой', 'Зеленый', 'Красный', 'Оранжевый',
            'Фиолетовый', 'Розовый', 'Белый', 'Желтый'
        ])
        self.color_combo.setCurrentText('Голубой')
        self.color_combo.currentTextChanged.connect(self.change_color)
        self.color_combo.setMinimumHeight(30)
        toolbar_layout.addWidget(self.color_combo)

        # Режим отображения
        mode_label = QLabel("Режим:")
        mode_label.setStyleSheet("color: #ffffff;")
        toolbar_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['Сплошной', 'Сетка', 'Смешанный'])
        self.mode_combo.setCurrentText('Сплошной')
        self.mode_combo.currentTextChanged.connect(self.change_display_mode)
        self.mode_combo.setMinimumHeight(30)
        toolbar_layout.addWidget(self.mode_combo)

        # Чекбокс для граней
        self.edges_checkbox = QCheckBox("Показать грани")
        self.edges_checkbox.setChecked(True)
        self.edges_checkbox.stateChanged.connect(self.toggle_edges)
        toolbar_layout.addWidget(self.edges_checkbox)

        # Настройки оптимизации
        opt_group = QGroupBox("Оптимизация")
        opt_group.setStyleSheet("color: #ffffff;")
        opt_layout = QHBoxLayout()

        self.optimize_checkbox = QCheckBox("Включить")
        self.optimize_checkbox.setChecked(True)
        self.optimize_checkbox.stateChanged.connect(self.toggle_optimization)
        opt_layout.addWidget(self.optimize_checkbox)

        opt_layout.addWidget(QLabel("Вершин:"))

        self.vertex_spin = QSpinBox()
        self.vertex_spin.setRange(1000, 10000000)
        self.vertex_spin.setValue(200000)
        self.vertex_spin.setSingleStep(50000)
        self.vertex_spin.setEnabled(True)
        self.vertex_spin.valueChanged.connect(self.change_target_vertices)
        opt_layout.addWidget(self.vertex_spin)

        opt_group.setLayout(opt_layout)
        toolbar_layout.addWidget(opt_group)

        self.info_btn = QPushButton("ℹ️ Информация")
        self.info_btn.clicked.connect(self.show_model_info)
        self.info_btn.setMinimumHeight(35)
        toolbar_layout.addWidget(self.info_btn)

        self.reset_btn = QPushButton("🔄 Сбросить вид")
        self.reset_btn.clicked.connect(self.reset_camera)
        self.reset_btn.setMinimumHeight(35)
        toolbar_layout.addWidget(self.reset_btn)

        self.clear_log_btn = QPushButton("🗑️ Очистить лог")
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.clear_log_btn.setMinimumHeight(35)
        toolbar_layout.addWidget(self.clear_log_btn)

        self.exit_btn = QPushButton("✖ Выход")
        self.exit_btn.clicked.connect(self.close)
        self.exit_btn.setMinimumHeight(35)
        toolbar_layout.addWidget(self.exit_btn)

        toolbar_layout.addStretch()
        main_layout.addWidget(toolbar)

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background-color: #3c3c3c;")
        main_layout.addWidget(separator)

        # Основной контент с разделителем
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Виджет для PyVista
        self.pyvista_frame = QFrame()
        self.pyvista_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.pyvista_frame.setMinimumHeight(500)
        splitter.addWidget(self.pyvista_frame)

        # Панель логов
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.Shape.StyledPanel)
        log_frame.setMaximumWidth(400)

        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(5, 5, 5, 5)

        log_label = QLabel("📋 Лог операций:")
        log_label.setStyleSheet("font-weight: bold; color: #4fc3f7;")
        log_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier New", 9))
        log_layout.addWidget(self.log_text)

        splitter.addWidget(log_frame)
        splitter.setSizes([800, 400])

        main_layout.addWidget(splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("color: #ffffff;")
        self.status_bar.showMessage("Готов к работе")

    def toggle_optimization(self, state):
        self.optimize_enabled = state == Qt.CheckState.Checked.value
        self.vertex_spin.setEnabled(self.optimize_enabled)
        self.log_message(f"Оптимизация: {'включена' if self.optimize_enabled else 'отключена'}")
        if self.pv_mesh is not None:
            # Перезагружаем модель с новыми настройками
            if self.current_file:
                self.start_loading(self.current_file)

    def change_target_vertices(self, value):
        self.target_vertices = value
        self.log_message(f"Целевое количество вершин: {value}")
        if self.pv_mesh is not None and self.optimize_enabled:
            # Перезагружаем модель с новыми настройками
            if self.current_file:
                self.start_loading(self.current_file)

    def get_color_from_name(self, name):
        colors = {
            'Голубой': '#4fc3f7',
            'Зеленый': '#66bb6a',
            'Красный': '#ef5350',
            'Оранжевый': '#ffa726',
            'Фиолетовый': '#ab47bc',
            'Розовый': '#ec407a',
            'Белый': '#ffffff',
            'Желтый': '#ffee58'
        }
        return colors.get(name, '#4fc3f7')

    def change_color(self, color_name):
        self.current_color = self.get_color_from_name(color_name)
        self.log_message(f"Изменен цвет: {color_name}")
        if self.pv_mesh is not None:
            self.display_model()

    def change_display_mode(self, mode):
        mode_map = {
            'Сплошной': 'solid',
            'Сетка': 'wireframe',
            'Смешанный': 'both'
        }
        self.display_mode = mode_map.get(mode, 'solid')
        self.log_message(f"Изменен режим отображения: {mode}")
        if self.pv_mesh is not None:
            self.display_model()

    def toggle_edges(self, state):
        self.show_edges = state == Qt.CheckState.Checked.value
        self.log_message(f"Показ граней: {self.show_edges}")
        if self.pv_mesh is not None:
            self.display_model()

    def setup_pyvista(self):
        try:
            self.plotter = QtInteractor(self.pyvista_frame)
            layout = QVBoxLayout(self.pyvista_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.plotter)

            self.plotter.set_background('#1a1a1a')
            self.plotter.show_grid(color='#444444')
            self.plotter.add_axes(color='#888888')
            self.plotter.view_isometric()

            self.log_message("PyVista инициализирован")

        except Exception as e:
            print(f"Ошибка инициализации PyVista: {str(e)}")
            if hasattr(self, 'log_message'):
                self.log_message(f"Ошибка инициализации PyVista: {str(e)}", 'ERROR')

    def setup_logging(self):
        self.logger = logging.getLogger('PLYViewer')
        self.logger.setLevel(logging.DEBUG)

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        handler = LogHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        try:
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'ply_viewer_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

            print(f"Лог-файл: {log_file}")
        except Exception as e:
            print(f"Не удалось создать файл лога: {str(e)}")

    def log_message(self, message, level='INFO'):
        try:
            if self.logger is None:
                print(f"{level}: {message}")
                return

            if level == 'DEBUG':
                self.logger.debug(message)
            elif level == 'WARNING':
                self.logger.warning(message)
            elif level == 'ERROR':
                self.logger.error(message)
            else:
                self.logger.info(message)

            if level in ['INFO', 'WARNING', 'ERROR']:
                self.status_bar.showMessage(message[:100])
        except Exception as e:
            print(f"Ошибка логирования: {e}")
            print(f"Сообщение: {message}")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите PLY файл",
            "",
            "PLY файлы (*.ply);;Все файлы (*.*)"
        )

        if file_path:
            self.current_file = file_path
            self.file_label.setText(f"📄 {os.path.basename(file_path)}")
            self.log_message(f"Выбран файл: {file_path}")

            file_size = os.path.getsize(file_path) / (1024 * 1024)
            self.log_message(f"Размер файла: {file_size:.2f} MB")

            if file_size > 100:
                self.log_message("ВНИМАНИЕ: Большой файл! Загрузка может занять время.", 'WARNING')

            self.start_loading(file_path)

    def start_loading(self, file_path):
        self.open_btn.setEnabled(False)
        self.info_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self.color_combo.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.edges_checkbox.setEnabled(False)
        self.optimize_checkbox.setEnabled(False)
        self.vertex_spin.setEnabled(False)

        self.progress_dialog = QProgressDialog("Загрузка PLY модели...", "Отмена", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(100)
        self.progress_dialog.canceled.connect(self.cancel_loading)

        # Передаем настройки оптимизации
        target = self.target_vertices if self.optimize_enabled else None
        self.loader_thread = LoaderThread(file_path, self.optimize_enabled, target)
        self.loader_thread.progress.connect(self.update_progress)
        self.loader_thread.status.connect(self.on_loading_status)
        self.loader_thread.finished.connect(self.on_loading_finished)
        self.loader_thread.error.connect(self.on_loading_error)

        self.log_message(f"Запуск потока загрузки (оптимизация: {self.optimize_enabled}, цель: {target if target else 'авто'})")
        self.loader_thread.start()

    def cancel_loading(self):
        if self.loader_thread and self.loader_thread.isRunning():
            self.log_message("Загрузка отменена пользователем", 'WARNING')
            self.loader_thread.terminate()
            self.loader_thread.wait()
            self.progress_dialog.close()
            self.enable_buttons()

    def update_progress(self, value):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.setValue(value)

    def on_loading_status(self, message):
        self.log_message(message)

    def on_loading_finished(self, result):
        self.log_message("Загрузка успешно завершена")

        self.mesh = result['mesh']
        self.mesh_combined = result['mesh_combined']
        self.pv_mesh = result['pv_mesh']
        self.is_scene = result['is_scene']

        self.display_model()

        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()

        self.enable_buttons()

        # Показываем информацию о загрузке и оптимизации
        info_msg = f"Загружено: {result['vertices']} вершин, {result['faces']} граней"
        if result.get('optimized', False):
            info_msg += f" (оптимизировано с {result.get('original_vertices', 0)} вершин)"
        self.log_message(info_msg)
        self.log_message(f"Время загрузки: {result['load_time']:.2f} сек")

        if self.is_scene:
            num_geoms = len(self.mesh.geometry) if hasattr(self.mesh, 'geometry') else 1
            self.status_bar.showMessage(f"Загружена сцена: {num_geoms} объектов, {result['vertices']} вершин")
        else:
            self.status_bar.showMessage(f"Загружена модель: {result['vertices']} вершин, {result['faces']} граней")

    def on_loading_error(self, error_msg):
        self.log_message(f"ОШИБКА загрузки: {error_msg}", 'ERROR')

        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()

        self.enable_buttons()

        QMessageBox.critical(self, "Ошибка загрузки",
                           f"Не удалось загрузить файл:\n{error_msg[:500]}...")

    def enable_buttons(self):
        self.open_btn.setEnabled(True)
        self.info_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self.color_combo.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.edges_checkbox.setEnabled(True)
        self.optimize_checkbox.setEnabled(True)
        self.vertex_spin.setEnabled(self.optimize_enabled)

    def display_model(self):
        try:
            self.log_message("Отображение модели...")

            self.plotter.clear()

            if self.pv_mesh is not None and self.pv_mesh.n_points > 0:
                self.log_message(f"Отображение модели с {self.pv_mesh.n_points} вершинами")

                # Настройки отображения в зависимости от режима
                if self.display_mode == 'solid':
                    self.plotter.add_mesh(
                        self.pv_mesh,
                        color=self.current_color,
                        smooth_shading=True,
                        opacity=1.0,
                        show_edges=False,
                        lighting=True,
                        specular=0.3,
                        specular_power=20
                    )

                elif self.display_mode == 'wireframe':
                    self.plotter.add_mesh(
                        self.pv_mesh,
                        color=self.current_color,
                        style='wireframe',
                        line_width=1,
                        opacity=0.7
                    )

                elif self.display_mode == 'both':
                    self.plotter.add_mesh(
                        self.pv_mesh,
                        color=self.current_color,
                        smooth_shading=True,
                        opacity=0.8,
                        show_edges=True,
                        edge_color='white',
                        line_width=1,
                        lighting=True,
                        specular=0.2,
                        specular_power=15
                    )

                # Добавляем подсветку
                self.plotter.add_light(pv.Light(position=(5, 5, 5), light_type='scene light'))
                self.plotter.add_light(pv.Light(position=(-5, -5, -5), light_type='scene light'))

                self.plotter.view_isometric()
                self.plotter.camera_position = 'iso'
                self.plotter.render()

                self.log_message("Модель отображена")
            else:
                self.log_message("Модель пустая или не загружена", 'WARNING')
                self.plotter.add_text("Модель не загружена", color='white', font_size=20)
                self.plotter.render()

        except Exception as e:
            self.log_message(f"Ошибка отображения: {str(e)}", 'ERROR')
            import traceback
            self.log_message(traceback.format_exc(), 'ERROR')

    def reset_camera(self):
        if self.pv_mesh is not None and self.pv_mesh.n_points > 0:
            self.plotter.view_isometric()
            self.plotter.render()
            self.log_message("Вид сброшен")
            self.status_bar.showMessage("Вид сброшен")

    def clear_log(self):
        self.log_text.clear()
        self.log_message("Лог очищен")

    def show_model_info(self):
        if self.mesh is None:
            QMessageBox.information(self, "Информация", "Модель не загружена")
            return

        try:
            info_text = f"""
            <b>Информация о {'сцене' if self.is_scene else 'модели'}:</b><br><br>
            <b>Имя файла:</b> {os.path.basename(self.current_file)}<br>
            <b>Тип:</b> {'Сцена (несколько объектов)' if self.is_scene else 'Одиночная модель'}<br>
            <b>Количество объектов:</b> {len(self.mesh.geometry) if hasattr(self.mesh, 'geometry') and self.is_scene else 1}<br>
            <b>Количество вершин:</b> {len(self.mesh_combined.vertices)}<br>
            <b>Количество граней:</b> {len(self.mesh_combined.faces) if hasattr(self.mesh_combined, 'faces') else 0}<br>
            <b>Границы:</b> {self.mesh_combined.bounds}<br>
            """

            if hasattr(self.mesh_combined, 'volume'):
                info_text += f"<b>Объем:</b> {self.mesh_combined.volume:.3f}<br>"
            if hasattr(self.mesh_combined, 'area'):
                info_text += f"<b>Площадь поверхности:</b> {self.mesh_combined.area:.3f}<br>"

            info_text += f"""
            <br><b>Настройки оптимизации:</b><br>
            <b>Оптимизация:</b> {'Включена' if self.optimize_enabled else 'Отключена'}<br>
            <b>Целевое количество вершин:</b> {self.target_vertices if self.optimize_enabled else 'N/A'}<br>
            """

            QMessageBox.information(self, "Информация о модели", info_text)

        except Exception as e:
            self.log_message(f"Ошибка получения информации: {str(e)}", 'ERROR')
            QMessageBox.warning(self, "Ошибка", f"Не удалось получить информацию:\n{str(e)}")

    def closeEvent(self, event):
        try:
            self.log_message("Закрытие программы...")
        except:
            pass

        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.terminate()
            self.loader_thread.wait()

        if hasattr(self, 'plotter'):
            self.plotter.close()

        try:
            self.log_message("Программа завершена")
        except:
            pass

        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    viewer = PLYViewer()
    viewer.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
