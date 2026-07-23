import sys
import os
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLabel, QFileDialog, QMessageBox,
    QGridLayout, QGroupBox, QFormLayout, QFrame, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import struct
import json
import gc
import mmap
import time
from queue import Queue

# Оптимизации для VTK/Metal на macOS
os.environ.setdefault('VTK_SILENCE_STATUS', '1')
os.environ.setdefault('PYVISTA_OFF_SCREEN', 'false')


class GLBLoaderThread(QThread):
    # Сигналы для безопасной передачи данных в главный поток
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, directory, mesh_queue, use_decimation=True):
        super().__init__()
        self.directory = directory
        self.mesh_queue = mesh_queue
        self.use_decimation = use_decimation

    def run(self):
        try:
            glb_files = [f for f in os.listdir(self.directory)
                         if f.lower().endswith(('.glb', '.gltf'))]
            if not glb_files:
                self.error_occurred.emit("GLB файлы не найдены")
                return

            total_files = len(glb_files)
            self.status_updated.emit(f"Найдено {total_files} файлов")

            errors = []
            for i, f in enumerate(glb_files):
                file_path = os.path.join(self.directory, f)
                try:
                    result = self._process_single_file(file_path, f)
                    if result is None:
                        errors.append(f"{f}: не удалось обработать")
                        continue

                    mesh_pv, stats = result
                    file_size = os.path.getsize(file_path)
                    self.mesh_queue.put((mesh_pv, f, stats, file_size))

                    self.status_updated.emit(f"Обработано: {i+1}/{total_files}")
                    gc.collect()

                except Exception as e:
                    errors.append(f"{f}: {str(e)}")

            if errors:
                self.error_occurred.emit("\n".join(errors[:10]))

        except Exception as e:
            self.error_occurred.emit(f"Произошла ошибка: {str(e)}")

    def _process_single_file(self, file_path, filename):
        try:
            import trimesh
            mesh = trimesh.load(file_path, force='mesh', process=False)
            if mesh is None or len(mesh.vertices) == 0:
                return None

            vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float32)

            # Конвертация системы координат (glTF -> PyVista) + Отзеркаливание по X
            if vertices.shape[1] == 3:
                vertices = vertices[:, [0, 2, 1]]  # Меняем местами Y и Z: [X, Z, Y]
                vertices[:, 0] *= -1                # Инвертируем X (отзеркаливание)
                vertices[:, 1] *= -1                # Инвертируем новую Y (бывшую Z)

            faces = np.ascontiguousarray(mesh.faces, dtype=np.int32)

            del mesh
            gc.collect()

            coords = self._parse_coordinates_from_filename(filename)
            if coords is not None:
                vertices += np.asarray(coords, dtype=np.float32)

            n_faces = faces.shape[0]
            faces_pv = np.empty((n_faces, 4), dtype=np.int32)
            faces_pv[:, 0] = 3
            faces_pv[:, 1:] = faces
            faces_pv = np.ascontiguousarray(faces_pv.ravel())

            mesh_pv = pv.PolyData(vertices, faces_pv)

            vertex_colors = self._extract_colors_fast(file_path, mesh_pv.n_points)
            if vertex_colors is not None:
                mesh_pv.point_data['Colors'] = vertex_colors
                del vertex_colors

            stats = {'orig_faces': n_faces, 'orig_verts': mesh_pv.n_points}

            # --- ДЕЦИМАЦИЯ ---
            if self.use_decimation and n_faces > 2_000_000:
                try:
                    reduction = 1.0 - (500_000 / n_faces)
                    mesh_pv = mesh_pv.decimate_pro(reduction, progress_bar=False)
                    stats['decimated_faces'] = mesh_pv.n_faces
                    stats['decimated_verts'] = mesh_pv.n_points
                except Exception as e:
                    stats['decimation_error'] = str(e)

            return mesh_pv, stats

        except Exception as e:
            print(f"Ошибка обработки {filename}: {e}")
            return None

    def _extract_colors_fast(self, file_path, vertex_count):
        try:
            file_size = os.path.getsize(file_path)
            if file_size < 20:
                return None

            with open(file_path, 'rb') as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    if mm[0:4] != b'glTF':
                        return None

                    json_length = struct.unpack_from('<I', mm, 12)[0]
                    json_data = mm[20:20 + json_length].decode('utf-8').strip()
                    gltf = json.loads(json_data)

                    color_accessor_idx = None
                    for m in gltf.get('meshes', []):
                        for p in m.get('primitives', []):
                            attrs = p.get('attributes', {})
                            if 'COLOR_0' in attrs:
                                color_accessor_idx = attrs['COLOR_0']
                                break
                        if color_accessor_idx is not None:
                            break

                    if color_accessor_idx is None:
                        return None

                    accessor = gltf['accessors'][color_accessor_idx]
                    if accessor.get('count', 0) != vertex_count:
                        return None

                    bv_idx = accessor.get('bufferView')
                    if bv_idx is None:
                        return None
                    bv = gltf['bufferViews'][bv_idx]

                    bin_chunk_offset = 20 + json_length
                    if bin_chunk_offset % 4 != 0:
                        bin_chunk_offset += 4 - (bin_chunk_offset % 4)
                    bin_chunk_offset += 8

                    byte_offset = (bv.get('byteOffset', 0) + accessor.get('byteOffset', 0))
                    byte_stride = bv.get('byteStride', 0)
                    component_type = accessor.get('componentType', 5126)
                    acc_type = accessor.get('type', 'VEC3')

                    type_sizes = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
                    n_components = type_sizes.get(acc_type, 3)

                    comp_sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
                    comp_size = comp_sizes.get(component_type, 4)
                    element_size = n_components * comp_size

                    if byte_stride == 0:
                        byte_stride = element_size

                    abs_offset = bin_chunk_offset + byte_offset

                    raw = None
                    raw_bytes = None
                    colors = None

                    if component_type == 5126:  # FLOAT
                        if byte_stride == element_size:
                            raw = np.frombuffer(mm, dtype=np.float32, count=vertex_count * n_components, offset=abs_offset)
                            colors = raw.reshape((vertex_count, n_components))
                        else:
                            raw_bytes = np.frombuffer(mm, dtype=np.uint8, count=vertex_count * byte_stride, offset=abs_offset)
                            raw_bytes = raw_bytes.reshape((vertex_count, byte_stride))
                            colors = raw_bytes[:, :element_size].view(np.float32).reshape((vertex_count, n_components))
                        colors = (colors[:, :3] * 255).astype(np.uint8)

                    elif component_type in (5120, 5121):  # BYTE / UNSIGNED_BYTE
                        if byte_stride == element_size:
                            raw = np.frombuffer(mm, dtype=np.uint8, count=vertex_count * n_components, offset=abs_offset)
                            colors = raw.reshape((vertex_count, n_components))
                        else:
                            raw_bytes = np.frombuffer(mm, dtype=np.uint8, count=vertex_count * byte_stride, offset=abs_offset)
                            colors = raw_bytes.reshape((vertex_count, byte_stride))[:, :n_components]
                        colors = colors[:, :3].astype(np.uint8)

                    elif component_type in (5122, 5123):  # SHORT / USHORT
                        dt = np.int16 if component_type == 5122 else np.uint16
                        if byte_stride == element_size:
                            raw = np.frombuffer(mm, dtype=dt, count=vertex_count * n_components, offset=abs_offset)
                            colors = raw.reshape((vertex_count, n_components))
                        else:
                            raw_bytes = np.frombuffer(mm, dtype=np.uint8, count=vertex_count * byte_stride, offset=abs_offset)
                            colors = raw_bytes.reshape((vertex_count, byte_stride))[:, :element_size].view(dt).reshape((vertex_count, n_components))
                        colors = (colors[:, :3] / 256.0).astype(np.uint8)
                    else:
                        return None

                    del raw, raw_bytes
                    return np.ascontiguousarray(colors).copy()

                finally:
                    mm.close()
        except Exception as e:
            print(f"Ошибка извлечения цветов: {e}")
            return None

    def _parse_coordinates_from_filename(self, filename):
        import re
        name_without_ext = os.path.splitext(filename)[0]
        patterns = [
            r'.*_([\d.-]+)_([\d.-]+)_([\d.-]+)$',
            r'.*\(([\d.-]+),([\d.-]+),([\d.-]+)\)$',
            r'.*x([\d.-]+)y([\d.-]+)z([\d.-]+)$',
        ]
        for pattern in patterns:
            match = re.match(pattern, name_without_ext)
            if match:
                try:
                    coords = np.array([float(match.group(i)) for i in (1, 2, 3)], dtype=np.float32)
                    coords[0] = -coords[0]  # Отзеркаливание X
                    return coords
                except ValueError:
                    continue
        return None


class GLBViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GLB Viewer — Аналитический стенд (PyQt6 + PyVista)")
        self.setGeometry(100, 100, 1400, 850)

        self.loaded_meshes = []
        self.rotation_active = False
        self.last_rotation_time = None
        self.outline_actor = None

        self.mesh_queue = Queue()
        self.worker_thread = None

        self._setup_ui()
        self._setup_timers()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- ЛЕВАЯ ПАНЕЛЬ (УПРАВЛЕНИЕ И АНАЛИТИКА) ---
        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_panel.setFixedWidth(350)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(10)

        # Заголовок
        title_label = QLabel("Панель управления")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        left_layout.addWidget(title_label)

        # Кнопки видов (Компактная сетка)
        view_group = QGroupBox("Управление видом")
        view_layout = QGridLayout(view_group)

        self.btn_top = QPushButton("Сверху")
        self.btn_bottom = QPushButton("Снизу")
        self.btn_left = QPushButton("Слева")
        self.btn_right = QPushButton("Справа")
        self.btn_iso = QPushButton("ИСО1")
        self.btn_rotate = QPushButton("Вращение")

        view_layout.addWidget(self.btn_top, 0, 0)
        view_layout.addWidget(self.btn_bottom, 0, 1)
        view_layout.addWidget(self.btn_left, 0, 2)
        view_layout.addWidget(self.btn_right, 1, 0)
        view_layout.addWidget(self.btn_iso, 1, 1)
        view_layout.addWidget(self.btn_rotate, 1, 2)

        self.btn_top.clicked.connect(lambda: self._set_view('top'))
        self.btn_bottom.clicked.connect(lambda: self._set_view('bottom'))
        self.btn_left.clicked.connect(lambda: self._set_view('left'))
        self.btn_right.clicked.connect(lambda: self._set_view('right'))
        self.btn_iso.clicked.connect(lambda: self._set_view('iso'))
        self.btn_rotate.clicked.connect(self._toggle_rotation)

        left_layout.addWidget(view_group)

        # Чекбокс децимации
        self.chk_decimation = QCheckBox("Децимация (упрощать модели >2 млн. граней)")
        self.chk_decimation.setChecked(False)
        self.chk_decimation.setToolTip("Если включено, модели упрощаются до 500к граней для плавности.\nВыключите, чтобы загрузить все точки в исходном виде.")
        left_layout.addWidget(self.chk_decimation)

        # Список файлов
        list_group = QGroupBox("Загруженные детали (клик = зум)")
        list_layout = QVBoxLayout(list_group)
        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Courier", 9))
        self.list_widget.currentRowChanged.connect(self._zoom_to_file)
        list_layout.addWidget(self.list_widget)

        # Кнопка снятия выделения
        self.btn_deselect = QPushButton("Снять выделение")
        self.btn_deselect.clicked.connect(self._deselect_file)
        list_layout.addWidget(self.btn_deselect)

        left_layout.addWidget(list_group, stretch=1)

        # Блок Аналитики (10 параметров)
        analytics_group = QGroupBox("Аналитика сборки")
        analytics_layout = QFormLayout(analytics_group)
        analytics_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        analytics_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        self.lbl_total_files = QLabel("0")
        self.lbl_total_polys = QLabel("0")
        self.lbl_total_verts = QLabel("0")
        self.lbl_total_size = QLabel("0 МБ")
        self.lbl_avg_polys = QLabel("0")
        self.lbl_max_size = QLabel("0 МБ")
        self.lbl_min_size = QLabel("0 КБ")
        self.lbl_scene_dx = QLabel("0 мм")
        self.lbl_scene_dy = QLabel("0 мм")
        self.lbl_scene_dz = QLabel("0 мм")

        for lbl in [self.lbl_total_files, self.lbl_total_polys, self.lbl_total_verts, self.lbl_total_size,
                    self.lbl_avg_polys, self.lbl_max_size, self.lbl_min_size, self.lbl_scene_dx,
                    self.lbl_scene_dy, self.lbl_scene_dz]:
            lbl.setFont(QFont("Courier", 9, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        analytics_layout.addRow("1. Всего деталей:", self.lbl_total_files)
        analytics_layout.addRow("2. Всего полигонов:", self.lbl_total_polys)
        analytics_layout.addRow("3. Всего вершин:", self.lbl_total_verts)
        analytics_layout.addRow("4. Общий вес:", self.lbl_total_size)
        analytics_layout.addRow("5. Ср. полигонов/дет:", self.lbl_avg_polys)
        analytics_layout.addRow("6. Макс. файл:", self.lbl_max_size)
        analytics_layout.addRow("7. Мин. файл:", self.lbl_min_size)
        analytics_layout.addRow("8. Габарит сцены X:", self.lbl_scene_dx)
        analytics_layout.addRow("9. Габарит сцены Y:", self.lbl_scene_dy)
        analytics_layout.addRow("10. Габарит сцены Z:", self.lbl_scene_dz)

        left_layout.addWidget(analytics_group)

        # Кнопка загрузки и статус
        self.btn_load = QPushButton("📁 Выбрать каталог с GLB файлами")
        self.btn_load.setStyleSheet("font-weight: bold; padding: 10px; background-color: #0078D7; color: white;")
        self.btn_load.clicked.connect(self.select_directory)
        left_layout.addWidget(self.btn_load)

        self.status_label = QLabel("Ожидание загрузки...")
        self.status_label.setFont(QFont("Segoe UI", 9, italic=True))
        left_layout.addWidget(self.status_label)

        main_layout.addWidget(left_panel)

        # --- ПРАВАЯ ПАНЕЛЬ (3D МОДЕЛЬ) ---
        self.plotter = QtInteractor(self)
        self.plotter.enable_anti_aliasing('ssaa')
        self.plotter.add_axes()
        self.plotter.set_background('#1e1e1e')

        self.plotter.show_bounds(
            grid='back',
            location='outer',
            ticks='both',
            color='#555555',
            font_size=10
        )

        main_layout.addWidget(self.plotter, stretch=1)

    def _setup_timers(self):
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._process_mesh_queue)
        self.queue_timer.start(100)

        self.rotation_timer = QTimer(self)
        self.rotation_timer.timeout.connect(self._rotate_model)

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Выберите каталог с GLB файлами")
        if not directory:
            return

        self.status_label.setText(f"Загрузка из: {directory}")
        self.btn_load.setEnabled(False)

        self.loaded_meshes.clear()
        self.list_widget.clear()
        self.plotter.clear_actors()
        self._update_analytics()

        # Инициализируем поток с использованием сигналов
        self.worker_thread = GLBLoaderThread(
            directory,
            self.mesh_queue,
            use_decimation=self.chk_decimation.isChecked()
        )

        # Подключаем сигналы к методам главного потока
        self.worker_thread.status_updated.connect(self._update_status)
        self.worker_thread.error_occurred.connect(self._show_errors)

        self.worker_thread.start()

    def _update_status(self, text):
        self.status_label.setText(text)

    def _show_errors(self, error_msg):
        QMessageBox.warning(self, "Ошибки при загрузке", error_msg)
        self.btn_load.setEnabled(True)

    def _process_mesh_queue(self):
        while not self.mesh_queue.empty():
            try:
                mesh_pv, filename, stats, file_size = self.mesh_queue.get_nowait()
                self._add_mesh_to_plotter(mesh_pv, filename, stats, file_size)
                self._update_analytics()
            except Exception as e:
                print(f"Queue error: {e}")

        if self.worker_thread and not self.worker_thread.isRunning():
            self.worker_thread = None
            if not self.btn_load.isEnabled():
                self.status_label.setText("Готово. Выберите файл из списка.")
                self.btn_load.setEnabled(True)

    def _add_mesh_to_plotter(self, mesh, filename, stats, file_size):
        try:
            use_lighting = mesh.n_faces < 1_000_000

            render_args = {
                "lighting": use_lighting,
                "smooth_shading": False,
                "show_edges": False,
                "opacity": 1.0,
                "ambient": 0.4 if not use_lighting else 0.2,
                "diffuse": 0.6 if not use_lighting else 0.8,
                "name": filename
            }

            if 'Colors' in mesh.point_data:
                render_args["scalars"] = 'Colors'
                render_args["rgb"] = True
            else:
                render_args["color"] = 'lightgray'

            self.plotter.add_mesh(mesh, **render_args)

            bounds = mesh.bounds
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            x = (bounds[0] + bounds[1]) / 2.0
            y = (bounds[2] + bounds[3]) / 2.0

            info = {
                'name': filename,
                'mesh': mesh,
                'size': file_size,
                'x': x, 'y': y,
                'dx': dx, 'dy': dy, 'dz': dz,
                'bounds': bounds,
                'faces': stats.get('decimated_faces', stats.get('orig_faces', 0)),
                'verts': stats.get('decimated_verts', stats.get('orig_verts', 0)),
            }
            self.loaded_meshes.append(info)

            name_short = filename if len(filename) <= 25 else filename[:22] + "..."
            text = f"{len(self.loaded_meshes):2d}. {name_short:25s} | {file_size//1024:>4d}КБ | X={x:7.1f} Y={y:7.1f}"
            self.list_widget.addItem(text)

        except Exception as e:
            print(f"Ошибка добавления {filename}: {e}")

    def _update_analytics(self):
        n = len(self.loaded_meshes)
        self.lbl_total_files.setText(f"{n}")

        if n == 0:
            self.lbl_total_polys.setText("0")
            self.lbl_total_verts.setText("0")
            self.lbl_total_size.setText("0 МБ")
            self.lbl_avg_polys.setText("0")
            self.lbl_max_size.setText("0 МБ")
            self.lbl_min_size.setText("0 КБ")
            self.lbl_scene_dx.setText("0 мм")
            self.lbl_scene_dy.setText("0 мм")
            self.lbl_scene_dz.setText("0 мм")
            return

        total_p = sum(i['faces'] for i in self.loaded_meshes)
        total_v = sum(i['verts'] for i in self.loaded_meshes)
        total_sz = sum(i['size'] for i in self.loaded_meshes)
        max_sz = max(i['size'] for i in self.loaded_meshes)
        min_sz = min(i['size'] for i in self.loaded_meshes)

        min_x = min(i['bounds'][0] for i in self.loaded_meshes)
        max_x = max(i['bounds'][1] for i in self.loaded_meshes)
        min_y = min(i['bounds'][2] for i in self.loaded_meshes)
        max_y = max(i['bounds'][3] for i in self.loaded_meshes)
        min_z = min(i['bounds'][4] for i in self.loaded_meshes)
        max_z = max(i['bounds'][5] for i in self.loaded_meshes)

        self.lbl_total_polys.setText(f"{total_p:,}")
        self.lbl_total_verts.setText(f"{total_v:,}")
        self.lbl_total_size.setText(f"{total_sz / (1024*1024):.2f} МБ")
        self.lbl_avg_polys.setText(f"{total_p // n:,}")
        self.lbl_max_size.setText(f"{max_sz / (1024*1024):.2f} МБ")
        self.lbl_min_size.setText(f"{min_sz / 1024:.1f} КБ")
        self.lbl_scene_dx.setText(f"{max_x - min_x:.1f} мм")
        self.lbl_scene_dy.setText(f"{max_y - min_y:.1f} мм")
        self.lbl_scene_dz.setText(f"{max_z - min_z:.1f} мм")

    def _deselect_file(self):
        self.list_widget.clearSelection()
        if self.outline_actor:
            self.plotter.remove_actor(self.outline_actor)
            self.outline_actor = None
            self.plotter.render()

    def _zoom_to_file(self, idx):
        if idx < 0:
            if self.outline_actor:
                self.plotter.remove_actor(self.outline_actor)
                self.outline_actor = None
                self.plotter.render()
            return

        if idx >= len(self.loaded_meshes):
            return

        info = self.loaded_meshes[idx]
        mesh = info['mesh']
        bounds = list(info['bounds'])

        if self.outline_actor:
            self.plotter.remove_actor(self.outline_actor)

        self.outline_actor = self.plotter.add_mesh(
            mesh,
            style='wireframe',
            color='red',
            line_width=5,
            name="selected_outline"
        )

        sz = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        pad = max(sz * 0.25, 1.0)
        padded = [
            bounds[0] - pad, bounds[1] + pad,
            bounds[2] - pad, bounds[3] + pad,
            bounds[4] - pad, bounds[5] - pad,
        ]

        self.plotter.renderer.ResetCamera(padded)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def _set_view(self, view_type):
        if view_type == 'top':
            try: self.plotter.view_xy(negative=False)
            except TypeError: self.plotter.view_xy()
        elif view_type == 'bottom':
            try: self.plotter.view_xy(negative=True)
            except TypeError: self.plotter.view_xy()
        elif view_type == 'left':
            try: self.plotter.view_yz(negative=True)
            except TypeError: self.plotter.view_yz()
        elif view_type == 'right':
            try: self.plotter.view_yz(negative=False)
            except TypeError: self.plotter.view_yz()
        elif view_type == 'iso':
            self.plotter.view_isometric()

        self.plotter.reset_camera()

    def _toggle_rotation(self):
        self.rotation_active = not self.rotation_active
        if self.rotation_active:
            self.last_rotation_time = time.time()
            self.rotation_timer.start(33)
            self.btn_rotate.setStyleSheet("background-color: #2d5a2d; color: white;")
        else:
            self.rotation_timer.stop()
            self.last_rotation_time = None
            self.btn_rotate.setStyleSheet("")

    def _rotate_model(self):
        if not self.last_rotation_time:
            return
        now = time.time()
        dt = now - self.last_rotation_time
        self.last_rotation_time = now

        angle = 18.0 * dt
        self.plotter.camera.azimuth += angle
        self.plotter.render()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    dark_palette = """
        QWidget {
            background-color: #1e1e1e;
            color: #e0e0e0;
        }
        QFrame#leftPanel {
            background-color: #252526;
            border-right: 1px solid #3c3c3c;
        }
        QGroupBox {
            border: 1px solid #3c3c3c;
            border-radius: 4px;
            margin-top: 12px;
            color: #cccccc;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QPushButton {
            background-color: #3a3d41;
            color: #ffffff;
            border: 1px solid #4a4d51;
            border-radius: 4px;
            padding: 6px;
        }
        QPushButton:hover {
            background-color: #4a4d51;
        }
        QPushButton:pressed {
            background-color: #2a2d31;
        }
        QListWidget {
            background-color: #1e1e1e;
            color: #e0e0e0;
            border: 1px solid #3c3c3c;
        }
        QListWidget::item:selected {
            background-color: #0078D7;
            color: white;
        }
        QLabel {
            color: #e0e0e0;
        }
        QCheckBox {
            color: #e0e0e0;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #4a4d51;
            border-radius: 3px;
            background-color: #1e1e1e;
        }
        QCheckBox::indicator:checked {
            background-color: #0078D7;
            border: 1px solid #0078D7;
        }
    """
    app.setStyleSheet(dark_palette)

    window = GLBViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
