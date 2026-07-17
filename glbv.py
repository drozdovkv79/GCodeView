import numpy as np
import laspy
from scipy.spatial import Delaunay, KDTree
import os
import struct
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import threading
import subprocess
import platform
import warnings

warnings.filterwarnings('ignore')


class LogWindow:
    """Отдельное окно для детального логирования."""
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Детальные логи конвертации")
        self.window.geometry("900x700")
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        # Notebook для вкладок
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Вкладка: Общие логи
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="Общие логи")
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame, wrap=tk.WORD, font=("Consolas", 9)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Вкладка: Информация о LAS файле
        self.las_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.las_frame, text="Информация о LAS")
        self.las_text = scrolledtext.ScrolledText(
            self.las_frame, wrap=tk.WORD, font=("Consolas", 10)
        )
        self.las_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Вкладка: Информация о цвете
        self.color_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.color_frame, text="Анализ цвета")
        self.color_text = scrolledtext.ScrolledText(
            self.color_frame, wrap=tk.WORD, font=("Consolas", 10)
        )
        self.color_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Вкладка: GLB структура
        self.glb_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.glb_frame, text="GLB структура")
        self.glb_text = scrolledtext.ScrolledText(
            self.glb_frame, wrap=tk.WORD, font=("Consolas", 9)
        )
        self.glb_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Кнопки
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="Очистить", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Скрыть", command=self.hide).pack(side=tk.LEFT, padx=5)

        self.hidden = False

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.hidden = False

    def hide(self):
        self.window.withdraw()
        self.hidden = True

    def toggle(self):
        if self.hidden:
            self.show()
        else:
            self.hide()

    def log(self, message, tag="general"):
        if tag == "las":
            target = self.las_text
        elif tag == "color":
            target = self.color_text
        elif tag == "glb":
            target = self.glb_text
        else:
            target = self.log_text

        target.config(state='normal')
        target.insert(tk.END, str(message) + "\n")
        target.see(tk.END)
        target.config(state='disabled')

    def clear_all(self):
        for widget in [self.log_text, self.las_text, self.color_text, self.glb_text]:
            widget.config(state='normal')
            widget.delete(1.0, tk.END)
            widget.config(state='disabled')


class LASConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Конвертер LAS в цветной GLB")
        self.root.geometry("650x550")
        self.root.resizable(True, True)

        # Переменные
        self.input_file = tk.StringVar()
        self.output_file = tk.StringVar()
        self.max_vertices = tk.IntVar(value=50000)
        self.k_neighbors = tk.IntVar(value=20)
        self.open_after_convert = tk.BooleanVar(value=True)
        self.color_mode = tk.StringVar(value="color")
        self.material_mode = tk.StringVar(value="standard")
        self.status = tk.StringVar(value="Готов к работе")
        self.progress = tk.DoubleVar(value=0)

        self._cancel_event = threading.Event()
        self._las_colors_raw = None  # Сырые цвета из LAS
        self._las_colors_normalized = None  # Нормализованные цвета

        # Окно логов
        self.log_window = LogWindow(root)
        self.log_window.hide()

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="Конвертер LAS в цветной GLB",
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=10)

        # Входной файл
        ttk.Label(main_frame, text="Входной LAS файл:", font=("Arial", 10)).grid(
            row=1, column=0, sticky=tk.W, pady=5)
        self.input_entry = ttk.Entry(main_frame, textvariable=self.input_file, width=50)
        self.input_entry.grid(row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_input_file).grid(
            row=1, column=2, padx=5, pady=5)

        # Выходной файл
        ttk.Label(main_frame, text="Выходной GLB файл:", font=("Arial", 10)).grid(
            row=2, column=0, sticky=tk.W, pady=5)
        self.output_entry = ttk.Entry(main_frame, textvariable=self.output_file, width=50)
        self.output_entry.grid(row=2, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_output_file).grid(
            row=2, column=2, padx=5, pady=5)

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # Параметры
        params_frame = ttk.LabelFrame(main_frame, text="Параметры конвертации", padding="10")
        params_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        params_frame.columnconfigure(1, weight=1)

        ttk.Label(params_frame, text="Макс. вершин:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=1000000, textvariable=self.max_vertices, width=15).grid(
            row=0, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(упрощение меша)").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)

        ttk.Label(params_frame, text="Соседей для нормалей:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=100, textvariable=self.k_neighbors, width=15).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(качество нормалей)").grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)

        ttk.Label(params_frame, text="Цветовой режим:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        color_frame = ttk.Frame(params_frame)
        color_frame.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(color_frame, text="Цветной (из LAS)", variable=self.color_mode, value="color").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(color_frame, text="Серый", variable=self.color_mode, value="gray").pack(side=tk.LEFT, padx=5)

        ttk.Label(params_frame, text="Тип материала:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        material_frame = ttk.Frame(params_frame)
        material_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        ttk.Radiobutton(material_frame, text="Standard", variable=self.material_mode, value="standard").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(material_frame, text="Basic (unlit)", variable=self.material_mode, value="basic").pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(params_frame, text="Открыть GLB после конвертации",
                       variable=self.open_after_convert).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=5)

        # Кнопки
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)

        self.convert_button = ttk.Button(btn_frame, text="Начать конвертацию", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)

        self.cancel_button = ttk.Button(btn_frame, text="Отмена", command=self.cancel_conversion, state='disabled')
        self.cancel_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="Детальные логи", command=self.log_window.toggle).pack(side=tk.LEFT, padx=5)

        # Прогресс и статус
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress, maximum=100, length=400)
        self.progress_bar.grid(row=6, column=0, columnspan=3, pady=5, sticky=(tk.W, tk.E))

        self.status_label = ttk.Label(main_frame, textvariable=self.status, font=("Arial", 9), wraplength=550)
        self.status_label.grid(row=7, column=0, columnspan=3, pady=5)

        # Лог в главном окне
        self.main_log = tk.Text(main_frame, height=8, width=70, state='disabled', wrap=tk.WORD)
        self.main_log.grid(row=8, column=0, columnspan=3, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(8, weight=1)

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.main_log.yview)
        scrollbar.grid(row=8, column=3, sticky=(tk.N, tk.S))
        self.main_log['yscrollcommand'] = scrollbar.set

        # Инфо
        info_frame = ttk.LabelFrame(main_frame, text="Информация", padding="5")
        info_frame.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        info_text = (
            "Поддерживаемые форматы: .las, .laz (требуется lazrs)\n"
            "GLB: interleaved vertices [pos+normal+color], цвет через COLOR_0 attribute"
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
            self.update_status(f"Выбран файл: {os.path.basename(file_path)}")
            # Предварительный анализ LAS
            self.preview_las_info(file_path)

    def preview_las_info(self, file_path):
        """Предварительный анализ LAS файла без конвертации."""
        try:
            self.log_window.clear_all()
            self.log_window.show()

            las = laspy.read(file_path)

            info = []
            info.append("=" * 60)
            info.append("ИНФОРМАЦИЯ О LAS ФАЙЛЕ")
            info.append("=" * 60)
            info.append(f"Файл: {file_path}")
            info.append(f"Версия LAS: {las.header.version}")
            info.append(f"Количество точек: {len(las.points):,}")
            info.append(f"Точность (scale): X={las.header.scales[0]}, Y={las.header.scales[1]}, Z={las.header.scales[2]}")
            info.append(f"Смещение (offset): X={las.header.offsets[0]}, Y={las.header.offsets[1]}, Z={las.header.offsets[2]}")
            info.append("")
            info.append("Доступные dimensions (поля):")
            for dim in las.point_format.dimensions:
                info.append(f"  - {dim.name}: тип={dim.dtype}")
            info.append("")

            # Проверка цвета
            has_red = hasattr(las, 'red')
            has_green = hasattr(las, 'green')
            has_blue = hasattr(las, 'blue')

            info.append("ЦВЕТОВЫЕ ДАННЫЕ:")
            info.append(f"  red: {'ПРИСУТСТВУЕТ' if has_red else 'ОТСУТСТВУЕТ'}")
            info.append(f"  green: {'ПРИСУТСТВУЕТ' if has_green else 'ОТСУТСТВУЕТ'}")
            info.append(f"  blue: {'ПРИСУТСТВУЕТ' if has_blue else 'ОТСУТСТВУЕТ'}")

            if has_red and has_green and has_blue:
                red_vals = np.array(las.red)
                green_vals = np.array(las.green)
                blue_vals = np.array(las.blue)

                info.append("")
                info.append("СТАТИСТИКА ЦВЕТОВ (сырые значения из LAS):")
                info.append(f"  RED:   min={red_vals.min()}, max={red_vals.max()}, mean={red_vals.mean():.2f}")
                info.append(f"  GREEN: min={green_vals.min()}, max={green_vals.max()}, mean={green_vals.mean():.2f}")
                info.append(f"  BLUE:  min={blue_vals.min()}, max={blue_vals.max()}, mean={blue_vals.mean():.2f}")
                info.append(f"  Уникальных значений RED: {len(np.unique(red_vals))}")

                # Определяем битность
                max_color = max(red_vals.max(), green_vals.max(), blue_vals.max())
                if max_color > 255:
                    info.append(f"  Битность: 16-бит (0-65535), max={max_color}")
                else:
                    info.append(f"  Битность: 8-бит (0-255), max={max_color}")

                # Примеры цветов
                info.append("")
                info.append("ПЕРВЫЕ 10 ТОЧЕК (сырые RGB):")
                for i in range(min(10, len(las.points))):
                    info.append(f"  Точка {i}: R={las.red[i]}, G={las.green[i]}, B={las.blue[i]}")
            else:
                info.append("\n⚠️ ЦВЕТОВЫЕ ДАННЫЕ ОТСУТСТВУЮТ! GLB будет серым.")

            # Проверка intensity
            if hasattr(las, 'intensity'):
                info.append("")
                info.append(f"Intensity: min={las.intensity.min()}, max={las.intensity.max()}")

            # Проверка classification
            if hasattr(las, 'classification'):
                classes = np.unique(las.classification)
                info.append("")
                info.append(f"Классификации: {classes}")

            for line in info:
                self.log_window.log(line, "las")

            self.main_log_message("LAS файл проанализирован. Откройте 'Детальные логи' для подробностей.")

        except Exception as e:
            self.log_window.log(f"Ошибка анализа LAS: {e}", "las")
            self.main_log_message(f"Ошибка анализа: {e}")

    def select_output_file(self):
        file_path = filedialog.asksaveasfilename(
            title="Сохранить GLB файл как",
            defaultextension=".glb",
            filetypes=[("GLB files", "*.glb"), ("All files", "*.*")]
        )
        if file_path:
            self.output_file.set(file_path)
            self.update_status(f"Выходной файл: {os.path.basename(file_path)}")

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
            self.main_log_message(f"Открытие файла: {file_path}")
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.run(["open", file_path], check=True)
            else:
                viewers = [["xdg-open", file_path], ["gnome-open", file_path], ["kde-open", file_path]]
                for viewer in viewers:
                    try:
                        subprocess.run(viewer, check=True)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    self.main_log_message("Не найден подходящий просмотрщик файлов")
                    return
            self.main_log_message("Файл открыт")
        except Exception as e:
            self.main_log_message(f"Не удалось открыть файл: {e}")

    def cancel_conversion(self):
        self._cancel_event.set()
        self.main_log_message("Запрошена отмена...")
        self.cancel_button.config(state='disabled')

    def start_conversion(self):
        if not self.input_file.get():
            messagebox.showerror("Ошибка", "Выберите входной LAS файл")
            return
        if not self.output_file.get():
            messagebox.showerror("Ошибка", "Укажите выходной GLB файл")
            return
        max_v = self.max_vertices.get()
        k_n = self.k_neighbors.get()
        if max_v < 3:
            messagebox.showerror("Ошибка", "Макс. вершин должно быть >= 3")
            return
        if k_n < 3:
            messagebox.showerror("Ошибка", "Соседей должно быть >= 3")
            return

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

    def _check_cancelled(self):
        if self._cancel_event.is_set():
            raise InterruptedError("Отменено")

    def convert(self):
        output_path = self.output_file.get()
        try:
            self.main_log_message("Начинаем конвертацию...")
            self.log_window.log("=== НАЧАЛО КОНВЕРТАЦИИ ===", "general")
            self.update_progress(5)
            self._check_cancelled()

            # Чтение LAS
            self.main_log_message(f"Чтение LAS: {self.input_file.get()}")
            points, colors, las_info = self.read_las_file(self.input_file.get())
            self.main_log_message(f"Загружено {len(points)} точек")
            self.update_progress(15)
            self._check_cancelled()

            # Нормали
            self.main_log_message("Вычисление нормалей...")
            normals = self.estimate_normals(points, self.k_neighbors.get())
            self.main_log_message("Нормали готовы")
            self.update_progress(35)
            self._check_cancelled()

            # Меш
            self.main_log_message("Построение меша...")
            points, triangles, colors, normals = self.build_mesh(points, normals, colors, self.max_vertices.get())
            self.main_log_message(f"Треугольников: {len(triangles)}")
            self.update_progress(55)
            self._check_cancelled()

            # Логирование цвета перед записью
            self.log_color_info(points, colors, "ЦВЕТ ПЕРЕД ЗАПИСЬЮ В GLB")

            # Запись GLB
            self.main_log_message(f"Сохранение GLB: {output_path}")
            self.write_glb(points, triangles, colors, normals, output_path)
            self.main_log_message("GLB создан!")
            self.update_progress(100)

            self.update_status("Готово!")
            self.show_success(
                f"Конвертация завершена!\n\n"
                f"Вершин: {len(points)}\n"
                f"Треугольников: {len(triangles)}"
            )

            if self.open_after_convert.get():
                self.open_glb_file(output_path)

        except InterruptedError:
            self.main_log_message("Отменено пользователем")
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
        """Чтение LAS с детальным логированием цвета."""
        try:
            las = laspy.read(file_path)
        except Exception as e:
            if file_path.lower().endswith('.laz'):
                raise Exception(f"Не удалось прочитать LAZ. Установите: pip install lazrs\n{e}")
            raise

        points = np.vstack((las.x, las.y, las.z)).transpose().astype(np.float64)

        # === ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ЦВЕТА ===
        color_log = []
        color_log.append("=" * 60)
        color_log.append("ЧТЕНИЕ ЦВЕТА ИЗ LAS ФАЙЛА")
        color_log.append("=" * 60)

        has_red = hasattr(las, 'red')
        has_green = hasattr(las, 'green')
        has_blue = hasattr(las, 'blue')

        color_log.append(f"red dimension: {has_red}")
        color_log.append(f"green dimension: {has_green}")
        color_log.append(f"blue dimension: {has_blue}")

        if has_red and has_green and has_blue:
            raw_red = np.array(las.red)
            raw_green = np.array(las.green)
            raw_blue = np.array(las.blue)

            self._las_colors_raw = np.column_stack([raw_red, raw_green, raw_blue])

            color_log.append(f"\nСЫРЫЕ ЗНАЧЕНИЯ (первые 20 точек):")
            for i in range(min(20, len(raw_red))):
                color_log.append(f"  [{i:4d}] R={raw_red[i]:6d} G={raw_green[i]:6d} B={raw_blue[i]:6d}")

            color_log.append(f"\nСТАТИСТИКА СЫРЫХ ЗНАЧЕНИЙ:")
            color_log.append(f"  RED:   min={raw_red.min():6d}, max={raw_red.max():6d}, mean={raw_red.mean():.2f}")
            color_log.append(f"  GREEN: min={raw_green.min():6d}, max={raw_green.max():6d}, mean={raw_green.mean():.2f}")
            color_log.append(f"  BLUE:  min={raw_blue.min():6d}, max={raw_blue.max():6d}, mean={raw_blue.mean():.2f}")

            # Определяем битность и нормализуем
            max_val = max(raw_red.max(), raw_green.max(), raw_blue.max())
            if max_val > 255:
                color_log.append(f"\nОпределена битность: 16-бит (max={max_val})")
                color_log.append(f"Нормализация: делим на 65535.0")
                colors = np.column_stack([raw_red, raw_green, raw_blue]).astype(np.float32) / 65535.0
            else:
                color_log.append(f"\nОпределена битность: 8-бит (max={max_val})")
                color_log.append(f"Нормализация: делим на 255.0")
                colors = np.column_stack([raw_red, raw_green, raw_blue]).astype(np.float32) / 255.0

            colors = np.clip(colors, 0.0, 1.0)
            self._las_colors_normalized = colors.copy()

            color_log.append(f"\nНОРМАЛИЗОВАННЫЕ ЦВЕТА [0-1] (первые 20 точек):")
            for i in range(min(20, len(colors))):
                color_log.append(f"  [{i:4d}] R={colors[i,0]:.4f} G={colors[i,1]:.4f} B={colors[i,2]:.4f}")

            color_log.append(f"\nСТАТИСТИКА НОРМАЛИЗОВАННЫХ ЦВЕТОВ:")
            color_log.append(f"  RED:   min={colors[:,0].min():.4f}, max={colors[:,0].max():.4f}, mean={colors[:,0].mean():.4f}")
            color_log.append(f"  GREEN: min={colors[:,1].min():.4f}, max={colors[:,1].max():.4f}, mean={colors[:,1].mean():.4f}")
            color_log.append(f"  BLUE:  min={colors[:,2].min():.4f}, max={colors[:,2].max():.4f}, mean={colors[:,2].mean():.4f}")

            # Проверка на монохромность
            if np.allclose(colors[:,0], colors[:,1]) and np.allclose(colors[:,1], colors[:,2]):
                color_log.append("\n⚠️ ВНИМАНИЕ: Все цвета примерно одинаковые (монохромные)!")

            # Проверка на нулевые цвета
            if colors.max() < 0.01:
                color_log.append("\n⚠️ ВНИМАНИЕ: Все цвета близки к нулю (чёрные)!")

        else:
            color_log.append("\n⚠️ ЦВЕТОВЫЕ ДАННЫЕ ОТСУТСТВУЮТ!")
            color_log.append("Используем серый цвет (0.5, 0.5, 0.5)")
            colors = np.ones((len(points), 3), dtype=np.float32) * 0.5

        # Серый режим
        if self.color_mode.get() == "gray":
            color_log.append("\n>>> Режим 'Серый' активирован <<<")
            gray = 0.299 * colors[:, 0] + 0.587 * colors[:, 1] + 0.114 * colors[:, 2]
            colors = np.column_stack([gray, gray, gray]).astype(np.float32)
            color_log.append(f"Первые 10 серых значений: {colors[:10, 0]}")

        for line in color_log:
            self.log_window.log(line, "color")

        # Инфо о LAS для return
        las_info = {
            'version': str(las.header.version),
            'point_count': len(las.points),
            'has_color': has_red and has_green and has_blue,
            'dimensions': [d.name for d in las.point_format.dimensions]
        }

        return points, colors, las_info

    def log_color_info(self, points, colors, title):
        """Логирование информации о цвете в любой момент."""
        info = []
        info.append("=" * 60)
        info.append(title)
        info.append("=" * 60)
        info.append(f"Количество вершин: {len(colors)}")
        info.append(f"Форма массива цветов: {colors.shape}")
        info.append(f"Тип данных: {colors.dtype}")
        info.append(f"Min: [{colors[:,0].min():.4f}, {colors[:,1].min():.4f}, {colors[:,2].min():.4f}]")
        info.append(f"Max: [{colors[:,0].max():.4f}, {colors[:,1].max():.4f}, {colors[:,2].max():.4f}]")
        info.append(f"Mean: [{colors[:,0].mean():.4f}, {colors[:,1].mean():.4f}, {colors[:,2].mean():.4f}]")
        info.append(f"Первые 10 цветов:")
        for i in range(min(10, len(colors))):
            info.append(f"  [{i}] ({points[i,0]:.2f}, {points[i,1]:.2f}, {points[i,2]:.2f}) -> "
                       f"RGB=({colors[i,0]:.4f}, {colors[i,1]:.4f}, {colors[i,2]:.4f})")

        # Проверка на NaN/Inf
        has_nan = np.isnan(colors).any()
        has_inf = np.isinf(colors).any()
        if has_nan:
            info.append("⚠️ Обнаружены NaN в цветах!")
        if has_inf:
            info.append("⚠️ Обнаружены Inf в цветах!")

        for line in info:
            self.log_window.log(line, "color")

    def estimate_normals(self, points, k_neighbors=20):
        n_points = len(points)
        k = min(k_neighbors + 1, n_points)
        tree = KDTree(points)
        distances, indices = tree.query(points, k=k)
        indices = indices[:, 1:]

        normals = np.zeros_like(points, dtype=np.float32)

        for i in range(n_points):
            neighbors = points[indices[i]]
            centroid = np.mean(neighbors, axis=0)
            centered = neighbors - centroid
            cov = np.cov(centered.T)
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            normal = eigenvectors[:, 0]
            if normal[2] < 0:
                normal = -normal
            normals[i] = normal

            if i % 5000 == 0 and i > 0:
                self._check_cancelled()
                progress = 15 + (i / n_points) * 20
                self.update_progress(progress)

        return normals

    def voxel_downsample(self, points, colors, normals, voxel_size=None):
        if voxel_size is None:
            bbox = points.max(axis=0) - points.min(axis=0)
            volume = np.prod(bbox)
            max_v = self.max_vertices.get()
            voxel_size = (volume / max_v) ** (1/3) if volume > 0 else 1.0

        voxel_coords = np.floor(points / voxel_size).astype(np.int32)
        unique_voxels, inverse, counts = np.unique(
            voxel_coords, axis=0, return_inverse=True, return_counts=True
        )

        n_unique = len(unique_voxels)
        new_points = np.zeros((n_unique, 3), dtype=np.float32)
        new_colors = np.zeros((n_unique, 3), dtype=np.float32)
        new_normals = np.zeros((n_unique, 3), dtype=np.float32)

        np.add.at(new_points, inverse, points)
        np.add.at(new_colors, inverse, colors)
        np.add.at(new_normals, inverse, normals)

        new_points /= counts[:, None]
        new_colors /= counts[:, None]
        new_normals /= counts[:, None]

        norms = np.linalg.norm(new_normals, axis=1, keepdims=True)
        norms[norms == 0] = 1
        new_normals /= norms

        return new_points, new_colors, new_normals

    def build_mesh(self, points, normals, colors, max_vertices):
        if len(points) > max_vertices:
            self.main_log_message(f"Упрощение: {len(points)} -> ~{max_vertices}...")
            points, colors, normals = self.voxel_downsample(points, colors, normals)
            self.main_log_message(f"После voxel: {len(points)} вершин")

            if len(points) > max_vertices:
                indices = np.random.choice(len(points), max_vertices, replace=False)
                points = points[indices]
                normals = normals[indices]
                colors = colors[indices]

        if len(points) < 3:
            raise Exception("Недостаточно точек (минимум 3)")

        try:
            points_2d = points[:, :2]
            tri = Delaunay(points_2d)
            triangles = tri.simplices

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
                self.main_log_message("Все треугольники вырождены, используем fan")
                triangles = self.build_simple_mesh(points)

        except Exception as e:
            self.main_log_message(f"Ошибка триангуляции: {e}, используем fan")
            triangles = self.build_simple_mesh(points)

        return points.astype(np.float32), triangles.astype(np.uint32), colors.astype(np.float32), normals.astype(np.float32)

    def build_simple_mesh(self, points):
        n_points = len(points)
        if n_points < 3:
            return np.array([], dtype=np.uint32).reshape(0, 3)

        triangles = np.zeros((n_points - 2, 3), dtype=np.uint32)
        triangles[:, 0] = 0
        triangles[:, 1] = np.arange(1, n_points - 1)
        triangles[:, 2] = np.arange(2, n_points)
        return triangles

    def write_glb(self, points, triangles, colors, normals, output_path):
        """Запись GLB с корректными цветами."""
        if len(triangles) == 0:
            raise Exception("Нет треугольников!")

        vertex_count = len(points)
        triangle_count = len(triangles)

        # === КРИТИЧЕСКИ ВАЖНО: проверяем цвета перед записью ===
        self.log_color_info(points, colors, "ЦВЕТ ПЕРЕД ЗАПИСЬЮ В GLB (финальная проверка)")

        # Убеждаемся, что цвета в правильном диапазоне [0, 1]
        colors = np.clip(colors, 0.0, 1.0)

        # Interleaved vertex: [pos(12b) + normal(12b) + color(12b)] = 36 bytes
        vertex_stride = 36

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

        # === ЛОГИРОВАНИЕ СТРУКТУРЫ GLB ===
        glb_log = []
        glb_log.append("=" * 60)
        glb_log.append("СТРУКТУРА GLB ФАЙЛА")
        glb_log.append("=" * 60)
        glb_log.append(f"Вершин: {vertex_count}")
        glb_log.append(f"Треугольников: {triangle_count}")
        glb_log.append(f"Размер вершины: {vertex_stride} bytes")
        glb_log.append(f"Vertex buffer size: {vertex_buffer_size} bytes")
        glb_log.append(f"Index buffer size: {index_buffer_size} bytes")
        glb_log.append(f"Total buffer size: {total_buffer_size} bytes")
        glb_log.append("")
        glb_log.append("Vertex layout (interleaved):")
        glb_log.append("  [0-11]:   POSITION (3 x float32)")
        glb_log.append("  [12-23]:  NORMAL   (3 x float32)")
        glb_log.append("  [24-35]:  COLOR_0  (3 x float32)")
        glb_log.append("")
        glb_log.append("Accessors:")
        glb_log.append("  [0] POSITION: bufferView=0, byteOffset=0, count={}".format(vertex_count))
        glb_log.append("  [1] NORMAL:   bufferView=0, byteOffset=12, count={}".format(vertex_count))
        glb_log.append("  [2] COLOR_0:  bufferView=0, byteOffset=24, count={}".format(vertex_count))
        glb_log.append("  [3] INDICES:  bufferView=1, byteOffset=0, count={}".format(triangle_count * 3))
        glb_log.append("")
        glb_log.append("Первые 5 вершин (hex dump позиций):")
        for i in range(min(5, vertex_count)):
            pos_hex = vertex_bytes[i*36:i*36+12].hex()
            col_hex = vertex_bytes[i*36+24:i*36+36].hex()
            glb_log.append(f"  [{i}] pos_bytes={pos_hex}, color_bytes={col_hex}")
            glb_log.append(f"       pos=({points[i,0]:.3f},{points[i,1]:.3f},{points[i,2]:.3f}), "
                          f"color=({colors[i,0]:.4f},{colors[i,1]:.4f},{colors[i,2]:.4f})")

        for line in glb_log:
            self.log_window.log(line, "glb")

        # GLTF JSON
        gltf = {
            "asset": {"version": "2.0", "generator": "LAS to GLB Converter"},
            "scene": 0,
            "scenes": [{"nodes": [0], "name": "Scene"}],
            "nodes": [{"mesh": 0, "name": "Mesh"}],
            "meshes": [{
                "primitives": [{
                    "attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2},
                    "indices": 3,
                    "mode": 4,
                    "material": 0
                }],
                "name": "Mesh"
            }],
            "materials": [{
                "name": "Material",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8
                },
                "doubleSided": True,
                "alphaMode": "OPAQUE"
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

        self.main_log_message(f"GLB создан: {vertex_count} вершин, {triangle_count} треугольников")
        self.log_window.log(f"\nФайл сохранён: {output_path} ({total_length} bytes)", "glb")

        self.validate_glb(output_path)

    def validate_glb(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                magic = struct.unpack('<I', f.read(4))[0]
                version = struct.unpack('<I', f.read(4))[0]
                length = struct.unpack('<I', f.read(4))[0]

                file_size = os.path.getsize(file_path)
                if length != file_size:
                    self.log_window.log(f"⚠️ Длина в заголовке ({length}) != реальному размеру ({file_size})", "glb")
                    return

                chunk_len = struct.unpack('<I', f.read(4))[0]
                chunk_type = struct.unpack('<I', f.read(4))[0]

                if chunk_type != 0x4E4F534A:
                    self.log_window.log("⚠️ Первый чанк не JSON", "glb")
                    return

                json_data = f.read(chunk_len).decode('utf-8')
                gltf_data = json.loads(json_data)

                # Проверяем наличие COLOR_0
                has_color = False
                if 'meshes' in gltf_data and len(gltf_data['meshes']) > 0:
                    prim = gltf_data['meshes'][0]['primitives'][0]
                    attrs = prim.get('attributes', {})
                    has_color = 'COLOR_0' in attrs

                self.log_window.log(f"\nВалидация GLB:", "glb")
                self.log_window.log(f"  Версия: {version}", "glb")
                self.log_window.log(f"  Размер: {length} bytes", "glb")
                self.log_window.log(f"  COLOR_0 присутствует: {has_color}", "glb")

                if not has_color:
                    self.log_window.log("  ⚠️ COLOR_0 ОТСУТСТВУЕТ В GLTF!", "glb")
                else:
                    self.log_window.log("  ✅ COLOR_0 найден в mesh attributes", "glb")

                self.log_window.log("  ✅ GLB валиден", "glb")

        except Exception as e:
            self.log_window.log(f"Ошибка валидации: {e}", "glb")


def main():
    root = tk.Tk()
    app = LASConverterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
