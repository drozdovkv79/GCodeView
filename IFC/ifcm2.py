import os
import threading
import time
import tkinter as tk
from collections import Counter
from tkinter import filedialog, scrolledtext, ttk

import ifcopenshell
import ifcopenshell.guid


class IFCMergerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("IFC Merger Pro (macOS)")
        self.root.geometry("800x600")

        # Настройка стиля
        style = ttk.Style()
        if "aqua" in style.theme_names():
            style.theme_use("aqua")

        # Панель управления
        control_frame = ttk.Frame(root, padding="15")
        control_frame.pack(fill=tk.X, side=tk.TOP)

        self.btn_select = ttk.Button(
            control_frame,
            text="Выбрать каталог и объединить",
            command=self.select_folder_and_start,
        )
        self.btn_select.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(
            control_frame, orient=tk.HORIZONTAL, mode="determinate"
        )
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # Окно вывода логов и статистики
        log_frame = ttk.Frame(root, padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_area = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Menlo", 12), bg="#000000"
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def log(self, message):
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_area.insert(tk.END, f"{message}\n")
        self.log_area.see(tk.END)

    def select_folder_and_start(self):
        folder_path = filedialog.askdirectory(title="Выберите каталог с IFC файлами")
        if not folder_path:
            return

        self.log_area.delete(1.0, tk.END)
        self.btn_select.config(state=tk.DISABLED)

        threading.Thread(
            target=self.process_ifc_files, args=(folder_path,), daemon=True
        ).start()

    def get_stats(self, elements):
        """Считает количество объектов по их типам (IfcWall, IfcWindow и т.д.)"""
        types = [el.is_a() for el in elements]
        return Counter(types)

    def process_ifc_files(self, folder_path):
        start_time_all = time.time()

        # Поиск файлов (исключаем возможный старый результат)
        ifc_files = [
            f
            for f in os.listdir(folder_path)
            if f.lower().endswith(".ifc") and "Merged_Final" not in f
        ]
        ifc_files.sort()

        if len(ifc_files) < 2:
            self.log("❌ ОШИБКА: Нужно минимум 2 файла для объединения.")
            self.root.after(0, lambda: self.btn_select.config(state=tk.NORMAL))
            return

        self.log(f"🚀 Найдено файлов: {len(ifc_files)}")
        self.root.after(
            0, lambda: self.progress.config(maximum=len(ifc_files), value=0)
        )

        try:
            # 1. Загрузка базовой модели
            base_file_name = ifc_files[0]
            self.log(f"📦 Загрузка базовой модели: {base_file_name}...")
            t0 = time.time()
            base_model = ifcopenshell.open(os.path.join(folder_path, base_file_name))

            # Поиск структуры
            storeys = base_model.by_type("IfcBuildingStorey")
            target_parent = (
                storeys[0] if storeys else base_model.by_type("IfcProject")[0]
            )

            self.log(
                f"✅ База загружена ({time.time() - t0:.2f}с). Контейнер: {target_parent.Name}"
            )
            self.root.after(0, lambda: self.progress.config(value=1))

            # 2. Объединение остальных файлов
            for i in range(1, len(ifc_files)):
                current_file = ifc_files[i]
                self.log(
                    f"\n--- Обработка [{i + 1}/{len(ifc_files)}]: {current_file} ---"
                )

                t_file_start = time.time()
                new_model = ifcopenshell.open(os.path.join(folder_path, current_file))

                # Фильтруем физические объекты (исключаем пространственные, чтобы не сместить координаты)
                products = [
                    p
                    for p in new_model.by_type("IfcProduct")
                    if not p.is_a("IfcSpatialElement")
                ]

                # Сбор статистики
                stats = self.get_stats(products)
                self.log(f"📊 Статистика элементов:")
                for e_type, count in sorted(stats.items()):
                    self.log(f"   - {e_type}: {count}")

                # Добавление в общую модель
                added_products = []
                for prod in products:
                    try:
                        new_prod = base_model.add(prod)
                        added_products.append(new_prod)
                    except:
                        continue

                # Создание связи (Spatial Structure) с использованием актуального guid.new()
                if added_products:
                    base_model.create_entity(
                        "IfcRelContainedInSpatialStructure",
                        GlobalId=ifcopenshell.guid.new(),
                        Name="Merged_Data",
                        RelatingStructure=target_parent,
                        RelatedElements=added_products,
                    )

                self.log(
                    f"⏱ Время обработки файла: {time.time() - t_file_start:.2f} сек."
                )
                self.root.after(0, lambda v=i + 1: self.progress.config(value=v))

            # 3. Сохранение результата
            self.log(f"\n💾 Сохранение итогового файла...")
            out_name = "Merged_Final.ifc"
            out_path = os.path.join(folder_path, out_name)

            t_save = time.time()
            base_model.write(out_path)

            total_time = time.time() - start_time_all
            self.log(f"✅ УСПЕШНО СОХРАНЕНО: {out_name}")
            self.log(f"⏱ Время сохранения: {time.time() - t_save:.2f} сек.")
            self.log(f"🏁 Общее время выполнения: {total_time:.2f} сек.")

        except Exception as e:
            self.log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            import traceback

            self.log(traceback.format_exc())

        finally:
            self.root.after(0, lambda: self.btn_select.config(state=tk.NORMAL))


if __name__ == "__main__":
    root = tk.Tk()
    app = IFCMergerApp(root)
    # Вывод окна на передний план в macOS
    os.system(
        """/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' """
    )
    root.mainloop()
