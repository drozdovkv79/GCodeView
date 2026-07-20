"""
Чтение: /Users/drozdovkv/Downloads/МАНЖЕРОК/all_10_seg.las
Загружено 25,350,617 точек
Децимация: 25,350,617 -> ~15,000,000...
После децимации: 8,436,174 точек
Нормали для 8,436,174 точек...
  Нормали: 421,808/8,436,174 (5%)
  Нормали: 3,374,464/8,436,174 (40%)
  Нормали: 6,327,120/8,436,174 (75%)
Нормали готовы
Построение меша...
Треугольников: 16,462,914
Сохранение: /Users/drozdovkv/Downloads/МАНЖЕРОК/all_10_seg.glb
GLB: 8,436,174 вершин, 16,462,914 треуг., 478.0 MB
GLB создан!

"""


import numpy as np
import laspy
from scipy.spatial import Delaunay, cKDTree
import os
import struct
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import threading
import subprocess
import platform
import warnings
import time
import hashlib

warnings.filterwarnings('ignore')

N_CPU = max(1, os.cpu_count() - 1)


class LogWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Детальные логи конвертации")
        self.window.geometry("950x750")
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        tabs = [
            ("general", "Общие логи"),
            ("las", "Информация о LAS"),
            ("color", "Анализ цвета"),
            ("glb", "GLB структура"),
            ("perf", "Производительность"),
        ]
        self.texts = {}
        for tag, title in tabs:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=title)
            txt = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=("Consolas", 9))
            txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.texts[tag] = txt

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="Очистить", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Скрыть", command=self.hide).pack(side=tk.LEFT, padx=5)

        self.hidden = False
        self._lock = threading.Lock()

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.hidden = False

    def hide(self):
        self.window.withdraw()
        self.hidden = True

    def toggle(self):
        self.show() if self.hidden else self.hide()

    def log(self, message, tag="general"):
        with self._lock:
            target = self.texts.get(tag, self.texts["general"])
            target.config(state='normal')
            target.insert(tk.END, str(message) + "\n")
            target.see(tk.END)
            target.config(state='disabled')

    def clear_all(self):
        for txt in self.texts.values():
            txt.config(state='normal')
            txt.delete(1.0, tk.END)
            txt.config(state='disabled')


class Timer:
    def __init__(self, name, log_callback, tag="perf"):
        self.name = name
        self.log = log_callback
        self.tag = tag
        self.t0 = None

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.t0
        self.log(f"[TIMER] {self.name}: {elapsed:.2f} сек", self.tag)


class LASConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Конвертер LAS → GLB (High-Perf v2)")
        self.root.geometry("720x620")
        self.root.resizable(True, True)

        self.input_file = tk.StringVar()
        self.output_file = tk.StringVar()
        self.max_vertices = tk.IntVar(value=100000)
        self.k_neighbors = tk.IntVar(value=15)
        self.decimate_before = tk.IntVar(value=500000)
        self.open_after_convert = tk.BooleanVar(value=True)
        self.color_mode = tk.StringVar(value="color")
        self.material_mode = tk.StringVar(value="basic")
        self.status = tk.StringVar(value="Готов к работе")
        self.progress = tk.DoubleVar(value=0)

        self._cancel_event = threading.Event()
        self._cancel_event.clear()

        self.log_window = LogWindow(root)
        self.log_window.hide()

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        ttk.Label(main_frame, text="Конвертер LAS → GLB (High-Perf v2)",
                 font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=3, pady=10)

        # Входной файл
        ttk.Label(main_frame, text="Входной LAS файл:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.input_file, width=50).grid(
            row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_input_file).grid(
            row=1, column=2, padx=5, pady=5)

        # Выходной файл
        ttk.Label(main_frame, text="Выходной GLB файл:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.output_file, width=50).grid(
            row=2, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_output_file).grid(
            row=2, column=2, padx=5, pady=5)

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # Параметры
        params_frame = ttk.LabelFrame(main_frame, text="Параметры конвертации", padding="10")
        params_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        params_frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(params_frame, text="Макс. вершин в GLB:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=2000000, textvariable=self.max_vertices, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(итоговое в файле)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Децимация до нормалей:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=1000, to=10000000, textvariable=self.decimate_before, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(уменьшить перед нормалями)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Соседей для нормалей:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=100, textvariable=self.k_neighbors, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(меньше = быстрее)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Цветовой режим:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        cf = ttk.Frame(params_frame)
        cf.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(cf, text="Цветной", variable=self.color_mode, value="color").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(cf, text="Серый", variable=self.color_mode, value="gray").pack(side=tk.LEFT, padx=5)

        row += 1
        ttk.Label(params_frame, text="Тип материала:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        mf = ttk.Frame(params_frame)
        mf.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(mf, text="Standard", variable=self.material_mode, value="standard").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mf, text="Basic (unlit)", variable=self.material_mode, value="basic").pack(side=tk.LEFT, padx=5)

        row += 1
        ttk.Checkbutton(params_frame, text="Открыть GLB после конвертации",
                       variable=self.open_after_convert).grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=5)

        # Кнопки
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)
        self.convert_button = ttk.Button(btn_frame, text="Начать конвертацию", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)
        self.cancel_button = ttk.Button(btn_frame, text="Отмена", command=self.cancel_conversion, state='disabled')
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Детальные логи", command=self.log_window.toggle).pack(side=tk.LEFT, padx=5)

        # Прогресс
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress, maximum=100, length=400)
        self.progress_bar.grid(row=6, column=0, columnspan=3, pady=5, sticky=(tk.W, tk.E))

        self.status_label = ttk.Label(main_frame, textvariable=self.status, font=("Arial", 9), wraplength=550)
        self.status_label.grid(row=7, column=0, columnspan=3, pady=5)

        self.main_log = tk.Text(main_frame, height=8, width=70, state='disabled', wrap=tk.WORD)
        self.main_log.grid(row=8, column=0, columnspan=3, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(8, weight=1)

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.main_log.yview)
        scrollbar.grid(row=8, column=3, sticky=(tk.N, tk.S))
        self.main_log['yscrollcommand'] = scrollbar.set

        info_frame = ttk.LabelFrame(main_frame, text="Информация", padding="5")
        info_frame.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        info_text = (
            "Оптимизации: numpy-only voxel decimate (без np.unique), cKDTree, SVD PCA, "
            f"параллельный query ({N_CPU} ядер)\n"
            "Для 25M точек: децимируйте до 500K перед нормалями"
        )
        ttk.Label(info_frame, text=info_text, font=("Arial", 8), justify=tk.LEFT).grid(row=0, column=0, sticky=tk.W)

        self.update_status("Готов к работе")

    def select_input_file(self):
        file_path = filedialog.askopenfilename(
            title="Выберите LAS файл",
            filetypes=[("LAS files", "*.las *.laz"), ("All files", "*.*")]
        )
        if file_path:
            self.input_file.set(file_path)
            if not self.output_file.get():
                self.output_file.set(os.path.splitext(file_path)[0] + '.glb')
            self.update_status(f"Выбран: {os.path.basename(file_path)}")
            self.preview_las_info(file_path)

    def preview_las_info(self, file_path):
        try:
            self.log_window.clear_all()
            self.log_window.show()

            las = laspy.read(file_path)
            n_points = len(las.points)

            info = []
            info.append("=" * 60)
            info.append("ИНФОРМАЦИЯ О LAS ФАЙЛЕ")
            info.append("=" * 60)
            info.append(f"Файл: {file_path}")
            info.append(f"Версия LAS: {las.header.version}")
            info.append(f"Point format: {las.point_format.id}")
            info.append(f"Количество точек: {n_points:,}")
            info.append(f"Размер файла: {os.path.getsize(file_path) / (1024*1024):.1f} MB")
            info.append(f"Scale: X={las.header.scales[0]:.6f}, Y={las.header.scales[1]:.6f}, Z={las.header.scales[2]:.6f}")

            bbox = [las.x.min(), las.x.max(), las.y.min(), las.y.max(), las.z.min(), las.z.max()]
            info.append(f"\nBounding box:")
            info.append(f"  X: [{bbox[0]:.2f}, {bbox[1]:.2f}]")
            info.append(f"  Y: [{bbox[2]:.2f}, {bbox[3]:.2f}]")
            info.append(f"  Z: [{bbox[4]:.2f}, {bbox[5]:.2f}]")

            has_color = hasattr(las, 'red') and hasattr(las, 'green') and hasattr(las, 'blue')
            info.append(f"\nЦВЕТ: {'✅ ПРИСУТСТВУЕТ' if has_color else '❌ ОТСУТСТВУЕТ'}")

            if has_color:
                r = np.array(las.red)
                max_c = max(r.max(), np.array(las.green).max(), np.array(las.blue).max())
                info.append(f"  Битность: {'16-бит' if max_c > 255 else '8-бит'} (max={max_c})")

            info.append("\nРЕКОМЕНДАЦИИ:")
            if n_points > 10000000:
                info.append(f"  ⚠️ {n_points:,} точек — ОБЯЗАТЕЛЬНО децимируйте до 500K-1M")
                self.decimate_before.set(min(500000, n_points))
            elif n_points > 1000000:
                info.append(f"  ℹ️ {n_points:,} точек — рекомендуется децимация до 200K-500K")
            else:
                info.append(f"  ✅ {n_points:,} точек — можно без децимации")

            for line in info:
                self.log_window.log(line, "las")

            self.main_log_message("LAS проанализирован. См. 'Детальные логи'.")

        except Exception as e:
            self.log_window.log(f"Ошибка анализа: {e}", "las")
            self.main_log_message(f"Ошибка: {e}")

    def select_output_file(self):
        file_path = filedialog.asksaveasfilename(
            title="Сохранить GLB", defaultextension=".glb",
            filetypes=[("GLB files", "*.glb"), ("All files", "*.*")]
        )
        if file_path:
            self.output_file.set(file_path)
            self.update_status(f"Выходной: {os.path.basename(file_path)}")

    def update_status(self, message):
        self.status.set(message)
        self.root.update_idletasks()

    def main_log_message(self, message):
        self.main_log.config(state='normal')
        self.main_log.insert(tk.END, message + "\n")
        self.main_log.see(tk.END)
        self.main_log.config(state='disabled')
        self.root.update_idletasks()

    def update_progress(self, value):
        self.progress.set(value)
        self.root.update_idletasks()

    def show_error(self, message):
        self.root.after(0, lambda: messagebox.showerror("Ошибка", message))

    def show_success(self, message):
        self.root.after(0, lambda: messagebox.showinfo("Успех", message))

    def open_glb_file(self, file_path):
        try:
            self.main_log_message(f"Открытие: {file_path}")
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.run(["open", file_path], check=True)
            else:
                for viewer in [["xdg-open", file_path], ["gnome-open", file_path], ["kde-open", file_path]]:
                    try:
                        subprocess.run(viewer, check=True)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
            self.main_log_message("Файл открыт")
        except Exception as e:
            self.main_log_message(f"Не удалось открыть: {e}")

    def cancel_conversion(self):
        self._cancel_event.set()
        self.main_log_message("Отмена запрошена...")
        self.cancel_button.config(state='disabled')

    def start_conversion(self):
        if not self.input_file.get():
            messagebox.showerror("Ошибка", "Выберите входной LAS файл")
            return
        if not self.output_file.get():
            messagebox.showerror("Ошибка", "Укажите выходной GLB")
            return
        max_v = self.max_vertices.get()
        k_n = self.k_neighbors.get()
        dec = self.decimate_before.get()
        if max_v < 3:
            messagebox.showerror("Ошибка", "Макс. вершин >= 3")
            return
        if k_n < 3:
            messagebox.showerror("Ошибка", "Соседей >= 3")
            return
        if dec < max_v:
            self.decimate_before.set(max_v)
            self.main_log_message(f"Децимация скорректирована до {max_v}")

        self.log_window.clear_all()
        self.log_window.show()

        self.convert_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self._cancel_event.clear()
        self.update_status("Конвертация...")
        self.main_log.config(state='normal')
        self.main_log.delete(1.0, tk.END)
        self.main_log.config(state='disabled')
        self.progress.set(0)

        thread = threading.Thread(target=self.convert, daemon=True)
        thread.start()

    def _check_cancelled(self, msg=""):
        if self._cancel_event.is_set():
            raise InterruptedError(f"Отменено {msg}".strip())

    def convert(self):
        total_start = time.time()
        output_path = self.output_file.get()

        try:
            self.main_log_message("=== НАЧАЛО КОНВЕРТАЦИИ ===")
            self.update_progress(2)
            self._check_cancelled()

            # === 1. ЧТЕНИЕ LAS ===
            with Timer("Чтение LAS", self.log_window.log):
                self.main_log_message(f"Чтение: {self.input_file.get()}")
                points, colors, las_info = self.read_las_file(self.input_file.get())
                n_raw = len(points)
                self.main_log_message(f"Загружено {n_raw:,} точек")
                self.log_window.log(f"Исходных точек: {n_raw:,}", "perf")
            self.update_progress(10)
            self._check_cancelled()

            # === 2. ДЕЦИМАЦИЯ ===
            decimate_target = self.decimate_before.get()
            if n_raw > decimate_target:
                with Timer(f"Децимация", self.log_window.log):
                    self.main_log_message(f"Децимация: {n_raw:,} -> ~{decimate_target:,}...")
                    points, colors = self.fast_voxel_decimate_v2(points, colors, decimate_target)
                    self.main_log_message(f"После децимации: {len(points):,} точек")
                    self.log_window.log(f"После децимации: {len(points):,}", "perf")
            else:
                self.log_window.log(f"Децимация не нужна ({n_raw:,} <= {decimate_target:,})", "perf")
            self.update_progress(20)
            self._check_cancelled()

            # === 3. НОРМАЛИ ===
            with Timer("Нормали", self.log_window.log):
                self.main_log_message(f"Нормали для {len(points):,} точек...")
                normals = self.estimate_normals_fast(points, self.k_neighbors.get())
                self.main_log_message("Нормали готовы")
            self.update_progress(50)
            self._check_cancelled()

            # === 4. МЕШ ===
            with Timer("Меш", self.log_window.log):
                self.main_log_message("Построение меша...")
                points, triangles, colors, normals = self.build_mesh(
                    points, normals, colors, self.max_vertices.get()
                )
                self.main_log_message(f"Треугольников: {len(triangles):,}")
            self.update_progress(70)
            self._check_cancelled()

            # === 5. GLB ===
            with Timer("GLB", self.log_window.log):
                self.main_log_message(f"Сохранение: {output_path}")
                self.write_glb(points, triangles, colors, normals, output_path)
                self.main_log_message("GLB создан!")
            self.update_progress(100)

            total_time = time.time() - total_start
            self.log_window.log(f"\n=== ОБЩЕЕ ВРЕМЯ: {total_time:.1f} сек ===", "perf")

            self.update_status("Готово!")
            self.show_success(
                f"Конвертация завершена!\n\n"
                f"Исходных: {n_raw:,}\n"
                f"Вершин: {len(points):,}\n"
                f"Треугольников: {len(triangles):,}\n"
                f"Время: {total_time:.1f} сек"
            )

            if self.open_after_convert.get():
                self.open_glb_file(output_path)

        except InterruptedError:
            self.main_log_message("Отменено")
            self.update_status("Отменено")
        except Exception as e:
            error_msg = f"Ошибка: {str(e)}"
            self.main_log_message(error_msg)
            self.update_status("Ошибка")
            import traceback
            self.log_window.log(traceback.format_exc(), "general")
            self.show_error(f"{error_msg}\n\nСм. детальные логи.")
        finally:
            self.root.after(0, lambda: self.convert_button.config(state='normal'))
            self.root.after(0, lambda: self.cancel_button.config(state='disabled'))

    def read_las_file(self, file_path):
        try:
            las = laspy.read(file_path)
        except Exception as e:
            if file_path.lower().endswith('.laz'):
                raise Exception(f"LAZ требует lazrs: pip install lazrs\n{e}")
            raise

        # Читаем сразу в float32 для экономии памяти
        points = np.column_stack([las.x, las.y, las.z]).astype(np.float32)

        color_log = []
        color_log.append("=" * 60)
        color_log.append("ЧТЕНИЕ ЦВЕТА ИЗ LAS")
        color_log.append("=" * 60)

        has_red = hasattr(las, 'red')
        has_green = hasattr(las, 'green')
        has_blue = hasattr(las, 'blue')

        color_log.append(f"red={has_red}, green={has_green}, blue={has_blue}")

        if has_red and has_green and has_blue:
            raw_red = np.array(las.red)
            raw_green = np.array(las.green)
            raw_blue = np.array(las.blue)

            max_val = max(raw_red.max(), raw_green.max(), raw_blue.max())
            if max_val > 255:
                color_log.append(f"16-бит (max={max_val})")
                colors = np.column_stack([raw_red, raw_green, raw_blue]).astype(np.float32) / 65535.0
            else:
                color_log.append(f"8-бит (max={max_val})")
                colors = np.column_stack([raw_red, raw_green, raw_blue]).astype(np.float32) / 255.0

            colors = np.clip(colors, 0.0, 1.0)
            color_log.append(f"Нормализованные: min={colors.min():.4f}, max={colors.max():.4f}")
        else:
            color_log.append("⚠️ ЦВЕТ ОТСУТСТВУЕТ — серый")
            colors = np.full((len(points), 3), 0.5, dtype=np.float32)

        if self.color_mode.get() == "gray":
            color_log.append(">>> Режим 'Серый' <<<")
            gray = 0.299 * colors[:, 0] + 0.587 * colors[:, 1] + 0.114 * colors[:, 2]
            colors = np.column_stack([gray, gray, gray]).astype(np.float32)

        for line in color_log:
            self.log_window.log(line, "color")

        return points, colors, {}

    def fast_voxel_decimate_v2(self, points, colors, target_count):
        """Быстрая однопроходная воксельная децимация без np.unique.

        Алгоритм:
        1. Вычисляем voxel_size из target_count и bbox
        2. floor(points / voxel_size) -> voxel_coords
        3. Сортируем по voxel_coords и группируем через np.diff (O(n log n) однократно)
        4. Усредняем точки и цвета в каждом вокселе
        """
        import time
        n_points = len(points)
        if n_points <= target_count:
            return points, colors

        t0_total = time.time()
        self.log_window.log(f"  Начало децимации: {n_points:,} -> ~{target_count:,}", "perf")

        # === Шаг 1: Определяем voxel_size напрямую ===
        bbox = points.max(axis=0) - points.min(axis=0)
        bbox = np.where(bbox == 0, 1.0, bbox)  # защита от нулевых измерений
        volume = np.prod(bbox)

        # voxel_size = (volume / target_count)^(1/3) * коэффициент
        # Коэффициент ~1.5 чтобы гарантировать <= target_count
        #voxel_size = (volume / (target_count * 1.5)) ** (1/3)
        voxel_size = (volume / (target_count*100)) ** (1/3)
        voxel_size = max(voxel_size, 1e-6)  # защита от слишком маленького

        self.log_window.log(f"  voxel_size={voxel_size:.6f}, bbox={bbox}", "perf")

        # === Шаг 2: Вычисляем координаты вокселей ===
        t0 = time.time()
        voxel_coords = np.floor(points / voxel_size).astype(np.int32)
        self.log_window.log(f"  floor division: {time.time()-t0:.2f} сек", "perf")
        self._check_cancelled("(дécимация: floor)")

        # === Шаг 3: Сортируем по voxel_coords и группируем ===
        # Кодируем 3D координаты в 1D ключ для сортировки
        t0 = time.time()

        # Сдвигаем координаты в положительный диапазон
        min_coords = voxel_coords.min(axis=0)
        shifted = voxel_coords - min_coords

        # Создаём 1D ключ: x * Ymax * Zmax + y * Zmax + z
        # Используем int64 чтобы избежать переполнения
        max_shifted = shifted.max(axis=0) + 1
        keys = shifted[:, 0].astype(np.int64) * max_shifted[1] * max_shifted[2] + \
               shifted[:, 1].astype(np.int64) * max_shifted[2] + \
               shifted[:, 2].astype(np.int64)

        self.log_window.log(f"  Кодирование ключей: {time.time()-t0:.2f} сек", "perf")
        self._check_cancelled("(дécимация: кодирование)")

        # === Шаг 4: Сортируем по ключам ===
        t0 = time.time()
        sort_order = np.argsort(keys, kind='mergesort')  # mergesort - стабильный
        sorted_keys = keys[sort_order]
        sorted_points = points[sort_order]
        sorted_colors = colors[sort_order]

        self.log_window.log(f"  Сортировка: {time.time()-t0:.2f} сек", "perf")
        self._check_cancelled("(дécимация: сортировка)")

        # === Шаг 5: Находим границы групп ===
        t0 = time.time()
        diff = np.diff(sorted_keys)
        group_starts = np.concatenate([[0], np.where(diff != 0)[0] + 1])
        group_ends = np.concatenate([group_starts[1:], [len(sorted_keys)]])
        n_groups = len(group_starts)

        self.log_window.log(f"  Группировка: {time.time()-t0:.2f} сек, групп={n_groups:,}", "perf")
        self._check_cancelled("(дécимация: группировка)")

        # === Шаг 6: Усредняем точки и цвета в каждой группе ===
        t0 = time.time()

        new_points = np.zeros((n_groups, 3), dtype=np.float32)
        new_colors = np.zeros((n_groups, 3), dtype=np.float32)

        # Векторизованное усреднение через np.add.reduceat
        new_points[:, 0] = np.add.reduceat(sorted_points[:, 0], group_starts) / (group_ends - group_starts)
        new_points[:, 1] = np.add.reduceat(sorted_points[:, 1], group_starts) / (group_ends - group_starts)
        new_points[:, 2] = np.add.reduceat(sorted_points[:, 2], group_starts) / (group_ends - group_starts)

        new_colors[:, 0] = np.add.reduceat(sorted_colors[:, 0], group_starts) / (group_ends - group_starts)
        new_colors[:, 1] = np.add.reduceat(sorted_colors[:, 1], group_starts) / (group_ends - group_starts)
        new_colors[:, 2] = np.add.reduceat(sorted_colors[:, 2], group_starts) / (group_ends - group_starts)

        self.log_window.log(f"  Усреднение: {time.time()-t0:.2f} сек", "perf")

        # === Шаг 7: Если всё ещё больше target — случайное сэмплирование ===
        if len(new_points) > target_count:
            self.log_window.log(f"  Слишком много ({len(new_points):,}), случайное сэмплирование до {target_count:,}", "perf")
            indices = np.random.choice(len(new_points), target_count, replace=False)
            new_points = new_points[indices]
            new_colors = new_colors[indices]

        total_time = time.time() - t0_total
        self.log_window.log(f"  Итого децимация: {total_time:.2f} сек, результат: {len(new_points):,} точек", "perf")

        return new_points, np.clip(new_colors, 0.0, 1.0)

    def estimate_normals_fast(self, points, k_neighbors=15):
        """Быстрое вычисление нормалей через cKDTree + SVD."""
        n_points = len(points)
        k = min(k_neighbors + 1, n_points)

        self.log_window.log(f"  KDTree ({n_points:,} точек)...", "perf")
        t0 = time.time()
        tree = cKDTree(points)
        self.log_window.log(f"  KDTree построен: {time.time()-t0:.2f} сек", "perf")

        self.log_window.log(f"  Query {k} соседей...", "perf")
        t0 = time.time()
        distances, indices = tree.query(points, k=k, workers=-1)
        indices = indices[:, 1:]
        self.log_window.log(f"  Query готов: {time.time()-t0:.2f} сек", "perf")

        self.log_window.log(f"  PCA через SVD...", "perf")
        t0 = time.time()

        normals = np.zeros((n_points, 3), dtype=np.float32)
        batch_size = max(5000, n_points // 20)
        n_batches = (n_points + batch_size - 1) // batch_size

        for batch_idx in range(n_batches):
            self._check_cancelled(f"(нормали, батч {batch_idx+1}/{n_batches})")

            start = batch_idx * batch_size
            end = min(start + batch_size, n_points)
            batch_n = end - start

            # Собираем соседей
            neighbors = points[indices[start:end]]  # (batch_n, k-1, 3)

            # Центроиды
            centroids = np.mean(neighbors, axis=1, keepdims=True)  # (batch_n, 1, 3)
            centered = neighbors - centroids  # (batch_n, k-1, 3)

            # SVD для каждой точки
            for i in range(batch_n):
                try:
                    u, s, vt = np.linalg.svd(centered[i], full_matrices=False)
                    normal = vt[-1, :]
                    if normal[2] < 0:
                        normal = -normal
                    normals[start + i] = normal
                except np.linalg.LinAlgError:
                    normals[start + i] = [0, 0, 1]

            progress = 20 + ((batch_idx + 1) / n_batches) * 30
            self.update_progress(progress)

            if batch_idx % max(1, n_batches // 3) == 0:
                self.main_log_message(f"  Нормали: {end:,}/{n_points:,} ({end/n_points*100:.0f}%)")

        self.log_window.log(f"  PCA: {time.time()-t0:.2f} сек", "perf")
        return normals

    def build_mesh(self, points, normals, colors, max_vertices):
        if len(points) > max_vertices:
            self.main_log_message(f"Финальное упрощение: {len(points):,} -> {max_vertices:,}...")
            points, colors = self.fast_voxel_decimate_v2(points, colors, max_vertices)
            # Нормали тоже нужно пересчитать или сэмплировать
            # Для простоты: пересчитаем нормали для финальных точек
            normals = self.estimate_normals_fast(points, min(15, len(points)-1))
            self.main_log_message(f"После упрощения: {len(points):,}")

        if len(points) < 3:
            raise Exception("Недостаточно точек (минимум 3)")

        try:
            points_2d = points[:, :2]
            tri = Delaunay(points_2d)
            triangles = tri.simplices

            # Векторизованная фильтрация
            p1 = points[triangles[:, 0]]
            p2 = points[triangles[:, 1]]
            p3 = points[triangles[:, 2]]

            v1 = p2 - p1
            v2 = p3 - p1
            cross = np.cross(v1, v2)
            areas = 0.5 * np.linalg.norm(cross, axis=1)

            valid_mask = areas > 1e-10
            triangles = triangles[valid_mask]

            if len(triangles) == 0:
                self.main_log_message("Все треугольники вырождены, fan")
                triangles = self.build_simple_mesh(points)

        except Exception as e:
            self.main_log_message(f"Ошибка Delaunay: {e}, fan")
            triangles = self.build_simple_mesh(points)

        return points, triangles.astype(np.uint32), colors, normals

    def build_simple_mesh(self, points):
        n = len(points)
        if n < 3:
            return np.array([], dtype=np.uint32).reshape(0, 3)
        triangles = np.zeros((n - 2, 3), dtype=np.uint32)
        triangles[:, 0] = 0
        triangles[:, 1] = np.arange(1, n - 1)
        triangles[:, 2] = np.arange(2, n)
        return triangles

    def write_glb(self, points, triangles, colors, normals, output_path):
        if len(triangles) == 0:
            raise Exception("Нет треугольников!")

        vertex_count = len(points)
        triangle_count = len(triangles)
        colors = np.clip(colors, 0.0, 1.0)

        vertex_stride = 36  # pos(12) + normal(12) + color(12)

        vertex_data = np.zeros((vertex_count, 9), dtype=np.float32)
        vertex_data[:, 0:3] = points
        vertex_data[:, 3:6] = normals
        vertex_data[:, 6:9] = colors
        vertex_bytes = vertex_data.tobytes()

        index_data = triangles.astype(np.uint32).ravel()
        index_bytes = index_data.tobytes()

        vertex_buffer_size = len(vertex_bytes)
        index_buffer_size = len(index_bytes)

        bin_padding = (4 - index_buffer_size % 4) % 4
        if bin_padding > 0:
            index_bytes += b'\x00' * bin_padding

        total_buffer_size = vertex_buffer_size + len(index_bytes)

        gltf = {
            "asset": {"version": "2.0", "generator": "LAS to GLB Converter"},
            "scene": 0,
            "scenes": [{"nodes": [0], "name": "Scene"}],
            "nodes": [{"mesh": 0, "name": "Mesh"}],
            "meshes": [{
                "primitives": [{
                    "attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2},
                    "indices": 3, "mode": 4, "material": 0
                }],
                "name": "Mesh"
            }],
            "materials": [{
                "name": "Material",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0, "roughnessFactor": 0.8
                },
                "doubleSided": True, "alphaMode": "OPAQUE"
            }],
            "accessors": [
                {"bufferView": 0, "byteOffset": 0, "componentType": 5126, "count": vertex_count,
                 "type": "VEC3",
                 "max": [float(np.max(points[:, 0])), float(np.max(points[:, 1])), float(np.max(points[:, 2]))],
                 "min": [float(np.min(points[:, 0])), float(np.min(points[:, 1])), float(np.min(points[:, 2]))]},
                {"bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": vertex_count, "type": "VEC3"},
                {"bufferView": 0, "byteOffset": 24, "componentType": 5126, "count": vertex_count, "type": "VEC3"},
                {"bufferView": 1, "byteOffset": 0, "componentType": 5125, "count": triangle_count * 3, "type": "SCALAR"}
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": vertex_buffer_size, "target": 34962, "byteStride": vertex_stride},
                {"buffer": 0, "byteOffset": vertex_buffer_size, "byteLength": index_buffer_size, "target": 34963}
            ],
            "buffers": [{"byteLength": total_buffer_size}]
        }

        if self.material_mode.get() == "basic":
            gltf["materials"][0]["extensions"] = {"KHR_materials_unlit": {}}
            gltf["extensionsUsed"] = ["KHR_materials_unlit"]

        json_str = json.dumps(gltf, separators=(',', ':'))
        json_padding = (4 - len(json_str) % 4) % 4
        json_str += ' ' * json_padding
        json_bytes = json_str.encode('utf-8')

        json_chunk_len = len(json_bytes)
        bin_chunk_len = len(index_bytes) + vertex_buffer_size
        total_length = 12 + 8 + json_chunk_len + 8 + bin_chunk_len

        glb = bytearray()
        glb.extend(struct.pack('<I', 0x46546C67))
        glb.extend(struct.pack('<I', 2))
        glb.extend(struct.pack('<I', total_length))
        glb.extend(struct.pack('<I', json_chunk_len))
        glb.extend(struct.pack('<I', 0x4E4F534A))
        glb.extend(json_bytes)
        glb.extend(struct.pack('<I', bin_chunk_len))
        glb.extend(struct.pack('<I', 0x004E4942))
        glb.extend(vertex_bytes)
        glb.extend(index_bytes)

        with open(output_path, 'wb') as f:
            f.write(glb)

        self.main_log_message(f"GLB: {vertex_count:,} вершин, {triangle_count:,} треуг., {total_length/1024/1024:.1f} MB")


def main():
    root = tk.Tk()
    app = LASConverterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
