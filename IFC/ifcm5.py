#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IFC Merger — объединение нескольких IFC-файлов в один
с сохранением иерархии, цветов, наименований и атрибутов.
macOS приложение с GUI.
"""

import os
import sys
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext

try:
    import ifcopenshell
    import ifcopenshell.util.element
    import ifcopenshell.util.pset
    import ifcopenshell.util.representation
    import ifcopenshell.util.schema
except ImportError:
    print("ERROR: ifcopenshell не установлен.")
    print("Установите: pip install ifcopenshell")
    sys.exit(1)


# ─────────────────────────────────────────────
#  IFC Merger — ядро
# ─────────────────────────────────────────────
class IFCMerger:
    """Объединяет несколько IFC-файлов в один."""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback or print
        self.stats = defaultdict(int)
        self.type_stats = defaultdict(int)
        self.merge_map = {}  # old_entity_id -> new_entity_id (per file)

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_callback(f"[{ts}] {msg}")

    def merge(self, ifc_paths: list[str], output_path: str) -> bool:
        """Главный метод объединения."""
        total_start = time.time()
        self.log("=" * 70)
        self.log(f"IFC MERGER — начало работы")
        self.log(f"Файлов для объединения: {len(ifc_paths)}")
        self.log(f"Результат: {output_path}")
        self.log("=" * 70)

        # ── 1. Читаем все файлы ──────────────────────────────
        self.log("\n── ЭТАП 1: Чтение файлов ──")
        ifc_files = []
        for i, path in enumerate(ifc_paths, 1):
            t0 = time.time()
            fname = os.path.basename(path)
            fsize = os.path.getsize(path) / (1024 * 1024)
            self.log(f"  [{i}/{len(ifc_paths)}] Чтение: {fname} ({fsize:.2f} МБ)...")

            try:
                ifc = ifcopenshell.open(path)
            except Exception as e:
                self.log(f"  ❌ ОШИБКА чтения {fname}: {e}")
                continue

            elapsed = time.time() - t0
            schema = ifc.schema
            project = ifc.by_type("IfcProject")
            project_name = project[0].Name if project else "N/A"

            # Подсчёт объектов по типам
            type_counts = defaultdict(int)
            for entity in ifc:
                type_counts[entity.is_a()] += 1

            total_entities = sum(type_counts.values())
            self.log(f"     ✓ Схема: {schema} | Проект: {project_name}")
            self.log(f"     ✓ Сущностей: {total_entities} | Типов: {len(type_counts)}")
            self.log(f"     ✓ Время чтения: {elapsed:.3f} с")

            # Топ-10 типов
            top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:10]
            for tname, cnt in top_types:
                self.log(f"        {tname}: {cnt}")

            ifc_files.append((path, ifc, type_counts, total_entities))

        if not ifc_files:
            self.log("\n❌ Нет файлов для обработки!")
            return False

        # ── 2. Создаём выходной файл ─────────────────────────
        self.log("\n── ЭТАП 2: Создание выходного файла ──")
        t0 = time.time()

        # Используем схему первого файла
        master_path, master_ifc, _, _ = ifc_files[0]
        schema = master_ifc.schema
        self.log(f"  Схема выходного файла: {schema}")

        # Создаём новый файл
        merged = ifcopenshell.file(schema=schema)

        # Копируем OwnerHistory из первого файла
        owner_hist = None
        for oh in master_ifc.by_type("IfcOwnerHistory"):
            owner_hist = merged.add(oh)
            self.log(f"  OwnerHistory: {oh.OwningUser} / {oh.OwningApplication}")
            break

        elapsed = time.time() - t0
        self.log(f"  ✓ Выходной файл создан за {elapsed:.3f} с")

        # ── 3. Копируем контексты представления ──────────────
        self.log("\n── ЭТАП 3: Контексты представления ──")
        t0 = time.time()
        context_map = {}
        for ctx in master_ifc.by_type("IfcGeometricRepresentationContext"):
            new_ctx = merged.add(ctx)
            context_map[ctx.id()] = new_ctx
            self.log(
                f"  Контекст: {ctx.ContextType} / {ctx.ContextIdentifier} -> id {new_ctx.id()}"
            )
        elapsed = time.time() - t0
        self.log(f"  ✓ Контекстов скопировано: {len(context_map)} за {elapsed:.3f} с")

        # ── 4. Создаём структуру проекта ─────────────────────
        self.log("\n── ЭТАП 4: Иерархия проекта ──")
        t0 = time.time()

        # Создаём единый проект
        master_project = master_ifc.by_type("IfcProject")
        if master_project:
            new_project = merged.add(master_project[0])
            self.log(f"  Проект: {new_project.Name} (id={new_project.id()})")
        else:
            # Создаём проект вручную
            new_project = merged.createIfcProject(
                ifcopenshell.guid.new(), owner_hist, "Merged Project", None
            )
            self.log(f"  Проект создан: Merged Project (id={new_project.id()})")

        # Собираем все сайты из всех файлов
        all_sites = []
        all_buildings = []
        all_storeys = []

        for path, ifc, _, _ in ifc_files:
            fname = os.path.basename(path)
            sites = ifc.by_type("IfcSite")
            buildings = ifc.by_type("IfcBuilding")
            storeys = ifc.by_type("IfcBuildingStorey")
            self.log(
                f"  {fname}: сайтов={len(sites)}, зданий={len(buildings)}, этажей={len(storeys)}"
            )
            all_sites.extend(sites)
            all_buildings.extend(buildings)
            all_storeys.extend(storeys)

        elapsed = time.time() - t0
        self.log(
            f"  ✓ Итого: сайтов={len(all_sites)}, зданий={len(all_buildings)}, этажей={len(all_storeys)} за {elapsed:.3f} с"
        )

        # ── 5. Объединяем каждый файл ────────────────────────
        self.log("\n── ЭТАП 5: Объединение файлов ──")

        # Глобальная карта маппинга: (file_index, old_id) -> new_entity
        global_map = {}
        # Карта для пространственных контейнеров
        spatial_map = {}  # old_spatial -> new_spatial

        for file_idx, (path, ifc, type_counts, total_entities) in enumerate(ifc_files):
            t_file = time.time()
            fname = os.path.basename(path)
            self.log(f"\n  ══ Файл {file_idx + 1}/{len(ifc_files)}: {fname} ══")

            # ── 5a. Копируем пространственную структуру ──────
            self.log(f"  ── Пространственная структура ──")
            t_spatial = time.time()

            # Копируем сайты
            for site in ifc.by_type("IfcSite"):
                new_site = merged.add(site)
                global_map[(file_idx, site.id())] = new_site
                spatial_map[site.id()] = new_site
                self.log(f"    Сайт: {site.Name or 'N/A'} -> id {new_site.id()}")

                # Привязываем к проекту
                try:
                    merged.createIfcRelAggregates(
                        ifcopenshell.guid.new(),
                        owner_hist,
                        None,
                        None,
                        new_project,
                        [new_site],
                    )
                except Exception as e:
                    self.log(f"    ⚠ Ошибка привязки сайта: {e}")

            # Копируем здания
            for building in ifc.by_type("IfcBuilding"):
                new_building = merged.add(building)
                global_map[(file_idx, building.id())] = new_building
                spatial_map[building.id()] = new_building
                self.log(
                    f"    Здание: {building.Name or 'N/A'} -> id {new_building.id()}"
                )

                # Привязываем к сайту
                if building.Decomposes:
                    for rel in building.Decomposes:
                        if rel.RelatingObject and rel.RelatingObject.is_a("IfcSite"):
                            parent_site = spatial_map.get(rel.RelatingObject.id())
                            if parent_site:
                                try:
                                    merged.createIfcRelAggregates(
                                        ifcopenshell.guid.new(),
                                        owner_hist,
                                        None,
                                        None,
                                        parent_site,
                                        [new_building],
                                    )
                                except Exception as e:
                                    self.log(f"    ⚠ Ошибка привязки здания: {e}")

            # Копируем этажи
            for storey in ifc.by_type("IfcBuildingStorey"):
                new_storey = merged.add(storey)
                global_map[(file_idx, storey.id())] = new_storey
                spatial_map[storey.id()] = new_storey
                self.log(
                    f"    Этаж: {storey.Name or 'N/A'} (Elevation={storey.Elevation}) -> id {new_storey.id()}"
                )

                # Привязываем к зданию
                if storey.Decomposes:
                    for rel in storey.Decomposes:
                        if rel.RelatingObject and rel.RelatingObject.is_a(
                            "IfcBuilding"
                        ):
                            parent_building = spatial_map.get(rel.RelatingObject.id())
                            if parent_building:
                                try:
                                    merged.createIfcRelAggregates(
                                        ifcopenshell.guid.new(),
                                        owner_hist,
                                        None,
                                        None,
                                        parent_building,
                                        [new_storey],
                                    )
                                except Exception as e:
                                    self.log(f"    ⚠ Ошибка привязки этажа: {e}")

            elapsed_spatial = time.time() - t_spatial
            self.log(f"    ✓ Пространственная структура: {elapsed_spatial:.3f} с")

            # ── 5b. Копируем физические элементы ─────────────
            self.log(f"  ── Физические элементы ──")
            t_elements = time.time()

            element_types = [
                "IfcWall",
                "IfcWallStandardCase",
                "IfcSlab",
                "IfcFloor",
                "IfcColumn",
                "IfcBeam",
                "IfcDoor",
                "IfcWindow",
                "IfcStair",
                "IfcStairFlight",
                "IfcRailing",
                "IfcCurtainWall",
                "IfcRoof",
                "IfcPlate",
                "IfcMember",
                "IfcPipeSegment",
                "IfcDuctSegment",
                "IfcCableCarrierSegment",
                "IfcFlowSegment",
                "IfcBuildingElementProxy",
                "IfcFurniture",
                "IfcFurnishingElement",
                "IfcDistributionElement",
                "IfcElementAssembly",
                "IfcOpeningElement",
                "IfcSpace",
                "IfcCovering",
                "IfcTransportElement",
            ]

            copied_elements = []
            file_type_stats = defaultdict(int)

            for etype in element_types:
                elements = (
                    ifc.by_type(etype) if etype in [e.is_a() for e in ifc] else []
                )
                if not elements:
                    continue

                for elem in elements:
                    try:
                        new_elem = merged.add(elem)
                        global_map[(file_idx, elem.id())] = new_elem
                        copied_elements.append((elem, new_elem))
                        file_type_stats[etype] += 1
                        self.type_stats[etype] += 1
                    except Exception as e:
                        self.log(
                            f"    ⚠ Ошибка копирования {etype} id={elem.id()}: {e}"
                        )

            elapsed_elements = time.time() - t_elements
            total_copied = sum(file_type_stats.values())
            self.log(
                f"    ✓ Элементов скопировано: {total_copied} за {elapsed_elements:.3f} с"
            )
            for tname, cnt in sorted(file_type_stats.items(), key=lambda x: -x[1]):
                self.log(f"       {tname}: {cnt}")

            # ── 5c. Привязка элементов к этажам ──────────────
            self.log(f"  ── Привязка к этажам ──")
            t_contain = time.time()
            contained = 0

            for elem, new_elem in copied_elements:
                if elem.ContainedInStructure:
                    for rel in elem.ContainedInStructure:
                        old_storey = rel.RelatingStructure
                        if old_storey and old_storey.is_a("IfcBuildingStorey"):
                            new_storey = spatial_map.get(old_storey.id())
                            if new_storey:
                                try:
                                    merged.createIfcRelContainedInSpatialStructure(
                                        ifcopenshell.guid.new(),
                                        owner_hist,
                                        None,
                                        None,
                                        [new_elem],
                                        new_storey,
                                    )
                                    contained += 1
                                except Exception as e:
                                    pass  # Дубликаты связей возможны

            elapsed_contain = time.time() - t_contain
            self.log(f"    ✓ Привязок создано: {contained} за {elapsed_contain:.3f} с")

            # ── 5d. Материалы и цвета ────────────────────────
            self.log(f"  ── Материалы и цвета ──")
            t_mat = time.time()
            mat_count = 0
            color_count = 0

            # Копируем определения материалов
            materials = ifc.by_type("IfcMaterial")
            for mat in materials:
                try:
                    new_mat = merged.add(mat)
                    mat_count += 1
                except Exception:
                    pass

            # Копируем стили представления (цвета)
            styles = ifc.by_type("IfcSurfaceStyle")
            for style in styles:
                try:
                    new_style = merged.add(style)
                    color_count += 1
                except Exception:
                    pass

            # Копируем связи материал-элемент
            mat_rels = ifc.by_type("IfcRelAssociatesMaterial")
            mat_rel_count = 0
            for rel in mat_rels:
                try:
                    merged.add(rel)
                    mat_rel_count += 1
                except Exception:
                    pass

            # Копируем связи стиль-представление
            style_rels = ifc.by_type("IfcStyledItem")
            styled_count = 0
            for item in style_rels:
                try:
                    merged.add(item)
                    styled_count += 1
                except Exception:
                    pass

            elapsed_mat = time.time() - t_mat
            self.log(
                f"    ✓ Материалов: {mat_count}, Стилей(цветов): {color_count}, "
                f"Связей материалов: {mat_rel_count}, StyledItems: {styled_count} за {elapsed_mat:.3f} с"
            )

            # ── 5e. Свойства (Psets) ─────────────────────────
            self.log(f"  ── Свойства (Property Sets) ──")
            t_pset = time.time()
            pset_count = 0
            pset_rel_count = 0

            psets = ifc.by_type("IfcPropertySet")
            for pset in psets:
                try:
                    merged.add(pset)
                    pset_count += 1
                except Exception:
                    pass

            pset_rels = ifc.by_type("IfcRelDefinesByProperties")
            for rel in pset_rels:
                try:
                    merged.add(rel)
                    pset_rel_count += 1
                except Exception:
                    pass

            elapsed_pset = time.time() - t_pset
            self.log(
                f"    ✓ PropertySets: {pset_count}, Связей Pset: {pset_rel_count} за {elapsed_pset:.3f} с"
            )

            # ── 5f. Типы элементов ────────────────────────────
            self.log(f"  ── Типы элементов ──")
            t_types = time.time()
            type_count = 0
            type_rel_count = 0

            type_elements = ifc.by_type("IfcTypeObject")
            for te in type_elements:
                try:
                    merged.add(te)
                    type_count += 1
                except Exception:
                    pass

            type_rels = ifc.by_type("IfcRelDefinesByType")
            for rel in type_rels:
                try:
                    merged.add(rel)
                    type_rel_count += 1
                except Exception:
                    pass

            elapsed_types = time.time() - t_types
            self.log(
                f"    ✓ Типов: {type_count}, Связей типов: {type_rel_count} за {elapsed_types:.3f} с"
            )

            # Итого по файлу
            elapsed_file = time.time() - t_file
            self.log(f"  ══ Итого по файлу {fname}: {elapsed_file:.3f} с ══")
            self.stats["files_processed"] += 1
            self.stats["total_elements"] += total_copied

        # ── 6. Сохранение ────────────────────────────────────
        self.log("\n── ЭТАП 6: Сохранение результата ──")
        t_save = time.time()

        total_entities_out = sum(1 for _ in merged)
        self.log(f"  Сущностей в выходном файле: {total_entities_out}")
        self.log(f"  Сохранение: {output_path}")

        merged.write(output_path)
        out_size = os.path.getsize(output_path) / (1024 * 1024)

        elapsed_save = time.time() - t_save
        self.log(f"  ✓ Файл сохранён ({out_size:.2f} МБ) за {elapsed_save:.3f} с")

        # ── Итоговая статистика ──────────────────────────────
        total_elapsed = time.time() - total_start
        self.log("\n" + "=" * 70)
        self.log("ИТОГОВАЯ СТАТИСТИКА")
        self.log("=" * 70)
        self.log(f"  Файлов обработано: {self.stats['files_processed']}")
        self.log(f"  Элементов скопировано: {self.stats['total_elements']}")
        self.log(f"  Сущностей в результате: {total_entities_out}")
        self.log(f"  Размер результата: {out_size:.2f} МБ")
        self.log(f"  Общее время: {total_elapsed:.3f} с")
        self.log("\n  Типы элементов:")
        for tname, cnt in sorted(self.type_stats.items(), key=lambda x: -x[1]):
            self.log(f"    {tname}: {cnt}")
        self.log("=" * 70)
        self.log("✓ ГОТОВО!")
        self.log("=" * 70)

        return True


# ─────────────────────────────────────────────
#  GUI — macOS приложение
# ─────────────────────────────────────────────
class IFCMergerApp:
    """GUI приложение для macOS."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("IFC Merger — Объединение IFC файлов")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        # macOS стиль
        self.root.configure(bg="systemWindowBackgroundColor")

        self.selected_dir = tk.StringVar()
        self.ifc_files = []
        self.is_running = False

        self._build_ui()
        self._apply_macos_style()

    def _apply_macos_style(self):
        """Применяем macOS-стиль."""
        try:
            self.root.tk.call("tk", "scaling", 2.0)  # Retina
        except Exception:
            pass

    def _build_ui(self):
        """Создаём интерфейс."""
        pad = {"padx": 15, "pady": 8}

        # ── Заголовок ──
        title_frame = tk.Frame(self.root)
        title_frame.pack(fill="x", **pad)

        title_label = tk.Label(
            title_frame,
            text="🏗 IFC Merger",
            font=("SF Pro Display", 22, "bold"),
        )
        title_label.pack(side="left")

        subtitle = tk.Label(
            title_frame,
            text="Объединение IFC-файлов с сохранением иерархии, цветов и атрибутов",
            font=("SF Pro Text", 11),
            fg="gray",
        )
        subtitle.pack(side="left", padx=(15, 0), pady=(8, 0))

        # ── Выбор каталога ──
        dir_frame = tk.LabelFrame(
            self.root, text="Каталог с IFC-файлами", padx=10, pady=10
        )
        dir_frame.pack(fill="x", **pad)

        dir_entry = tk.Entry(
            dir_frame,
            textvariable=self.selected_dir,
            font=("SF Mono", 12),
            width=60,
        )
        dir_entry.pack(side="left", fill="x", expand=True)

        btn_browse = tk.Button(
            dir_frame,
            text="Выбрать…",
            command=self._browse_directory,
            font=("SF Pro Text", 12),
        )
        btn_browse.pack(side="right", padx=(10, 0))

        btn_scan = tk.Button(
            dir_frame,
            text="Сканировать",
            command=self._scan_directory,
            font=("SF Pro Text", 12),
        )
        btn_scan.pack(side="right", padx=(5, 0))

        # ── Список файлов ──
        list_frame = tk.LabelFrame(
            self.root, text="Найденные IFC-файлы", padx=10, pady=10
        )
        list_frame.pack(fill="both", expand=True, **pad)

        # Список с чекбоксами
        self.files_canvas_frame = tk.Frame(list_frame)
        self.files_canvas_frame.pack(fill="both", expand=True)

        self.files_listbox = tk.Listbox(
            self.files_canvas_frame,
            font=("SF Mono", 11),
            selectmode="multiple",
            height=6,
        )
        scrollbar = tk.Scrollbar(
            self.files_canvas_frame, orient="vertical", command=self.files_listbox.yview
        )
        self.files_listbox.config(yscrollcommand=scrollbar.set)

        self.files_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Кнопки выделения
        sel_frame = tk.Frame(list_frame)
        sel_frame.pack(fill="x", pady=(5, 0))

        tk.Button(sel_frame, text="Выделить все", command=self._select_all).pack(
            side="left", padx=2
        )
        tk.Button(sel_frame, text="Снять все", command=self._deselect_all).pack(
            side="left", padx=2
        )

        self.file_count_label = tk.Label(
            sel_frame, text="Файлов: 0", font=("SF Pro Text", 11)
        )
        self.file_count_label.pack(side="right")

        # ── Кнопка Merge ──
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)

        self.btn_merge = tk.Button(
            btn_frame,
            text="🔗 Объединить IFC-файлы",
            command=self._start_merge,
            font=("SF Pro Text", 14, "bold"),
            bg="#007AFF",
            fg="white",
            activebackground="#0056CC",
            activeforeground="white",
            relief="flat",
            padx=20,
            pady=8,
        )
        self.btn_merge.pack()

        # ── Прогресс ──
        self.progress = tk.DoubleVar()
        self.progress_bar = tk.ttk = None
        try:
            import tkinter.ttk as ttk

            self.progress_bar = ttk.Progressbar(
                self.root,
                variable=self.progress,
                maximum=100,
                mode="determinate",
            )
            self.progress_bar.pack(fill="x", **pad)
        except Exception:
            pass

        # ── Лог ──
        log_frame = tk.LabelFrame(self.root, text="Журнал выполнения", padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            font=("SF Mono", 10),
            height=12,
            wrap="word",
            bg="#1E1E1E",
            fg="#D4D4D4",
            insertbackground="white",
        )
        self.log_text.pack(fill="both", expand=True)

        # ── Статус ──
        self.status_var = tk.StringVar(value="Готово. Выберите каталог с IFC-файлами.")
        status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("SF Pro Text", 10),
            relief="sunken",
            anchor="w",
        )
        status_bar.pack(fill="x", side="bottom")

    def _browse_directory(self):
        """Выбор каталога."""
        directory = filedialog.askdirectory(
            title="Выберите каталог с IFC-файлами",
            initialdir=os.path.expanduser("~"),
        )
        if directory:
            self.selected_dir.set(directory)
            self._scan_directory()

    def _scan_directory(self):
        """Сканируем каталог на IFC-файлы."""
        directory = self.selected_dir.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Ошибка", "Укажите существующий каталог!")
            return

        self.files_listbox.delete(0, tk.END)
        self.ifc_files = []

        for fname in sorted(os.listdir(directory)):
            if fname.lower().endswith(".ifc"):
                fpath = os.path.join(directory, fname)
                fsize = os.path.getsize(fpath) / (1024 * 1024)
                display = f"  {fname}  ({fsize:.2f} МБ)"
                self.files_listbox.insert(tk.END, display)
                self.ifc_files.append(fpath)

        self.file_count_label.config(text=f"Файлов: {len(self.ifc_files)}")
        self.status_var.set(f"Найдено {len(self.ifc_files)} IFC-файлов в {directory}")

        if not self.ifc_files:
            messagebox.showwarning(
                "Предупреждение", "IFC-файлы не найдены в указанном каталоге."
            )

    def _select_all(self):
        self.files_listbox.select_set(0, tk.END)

    def _deselect_all(self):
        self.files_listbox.select_clear(0, tk.END)

    def _log(self, msg):
        """Добавляем строку в лог (потокобезопасно)."""

        def _append():
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.update_idletasks()

        self.root.after(0, _append)

    def _start_merge(self):
        """Запускаем объединение в отдельном потоке."""
        if self.is_running:
            messagebox.showwarning("Предупреждение", "Объединение уже выполняется!")
            return

        selected_indices = self.files_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Предупреждение", "Выберите хотя бы один IFC-файл!")
            return

        selected_files = [self.ifc_files[i] for i in selected_indices]

        if len(selected_files) < 2:
            messagebox.showwarning(
                "Предупреждение", "Для объединения нужно минимум 2 файла!"
            )
            return

        output_dir = self.selected_dir.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"merged_{timestamp}.ifc")

        self.is_running = True
        self.btn_merge.config(state="disabled", text="⏳ Объединение…")
        self.status_var.set("Объединение в процессе…")
        self.log_text.delete("1.0", tk.END)
        self.progress.set(0)

        def _run():
            try:
                merger = IFCMerger(log_callback=self._log)

                # Прогресс по файлам
                total_files = len(selected_files)
                for i, fpath in enumerate(selected_files):
                    progress_val = ((i + 1) / total_files) * 80
                    self.root.after(0, lambda v=progress_val: self.progress.set(v))

                success = merger.merge(selected_files, output_path)

                self.root.after(0, lambda: self.progress.set(100))

                if success:
                    self.root.after(
                        0,
                        lambda: self.status_var.set(
                            f"✓ Готово! Результат: {os.path.basename(output_path)}"
                        ),
                    )
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Готово",
                            f"IFC-файлы объединены!\n\nРезультат:\n{output_path}",
                        ),
                    )
                else:
                    self.root.after(
                        0, lambda: self.status_var.set("❌ Ошибка объединения")
                    )
            except Exception as e:
                self._log(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
                import traceback

                self._log(traceback.format_exc())
                self.root.after(0, lambda: self.status_var.set(f"❌ Ошибка: {e}"))
            finally:
                self.root.after(0, self._merge_finished)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _merge_finished(self):
        self.is_running = False
        self.btn_merge.config(state="normal", text="🔗 Объединить IFC-файлы")

    def run(self):
        self.root.mainloop()


# ─────────────────────────────────────────────
#  Точка входа
# ─────────────────────────────────────────────
def main():
    # Проверка ifcopenshell
    try:
        import ifcopenshell

        print(f"ifcopenshell version: {ifcopenshell.version}")
    except ImportError:
        print("ERROR: ifcopenshell не установлен!")
        print("Установите командой: pip3 install ifcopenshell")
        sys.exit(1)

    app = IFCMergerApp()
    app.run()


if __name__ == "__main__":
    main()
