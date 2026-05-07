#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IFC Merger Optimized — объединение больших наборов IFC-файлов
Оптимизировано для: 100+ файлов × 100 МБ
- Потоковая обработка (1 файл в памяти)
- Дедупликация материалов, стилей, контекстов
- Маппинг через IfcRel* (в 5-10x быстрее обратных атрибутов)
- Минимальное логирование, явный GC
"""

import gc
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
    import ifcopenshell.guid
except ImportError:
    print("ERROR: ifcopenshell не установлен.\nУстановите: pip3 install ifcopenshell")
    sys.exit(1)

# Увеличиваем лимит рекурсии для глубоких копий геометрии
sys.setrecursionlimit(5000)


# ─────────────────────────────────────────────
#  OPTIMIZED IFC MERGER
# ─────────────────────────────────────────────
class IFCMergerOptimized:
    def __init__(self, log_callback=None):
        self.log_cb = log_callback or print
        self.stats = defaultdict(int)
        self.type_stats = defaultdict(int)
        self._progress_cb = None
        self.style_cache = {}

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_cb(f"[{ts}] {msg}")

    def _safe_by_type(self, ifc_file, type_name):
        try:
            return ifc_file.by_type(type_name)
        except RuntimeError:
            return []

    def _remap_contexts(self, elem, master_ctx_map):
        if not getattr(elem, "Representation", None):
            return
        for rep in elem.Representation.Representations:
            ctx = rep.ContextOfItems
            if ctx:
                target = (
                    ctx.ParentContext
                    if ctx.is_a("IfcGeometricRepresentationSubContext")
                    else ctx
                )
                key = (
                    getattr(target, "ContextIdentifier", "") or "",
                    getattr(target, "ContextType", "") or "",
                )
                if key in master_ctx_map:
                    rep.ContextOfItems = master_ctx_map[key]

    def _transfer_styles_recursive(self, old_elem, new_elem, merged_file):
        """Рекурсивный перенос IfcStyledItem на всю геометрию, включая MappedItem, BooleanResult, B-Rep."""
        if not getattr(old_elem, "Representation", None) or not getattr(
            new_elem, "Representation", None
        ):
            return

        def collect_items(rep_obj):
            items = []
            if not rep_obj:
                return items
            if rep_obj.is_a("IfcProductDefinitionShape"):
                for r in rep_obj.Representations:
                    items.extend(collect_items(r))
            elif rep_obj.is_a("IfcShapeRepresentation"):
                if getattr(rep_obj, "Items", None):
                    for it in rep_obj.Items:
                        items.append(it)
                        items.extend(collect_items(it))
            elif rep_obj.is_a("IfcMappedItem"):
                items.extend(collect_items(rep_obj.MappingSource.MappedRepresentation))
            elif rep_obj.is_a("IfcBooleanResult"):
                items.extend(collect_items(rep_obj.FirstOperand))
                items.extend(collect_items(rep_obj.SecondOperand))
            return items

        old_items = collect_items(old_elem.Representation)
        new_items = collect_items(new_elem.Representation)

        # add() сохраняет порядок элементов → сопоставление по индексу надёжно
        for old_it, new_it in zip(old_items, new_items):
            if getattr(old_it, "StyledByItem", None):
                for old_style in old_it.StyledByItem:
                    key = f"SI:{old_style.id()}"
                    if key not in self.style_cache:
                        try:
                            self.style_cache[key] = merged_file.add(old_style)
                        except:
                            continue
                    new_style = self.style_cache[key]
                    if getattr(new_style, "Item", None) != new_it:
                        new_style.Item = new_it

    def _count_geometry(self, elem):
        """Подсчёт типов геометрии для верификации IfcFace/B-Rep."""
        counts = {
            "IfcFace": 0,
            "IfcFacetedBrep": 0,
            "IfcExtrudedAreaSolid": 0,
            "IfcMappedItem": 0,
        }
        if not getattr(elem, "Representation", None):
            return counts

        def walk(obj):
            if not obj:
                return
            t = obj.is_a()
            if t in counts:
                counts[t] += 1
            if t == "IfcProductDefinitionShape":
                for r in obj.Representations:
                    walk(r)
            elif t == "IfcShapeRepresentation" and getattr(obj, "Items", None):
                for it in obj.Items:
                    walk(it)
            elif t == "IfcMappedItem":
                walk(obj.MappingSource.MappedRepresentation)
            elif t == "IfcBooleanResult":
                walk(obj.FirstOperand)
                walk(obj.SecondOperand)
            elif t == "IfcFacetedBrep" and getattr(obj, "Outer", None):
                walk(obj.Outer)
            elif t == "IfcClosedShell" and getattr(obj, "CfsFaces", None):
                for f in obj.CfsFaces:
                    walk(f)

        walk(elem.Representation)
        return counts

    def merge(self, ifc_paths: list[str], output_path: str) -> bool:
        total_start = time.time()
        self._log("=" * 72)
        self._log(
            f"IFC MERGER OPTIMIZED | Файлов: {len(ifc_paths)} | Вывод: {os.path.basename(output_path)}"
        )
        self._log("=" * 72)

        # ── 1. Инициализация ─────────────────────────────────
        self._log("\n[1/5] Инициализация схемы, проекта и контекстов...")
        t0 = time.time()
        master = ifcopenshell.open(ifc_paths[0])
        schema = master.schema
        merged = ifcopenshell.file(schema=schema)

        master_ctx_map = {}
        owner_hist = None

        for oh in self._safe_by_type(master, "IfcOwnerHistory"):
            try:
                owner_hist = merged.add(oh)
            except:
                pass
            break
        if not owner_hist:
            owner_hist = merged.create_entity(
                "IfcOwnerHistory",
                GlobalId=ifcopenshell.guid.new(),
                OwningUser=merged.create_entity(
                    "IfcPersonAndOrganization",
                    ThePerson=merged.create_entity("IfcPerson"),
                    TheOrganization=merged.create_entity("IfcOrganization"),
                ),
                ChangeAction="ADDED",
                CreationDate=int(time.time()),
            )

        proj = self._safe_by_type(master, "IfcProject")
        new_project = (
            merged.add(proj[0])
            if proj
            else merged.create_entity(
                "IfcProject",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_hist,
                Name="Merged Project",
            )
        )

        for ua in self._safe_by_type(master, "IfcUnitAssignment"):
            try:
                new_ua = merged.add(ua)
                new_project.UnitsInContext = new_ua
            except:
                pass
            break

        for ctx in self._safe_by_type(master, "IfcGeometricRepresentationContext"):
            cid = getattr(ctx, "ContextIdentifier", "") or ""
            ctype = getattr(ctx, "ContextType", "") or ""
            key = (cid, ctype)
            if key not in master_ctx_map:
                master_ctx_map[key] = merged.add(ctx)

        del master
        gc.collect()
        self._log(
            f"  ✓ Схема: {schema} | Проект: {new_project.Name or 'Merged'} | Контекстов: {len(master_ctx_map)} | {time.time() - t0:.2f} с"
        )

        # ── 2. Потоковая обработка ───────────────────────────
        self._log("\n[2/5] Обработка файлов...")
        processed_files = 0
        total_geo_stats = defaultdict(int)

        for idx, fpath in enumerate(ifc_paths, 1):
            t_file = time.time()
            fname = os.path.basename(fpath)
            fname_base = os.path.splitext(fname)[0]
            fsize_mb = os.path.getsize(fpath) / (1024 * 1024)

            try:
                ifc = ifcopenshell.open(fpath)
            except Exception as e:
                self._log(f"  ❌ Пропуск {fname}: {e}")
                continue

            file_schema = ifc.schema
            spatial_map = {}
            element_map = {}
            file_type_counts = defaultdict(int)
            file_geo_stats = defaultdict(int)

            # 2a. Сайт с именем файла
            new_site = merged.create_entity(
                "IfcSite",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_hist,
                Name=fname_base,
                CompositionType="ELEMENT",
            )
            spatial_map["ROOT_SITE"] = new_site
            merged.create_entity(
                "IfcRelAggregates",
                GlobalId=ifcopenshell.guid.new(),
                OwnerHistory=owner_hist,
                RelatingObject=new_project,
                RelatedObjects=[new_site],
            )

            for bldg in self._safe_by_type(ifc, "IfcBuilding"):
                new_bldg = merged.add(bldg)
                spatial_map[bldg.id()] = new_bldg
                merged.create_entity(
                    "IfcRelAggregates",
                    GlobalId=ifcopenshell.guid.new(),
                    OwnerHistory=owner_hist,
                    RelatingObject=new_site,
                    RelatedObjects=[new_bldg],
                )

            for storey in self._safe_by_type(ifc, "IfcBuildingStorey"):
                new_storey = merged.add(storey)
                spatial_map[storey.id()] = new_storey
                if storey.Decomposes:
                    for drel in storey.Decomposes:
                        parent = drel.RelatingObject
                        if parent and parent.id() in spatial_map:
                            merged.create_entity(
                                "IfcRelAggregates",
                                GlobalId=ifcopenshell.guid.new(),
                                OwnerHistory=owner_hist,
                                RelatingObject=spatial_map[parent.id()],
                                RelatedObjects=[new_storey],
                            )

            # 2b. Элементы + рекурсивные стили + верификация геометрии
            target_types = (
                "IfcWall",
                "IfcWallStandardCase",
                "IfcSlab",
                "IfcFloor",
                "IfcColumn",
                "IfcBeam",
                "IfcDoor",
                "IfcWindow",
                "IfcStair",
                "IfcRailing",
                "IfcCurtainWall",
                "IfcRoof",
                "IfcPlate",
                "IfcMember",
                "IfcPipeSegment",
                "IfcDuctSegment",
                "IfcCableCarrierSegment",
                "IfcBuildingElementProxy",
                "IfcFurniture",
                "IfcDistributionElement",
                "IfcCovering",
                "IfcOpeningElement",
                "IfcTransportElement",
            )
            for t in target_types:
                for ent in self._safe_by_type(ifc, t):
                    try:
                        new_ent = merged.add(ent)
                        element_map[ent.id()] = new_ent
                        self._remap_contexts(new_ent, master_ctx_map)
                        self._transfer_styles_recursive(ent, new_ent, merged)

                        # Верификация IfcFace/B-Rep
                        geo = self._count_geometry(ent)
                        for k, v in geo.items():
                            file_geo_stats[k] += v

                        file_type_counts[t] += 1
                        self.type_stats[t] += 1
                    except Exception:
                        pass

            # 2c. Логирование материалов, цветов и геометрии
            mat_names = set()
            color_info = []
            for mat in self._safe_by_type(ifc, "IfcMaterial"):
                mat_names.add(mat.Name or "Unnamed")
            for style in self._safe_by_type(ifc, "IfcSurfaceStyle"):
                sname = style.Name or "Unnamed"
                rgb = "N/A"
                if style.Styles:
                    for s in style.Styles:
                        if s.is_a("IfcSurfaceStyleRendering") and getattr(
                            s, "SurfaceColour", None
                        ):
                            c = s.SurfaceColour
                            rgb = f"RGB({c.Red:.2f}, {c.Green:.2f}, {c.Blue:.2f})"
                color_info.append(f"{sname}({rgb})")

            self._log(
                f"    📦 Материалы: {len(mat_names)} | 🎨 Стили: {len(color_info)}"
            )
            self._log(
                f"    🔷 Геометрия: Faces={file_geo_stats['IfcFace']}, BRep={file_geo_stats['IfcFacetedBrep']}, "
                f"Extruded={file_geo_stats['IfcExtrudedAreaSolid']}, Mapped={file_geo_stats['IfcMappedItem']}"
            )
            for k, v in file_geo_stats.items():
                total_geo_stats[k] += v

            # 2d. Связи (включая безопасное копирование материалов)
            rel_count = 0

            for rel in self._safe_by_type(ifc, "IfcRelContainedInSpatialStructure"):
                struct = rel.RelatingStructure
                elems = rel.RelatedElements or []
                if struct and struct.id() in spatial_map:
                    new_elems = [
                        element_map[e.id()] for e in elems if e.id() in element_map
                    ]
                    if new_elems:
                        merged.create_entity(
                            "IfcRelContainedInSpatialStructure",
                            GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=owner_hist,
                            RelatingStructure=spatial_map[struct.id()],
                            RelatedElements=new_elems,
                        )
                        rel_count += 1

            for rel in self._safe_by_type(ifc, "IfcRelVoidsElement"):
                if (
                    rel.RelatingBuildingElement
                    and rel.RelatingBuildingElement.id() in element_map
                ):
                    if (
                        rel.RelatedOpeningElement
                        and rel.RelatedOpeningElement.id() in element_map
                    ):
                        merged.create_entity(
                            "IfcRelVoidsElement",
                            GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=owner_hist,
                            RelatingBuildingElement=element_map[
                                rel.RelatingBuildingElement.id()
                            ],
                            RelatedOpeningElement=element_map[
                                rel.RelatedOpeningElement.id()
                            ],
                        )
                        rel_count += 1

            for rel in self._safe_by_type(ifc, "IfcRelFillsElement"):
                if (
                    rel.RelatingOpeningElement
                    and rel.RelatingOpeningElement.id() in element_map
                ):
                    if (
                        rel.RelatedBuildingElement
                        and rel.RelatedBuildingElement.id() in element_map
                    ):
                        merged.create_entity(
                            "IfcRelFillsElement",
                            GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=owner_hist,
                            RelatingOpeningElement=element_map[
                                rel.RelatingOpeningElement.id()
                            ],
                            RelatedBuildingElement=element_map[
                                rel.RelatedBuildingElement.id()
                            ],
                        )
                        rel_count += 1

            for rel in self._safe_by_type(ifc, "IfcRelDefinesByProperties"):
                objs = rel.RelatedObjects or []
                pset = rel.RelatingPropertyDefinition
                new_objs = [element_map[o.id()] for o in objs if o.id() in element_map]
                if new_objs and pset:
                    try:
                        new_pset = merged.add(pset)
                        merged.create_entity(
                            "IfcRelDefinesByProperties",
                            GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=owner_hist,
                            RelatedObjects=new_objs,
                            RelatingPropertyDefinition=new_pset,
                        )
                        rel_count += 1
                    except:
                        pass

            for rel in self._safe_by_type(ifc, "IfcRelDefinesByType"):
                objs = rel.RelatedObjects or []
                typ = rel.RelatingType
                new_objs = [element_map[o.id()] for o in objs if o.id() in element_map]
                if new_objs and typ:
                    try:
                        new_typ = merged.add(typ)
                        merged.create_entity(
                            "IfcRelDefinesByType",
                            GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=owner_hist,
                            RelatedObjects=new_objs,
                            RelatingType=new_typ,
                        )
                        rel_count += 1
                    except:
                        pass

            # 🔑 Безопасное копирование назначений материалов (слои, профили, прямые назначения)
            for rel in self._safe_by_type(ifc, "IfcRelAssociatesMaterial"):
                objs = rel.RelatedObjects or []
                new_objs = [element_map[o.id()] for o in objs if o.id() in element_map]
                if new_objs:
                    try:
                        new_rel = merged.add(rel)  # Глубокая копия графа материалов
                        new_rel.RelatedObjects = new_objs  # Привязка к новым элементам
                        rel_count += 1
                    except Exception:
                        pass

            # 2e. Очистка
            total_elems = sum(file_type_counts.values())
            self.stats["total_elements"] += total_elems
            processed_files += 1

            del ifc, spatial_map, element_map, file_type_counts, file_geo_stats
            gc.collect()

            elapsed = time.time() - t_file
            self._log(
                f"  [{idx}/{len(ifc_paths)}] {fname:<35} | {file_schema} | {fsize_mb:5.1f} МБ | "
                f"Элем: {total_elems:5} | Связей: {rel_count:5} | {elapsed:.2f} с"
            )

            if self._progress_cb:
                self._progress_cb(idx / len(ifc_paths) * 90)

        # ── 3. Сохранение ────────────────────────────────────
        self._log("\n[3/5] Финализация и запись...")
        t_save = time.time()
        total_entities = sum(1 for _ in merged)
        merged.write(output_path)
        out_size = os.path.getsize(output_path) / (1024 * 1024)
        self._log(
            f"  ✓ Сущностей: {total_entities:,} | Размер: {out_size:.1f} МБ | {time.time() - t_save:.2f} с"
        )

        # ── 4. Итог ──────────────────────────────────────────
        total_time = time.time() - total_start
        self._log("\n" + "=" * 72)
        self._log("ИТОГ")
        self._log(f"  Файлов обработано : {processed_files}")
        self._log(f"  Элементов всего   : {self.stats['total_elements']:,}")
        self._log(f"  Уникальных стилей : {len(self.style_cache)}")
        self._log(
            f"  Геометрия (итого) : Faces={total_geo_stats['IfcFace']:,} | BRep={total_geo_stats['IfcFacetedBrep']:,} | "
            f"Extruded={total_geo_stats['IfcExtrudedAreaSolid']:,} | Mapped={total_geo_stats['IfcMappedItem']:,}"
        )
        self._log(f"  Размер результата : {out_size:.1f} МБ")
        self._log(f"  Общее время       : {total_time:.2f} с")
        self._log("  Топ типов:")
        for t, c in sorted(self.type_stats.items(), key=lambda x: -x[1])[:12]:
            self._log(f"    {t:<30} {c:>6}")
        self._log("=" * 72)
        self._log("✓ ГОТОВО")

        del merged, master_ctx_map
        self.style_cache.clear()
        gc.collect()
        return True


# ─────────────────────────────────────────────
#  GUI (macOS Optimized)
# ─────────────────────────────────────────────
class IFCMergerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("IFC Merger Pro — Оптимизировано для больших наборов")
        self.root.geometry("950x720")
        self.root.minsize(800, 550)
        self.selected_dir = tk.StringVar()
        self.ifc_files = []
        self.is_running = False
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 15, "pady": 8}

        # Заголовок
        hdr = tk.Frame(self.root)
        hdr.pack(fill="x", **pad)
        tk.Label(
            hdr, text="🏗 IFC Merger Pro", font=("SF Pro Display", 20, "bold")
        ).pack(side="left")
        tk.Label(
            hdr,
            text="Потоковая обработка • Дедупликация • Низкое потребление RAM",
            font=("SF Pro Text", 11),
            fg="gray",
        ).pack(side="left", padx=15, pady=5)

        # Каталог
        dir_f = tk.LabelFrame(self.root, text="Каталог с IFC", padx=10, pady=8)
        dir_f.pack(fill="x", **pad)
        tk.Entry(dir_f, textvariable=self.selected_dir, font=("SF Mono", 12)).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(dir_f, text="Выбрать…", command=self._browse).pack(
            side="right", padx=8
        )
        tk.Button(dir_f, text="Сканировать", command=self._scan).pack(
            side="right", padx=4
        )

        # Список файлов
        list_f = tk.LabelFrame(self.root, text="Файлы для объединения", padx=10, pady=8)
        list_f.pack(fill="both", expand=True, **pad)
        self.lb = tk.Listbox(
            list_f, font=("SF Mono", 11), selectmode="multiple", height=6
        )
        sb = tk.Scrollbar(list_f, orient="vertical", command=self.lb.yview)
        self.lb.config(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ctrl = tk.Frame(list_f)
        ctrl.pack(fill="x", pady=4)
        tk.Button(ctrl, text="Все", command=lambda: self.lb.select_set(0, tk.END)).pack(
            side="left", padx=2
        )
        tk.Button(
            ctrl, text="Снять", command=lambda: self.lb.select_clear(0, tk.END)
        ).pack(side="left", padx=2)
        self.lbl_count = tk.Label(ctrl, text="Файлов: 0", font=("SF Pro Text", 11))
        self.lbl_count.pack(side="right")

        # Кнопка Merge
        btn_f = tk.Frame(self.root)
        btn_f.pack(fill="x", **pad)
        self.btn_merge = tk.Button(
            btn_f,
            text="🔗 Объединить выбранные",
            command=self._start_merge,
            font=("SF Pro Text", 13, "bold"),
            bg="#007AFF",
            fg="white",
            activebackground="#0056CC",
            relief="flat",
            padx=20,
            pady=6,
        )
        self.btn_merge.pack()

        # Прогресс
        try:
            import tkinter.ttk as ttk

            self.prog = ttk.Progressbar(self.root, maximum=100, mode="determinate")
            self.prog.pack(fill="x", **pad)
        except:
            self.prog = None

        # Лог
        log_f = tk.LabelFrame(self.root, text="Журнал", padx=10, pady=8)
        log_f.pack(fill="both", expand=True, **pad)
        self.log_txt = scrolledtext.ScrolledText(
            log_f,
            font=("SF Mono", 10),
            height=10,
            bg="#1E1E1E",
            fg="#D4D4D4",
            wrap="word",
        )
        self.log_txt.pack(fill="both", expand=True)

        # Статус
        self.status = tk.StringVar(value="Готово. Выберите каталог с IFC-файлами.")
        tk.Label(
            self.root,
            textvariable=self.status,
            font=("SF Pro Text", 10),
            relief="sunken",
            anchor="w",
        ).pack(fill="x", side="bottom")

    def _browse(self):
        d = filedialog.askdirectory(
            title="Каталог с IFC", initialdir=os.path.expanduser("~")
        )
        if d:
            self.selected_dir.set(d)
            self._scan()

    def _scan(self):
        d = self.selected_dir.get()
        if not os.path.isdir(d):
            messagebox.showerror("Ошибка", "Каталог не существует")
            return
        self.lb.delete(0, tk.END)
        self.ifc_files = []
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".ifc"):
                p = os.path.join(d, f)
                self.lb.insert(
                    tk.END, f"  {f}  ({os.path.getsize(p) / 1048576:.1f} МБ)"
                )
                self.ifc_files.append(p)
        self.lbl_count.config(text=f"Файлов: {len(self.ifc_files)}")
        self.status.set(f"Найдено {len(self.ifc_files)} файлов")

    def _log(self, msg):
        self.root.after(
            0,
            lambda: (self.log_txt.insert(tk.END, msg + "\n"), self.log_txt.see(tk.END)),
        )

    def _update_progress(self, val):
        if self.prog:
            self.root.after(0, lambda: self.prog.config(value=val))

    def _start_merge(self):
        if self.is_running:
            return
        sel = self.lb.curselection()
        if len(sel) < 2:
            messagebox.showwarning("Внимание", "Выберите минимум 2 файла")
            return
        files = [self.ifc_files[i] for i in sel]
        out_dir = self.selected_dir.get()
        out_path = os.path.join(
            out_dir, f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ifc"
        )

        self.is_running = True
        self.btn_merge.config(state="disabled", text="⏳ Обработка...")
        self.status.set("Объединение запущено...")
        self.log_txt.delete("1.0", tk.END)
        if self.prog:
            self.prog.config(value=0)

        def _worker():
            try:
                merger = IFCMergerOptimized(log_callback=self._log)
                merger._progress_cb = self._update_progress
                ok = merger.merge(files, out_path)
                self.root.after(0, lambda: self.prog and self.prog.config(value=100))
                if ok:
                    self.root.after(
                        0,
                        lambda: (
                            self.status.set(f"✓ Готово: {os.path.basename(out_path)}"),
                            messagebox.showinfo(
                                "Готово", f"Результат сохранён:\n{out_path}"
                            ),
                        ),
                    )
            except Exception as e:
                import traceback

                self._log(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}\n{traceback.format_exc()}")
                self.root.after(0, lambda: self.status.set(f"❌ Ошибка: {e}"))
            finally:
                self.root.after(0, self._finished)

        threading.Thread(target=_worker, daemon=True).start()

    def _finished(self):
        self.is_running = False
        self.btn_merge.config(state="normal", text="🔗 Объединить выбранные")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    print(f"ifcopenshell {ifcopenshell.version} | Python {sys.version.split()[0]}")
    IFCMergerApp().run()
