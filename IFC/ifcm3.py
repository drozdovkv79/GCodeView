import gc
import os
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

import ifcopenshell
import ifcopenshell.api


class IFCCoreStabilityMerger:
    def __init__(self, root):
        self.root = root
        self.root.title("IFC Heavy Merger (v15.0) - RAM Optimized")
        self.root.geometry("1100x850")
        self.setup_ui()

    def setup_ui(self):
        control_frame = ttk.Frame(self.root, padding="15")
        control_frame.pack(fill=tk.X)
        self.btn_select = ttk.Button(
            control_frame, text="Начать слияние (10GB+)", command=self.start_process
        )
        self.btn_select.pack(side=tk.LEFT, padx=5)
        self.progress = ttk.Progressbar(
            control_frame, orient=tk.HORIZONTAL, mode="determinate"
        )
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.log_area = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, font=("Menlo", 11), bg="#1c1c1c", fg="#e0e0e0"
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def log(self, message):
        self.root.after(
            0,
            lambda: (
                self.log_area.insert(tk.END, f"{message}\n"),
                self.log_area.see(tk.END),
            ),
        )

    def start_process(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.btn_select.config(state=tk.DISABLED)
            threading.Thread(
                target=self.run_merger, args=(folder_path,), daemon=True
            ).start()

    def run_merger(self, folder_path):
        ifc_files = [
            f
            for f in os.listdir(folder_path)
            if f.lower().endswith(".ifc") and "MERGED" not in f.upper()
        ]
        ifc_files.sort()

        if not ifc_files:
            self.log("❌ Файлы не найдены.")
            self.btn_select.config(state=tk.NORMAL)
            return

        try:
            self.log(f"📑 Инициализация мастер-файла для большого объема данных...")
            master = ifcopenshell.file(schema="IFC2X3")

            # Базовые настройки проекта
            organization = ifcopenshell.api.run(
                "owner.add_organisation", master, name="GCodeView Team"
            )
            person = ifcopenshell.api.run(
                "owner.add_person", master, family_name="Developer", given_name="User"
            )
            ifcopenshell.api.run(
                "owner.add_person_and_organisation",
                master,
                person=person,
                organisation=organization,
            )
            ifcopenshell.api.run(
                "owner.add_application",
                master,
                application_developer=organization,
                version="1.0",
                application_full_name="IFC Merger",
                application_identifier="IFCM",
            )
            ifcopenshell.api.run("owner.create_owner_history", master)

            project = ifcopenshell.api.run(
                "root.create_entity",
                master,
                ifc_class="IfcProject",
                name="Merged Project",
            )
            ifcopenshell.api.run(
                "unit.assign_unit",
                master,
                units=[
                    ifcopenshell.api.run(
                        "unit.add_si_unit", master, unit_type="LENGTHUNIT"
                    )
                ],
            )

            # Настройка точности для предотвращения ошибок геометрии
            context = ifcopenshell.api.run(
                "context.add_context", master, context_type="Model"
            )
            ifcopenshell.api.run(
                "context.edit_context",
                master,
                context=context,
                attributes={"Precision": 0.00001, "CoordinateSpaceDimension": 3},
            )

            self.root.after(
                0, lambda: self.progress.config(maximum=len(ifc_files), value=0)
            )

            # --- ЦИКЛ ОБРАБОТКИ ---
            for i, file_name in enumerate(ifc_files):
                self.log(f"\n🚀 [{i + 1}/{len(ifc_files)}] Чтение {file_name}...")
                full_path = os.path.join(folder_path, file_name)

                # Загружаем файл без создания лишних итераторов для экономии RAM
                source = ifcopenshell.open(full_path)

                # Создаем контейнеры
                site = ifcopenshell.api.run(
                    "root.create_entity",
                    master,
                    ifc_class="IfcSite",
                    name=f"S_{file_name}",
                )
                ifcopenshell.api.run(
                    "aggregate.assign_object",
                    master,
                    products=[site],
                    relating_object=project,
                )
                building = ifcopenshell.api.run(
                    "root.create_entity",
                    master,
                    ifc_class="IfcBuilding",
                    name=f"B_{file_name}",
                )
                ifcopenshell.api.run(
                    "aggregate.assign_object",
                    master,
                    products=[building],
                    relating_object=site,
                )

                storey_map = {}

                # Перенос продуктов порциями
                products = source.by_type("IfcProduct")
                for product in products:
                    if product.is_a("IfcSpatialStructureElement") or product.is_a(
                        "IfcProject"
                    ):
                        continue

                    new_item = master.add(product)

                    # Привязка к этажу
                    target_container = building
                    for rel in product.ContainedInStructure:
                        ps = rel.RelatingStructure
                        if ps.is_a("IfcBuildingStorey"):
                            sn = ps.Name or "Storey"
                            if sn not in storey_map:
                                new_s = ifcopenshell.api.run(
                                    "root.create_entity",
                                    master,
                                    ifc_class="IfcBuildingStorey",
                                    name=sn,
                                )
                                ifcopenshell.api.run(
                                    "aggregate.assign_object",
                                    master,
                                    products=[new_s],
                                    relating_object=building,
                                )
                                storey_map[sn] = new_s
                            target_container = storey_map[sn]
                            break

                    ifcopenshell.api.run(
                        "spatial.assign_container",
                        master,
                        products=[new_item],
                        relating_structure=target_container,
                    )

                # Перенос стилей и слоев (критично для Metal)
                for entity_type in ["IfcStyledItem", "IfcPresentationLayerAssignment"]:
                    for item in source.by_type(entity_type):
                        try:
                            master.add(item)
                        except:
                            continue

                # --- ОЧИСТКА ПАМЯТИ ПОСЛЕ КАЖДОГО ФАЙЛА ---
                del source
                gc.collect()  # Принудительный сборщик мусора

                self.root.after(0, lambda v=i + 1: self.progress.config(value=v))

                # Промежуточное сохранение каждые 10 файлов (защита от краша)
                if (i + 1) % 10 == 0:
                    self.log(f"💾 Промежуточное сохранение (checkpoint)...")
                    master.write(os.path.join(folder_path, "MERGED_TEMP.ifc"))

            self.log(f"\n🏆 Финальная запись файла...")
            output_path = os.path.join(folder_path, "FINAL_MASSIVE_MERGE.ifc")
            master.write(output_path)
            self.log(f"🏁 Завершено успешно! Итоговый путь: {output_path}")

        except Exception as e:
            self.log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        finally:
            self.root.after(0, lambda: self.btn_select.config(state=tk.NORMAL))


if __name__ == "__main__":
    root = tk.Tk()
    app = IFCCoreStabilityMerger(root)
    root.mainloop()
