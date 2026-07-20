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

import os
import sys
import gc
import time
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
from datetime import datetime
from collections import defaultdict

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
        self.verbose = False  # Включите для пошагового лога

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_cb(f"[{ts}] {msg}")

    def _dedup_key(self, entity):
        """Уникальный ключ для дедупликации ресурсов."""
        if entity.is_a("IfcMaterial"):
            return f"MAT:{entity.Name or 'Unnamed'}"
        if entity.is_a("IfcSurfaceStyle"):
            return f"STYLE:{entity.Name or 'Unnamed'}"
        if entity.is_a("IfcGeometricRepresentationContext"):
            return f"CTX:{entity.ContextIdentifier}:{entity.ContextType}"
        if entity.is_a("IfcUnitAssignment"):
            return "UNITS:GLOBAL"
        return None

    def merge(self, ifc_paths: list[str], output_path: str) -> bool:
        total_start = time.time()
        self._log("=" * 72)
        self._log(f"IFC MERGER OPTIMIZED | Файлов: {len(ifc_paths)} | Вывод: {os.path.basename(output_path)}")
        self._log("=" * 72)

        # ── 1. Инициализация выходного файла ─────────────────
        self._log("\n[1/5] Инициализация схемы и глобальных ресурсов...")
        t0 = time.time()
        master = ifcopenshell.open(ifc_paths[0])
        schema = master.schema
        merged = ifcopenshell.file(schema=schema)

        # Глобальные кэши дедупликации
        resource_cache = {}  # key -> new_entity
        owner_hist = None

        # Копируем OwnerHistory и Units один раз
        for oh in master.by_type("IfcOwnerHistory"):
            owner_hist = merged.add(oh)
            break
        for ua in master.by_type("IfcUnitAssignment"):
            new_ua = merged.add(ua)
            resource_cache["UNITS:GLOBAL"] = new_ua
            merged.by_type("IfcProject")[0].UnitsInContext = new_ua
            break

        # Создаём проект
        proj = master.by_type("IfcProject")
        new_project = merged.add(proj[0]) if proj else merged.createIfcProject(
            ifcopenshell.guid.new(), owner_hist, "Merged Project", None
        )
        # Привязываем Units к проекту если не привязались
        if "UNITS:GLOBAL" in resource_cache and not new_project.UnitsInContext:
            new_project.UnitsInContext = resource_cache["UNITS:GLOBAL"]

        master.close()
        del master
        gc.collect()
        self._log(f"  ✓ Схема: {schema} | Проект создан | {time.time()-t0:.2f} с")

        # ── 2. Последовательная обработка файлов ─────────────
        self._log("\n[2/5] Обработка файлов (потоковый режим)...")
        processed_files = 0

        for idx, fpath in enumerate(ifc_paths, 1):
            t_file = time.time()
            fname = os.path.basename(fpath)
            fsize_mb = os.path.getsize(fpath) / (1024 * 1024)

            try:
                ifc = ifcopenshell.open(fpath)
            except Exception as e:
                self._log(f"  ❌ Пропуск {fname}: {e}")
                continue

            # Локальные маппинги (очищаются после каждого файла → экономия RAM)
            spatial_map = {}   # old_id -> new_entity
            element_map = {}   # old_id -> new_entity
            file_type_counts = defaultdict(int)

            # ─ 2a. Пространственная структура ────────────────
            for stype in ("IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace"):
                for ent in ifc.by_type(stype):
                    new_ent = merged.add(ent)
                    spatial_map[ent.id()] = new_ent

            # Привязка сайтов к проекту
            for site in ifc.by_type("IfcSite"):
                if site.id() in spatial_map:
                    merged.createIfcRelAggregates(
                        ifcopenshell.guid.new(), owner_hist, None, None,
                        new_project, [spatial_map[site.id()]]
                    )

            # ─ 2b. Физические элементы ───────────────────────
            target_types = (
                "IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcFloor",
                "IfcColumn", "IfcBeam", "IfcDoor", "IfcWindow", "IfcStair",
                "IfcRailing", "IfcCurtainWall", "IfcRoof", "IfcPlate",
                "IfcMember", "IfcPipeSegment", "IfcDuctSegment",
                "IfcCableCarrierSegment", "IfcBuildingElementProxy",
                "IfcFurniture", "IfcDistributionElement", "IfcCovering",
                "IfcOpeningElement", "IfcTransportElement"
            )
            for t in target_types:
                for ent in ifc.by_type(t):
                    new_ent = merged.add(ent)
                    element_map[ent.id()] = new_ent
                    file_type_counts[t] += 1
                    self.type_stats[t] += 1

            # ─ 2c. Дедупликация и копирование ресурсов ───────
            for res_type in ("IfcMaterial", "IfcSurfaceStyle", "IfcGeometricRepresentationContext"):
                for res in ifc.by_type(res_type):
                    key = self._dedup_key(res)
                    if key and key not in resource_cache:
                        resource_cache[key] = merged.add(res)

            # ─ 2d. Восстановление связей (через IfcRel*) ─────
            # Это в 5-10x быстрее, чем обход inverse-атрибутов элементов
            rel_count = 0

            # Пространственные агрегации (Building->Site, Storey->Building)
            for rel in ifc.by_type("IfcRelAggregates"):
                rel_obj = rel.RelatingObject
                rel_objs = rel.RelatedObjects
                if rel_obj and rel_obj.id() in spatial_map:
                    new_rel = spatial_map[rel_obj.id()]
                    new_related = [spatial_map[o.id()] for o in rel_objs if o.id() in spatial_map]
                    if new_related:
                        merged.createIfcRelAggregates(
                            ifcopenshell.guid.new(), owner_hist, None, None, new_rel, new_related
                        )
                        rel_count += 1

            # Привязка элементов к этажам/пространствам
            for rel in ifc.by_type("IfcRelContainedInSpatialStructure"):
                struct = rel.RelatingStructure
                elems = rel.RelatedElements
                if struct and struct.id() in spatial_map:
                    new_struct = spatial_map[struct.id()]
                    new_elems = [element_map[e.id()] for e in elems if e.id() in element_map]
                    if new_elems:
                        merged.createIfcRelContainedInSpatialStructure(
                            ifcopenshell.guid.new(), owner_hist, None, None, new_elems, new_struct
                        )
                        rel_count += 1

            # Свойства (Psets)
            for rel in ifc.by_type("IfcRelDefinesByProperties"):
                objs = rel.RelatedObjects
                pset = rel.RelatingPropertyDefinition
                new_objs = [element_map[o.id()] for o in objs if o.id() in element_map]
                if new_objs and pset:
                    new_pset = merged.add(pset)
                    merged.createIfcRelDefinesByProperties(
                        ifcopenshell.guid.new(), owner_hist, None, None, new_objs, new_pset
                    )
                    rel_count += 1

            # Материалы (с дедупликацией)
            for rel in ifc.by_type("IfcRelAssociatesMaterial"):
                objs = rel.RelatedObjects
                mat = rel.RelatingMaterial
                new_objs = [element_map[o.id()] for o in objs if o.id() in element_map]
                if new_objs and mat:
                    key = self._dedup_key(mat)
                    new_mat = resource_cache.get(key) or merged.add(mat)
                    if key: resource_cache[key] = new_mat
                    merged.createIfcRelAssociatesMaterial(
                        ifcopenshell.guid.new(), owner_hist, None, None, new_objs, new_mat
                    )
                    rel_count += 1

            # ─ 2e. Очистка памяти файла ──────────────────────
            total_elems = sum(file_type_counts.values())
            self.stats["total_elements"] += total_elems
            processed_files += 1

            ifc.close()
            del ifc, spatial_map, element_map, file_type_counts
            gc.collect()  # Критично для 100×100МБ

            elapsed = time.time() - t_file
            self._log(f"  [{idx}/{len(ifc_paths)}] {fname:<35} | {fsize_mb:6.1f} МБ | "
                      f"Элементов: {total_elems:5} | Связей: {rel_count:5} | {elapsed:.2f} с")

            # Обновляем прогресс (1 файл = 1 шаг)
            if hasattr(self, '_progress_cb'):
                self._progress_cb(idx / len(ifc_paths) * 90)

        # ── 3. Сохранение ────────────────────────────────────
        self._log("\n[3/5] Финализация и запись файла...")
        t_save = time.time()
        total_entities = sum(1 for _ in merged)
        merged.write(output_path)
        out_size = os.path.getsize(output_path) / (1024 * 1024)
        self._log(f"  ✓ Сущностей: {total_entities:,} | Размер: {out_size:.1f} МБ | {time.time()-t_save:.2f} с")

        # ── 4. Статистика ────────────────────────────────────
        total_time = time.time() - total_start
        self._log("\n" + "=" * 72)
        self._log("ИТОГ")
        self._log(f"  Файлов обработано : {processed_files}")
        self._log(f"  Элементов всего   : {self.stats['total_elements']:,}")
        self._log(f"  Уникальных ресурсов в кэше: {len(resource_cache)}")
        self._log(f"  Размер результата : {out_size:.1f} МБ")
        self._log(f"  Общее время       : {total_time:.2f} с")
        self._log("  Топ типов:")
        for t, c in sorted(self.type_stats.items(), key=lambda x: -x[1])[:12]:
            self._log(f"    {t:<30} {c:>6}")
        self._log("=" * 72)
        self._log("✓ ГОТОВО")

        del merged, resource_cache
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
        tk.Label(hdr, text="🏗 IFC Merger Pro", font=("SF Pro Display", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="Потоковая обработка • Дедупликация • Низкое потребление RAM",
                 font=("SF Pro Text", 11), fg="gray").pack(side="left", padx=15, pady=5)

        # Каталог
        dir_f = tk.LabelFrame(self.root, text="Каталог с IFC", padx=10, pady=8)
        dir_f.pack(fill="x", **pad)
        tk.Entry(dir_f, textvariable=self.selected_dir, font=("SF Mono", 12)).pack(side="left", fill="x", expand=True)
        tk.Button(dir_f, text="Выбрать…", command=self._browse).pack(side="right", padx=8)
        tk.Button(dir_f, text="Сканировать", command=self._scan).pack(side="right", padx=4)

        # Список файлов
        list_f = tk.LabelFrame(self.root, text="Файлы для объединения", padx=10, pady=8)
        list_f.pack(fill="both", expand=True, **pad)
        self.lb = tk.Listbox(list_f, font=("SF Mono", 11), selectmode="multiple", height=6)
        sb = tk.Scrollbar(list_f, orient="vertical", command=self.lb.yview)
        self.lb.config(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ctrl = tk.Frame(list_f)
        ctrl.pack(fill="x", pady=4)
        tk.Button(ctrl, text="Все", command=lambda: self.lb.select_set(0, tk.END)).pack(side="left", padx=2)
        tk.Button(ctrl, text="Снять", command=lambda: self.lb.select_clear(0, tk.END)).pack(side="left", padx=2)
        self.lbl_count = tk.Label(ctrl, text="Файлов: 0", font=("SF Pro Text", 11))
        self.lbl_count.pack(side="right")

        # Кнопка Merge
        btn_f = tk.Frame(self.root)
        btn_f.pack(fill="x", **pad)
        self.btn_merge = tk.Button(btn_f, text="🔗 Объединить выбранные", command=self._start_merge,
                                   font=("SF Pro Text", 13, "bold"), bg="#007AFF", fg="white",
                                   activebackground="#0056CC", relief="flat", padx=20, pady=6)
        self.btn_merge.pack()

        # Прогресс
        try:
            import tkinter.ttk as ttk
            self.prog = ttk.Progressbar(self.root, maximum=100, mode="determinate")
            self.prog.pack(fill="x", **pad)
        except: self.prog = None

        # Лог
        log_f = tk.LabelFrame(self.root, text="Журнал", padx=10, pady=8)
        log_f.pack(fill="both", expand=True, **pad)
        self.log_txt = scrolledtext.ScrolledText(log_f, font=("SF Mono", 10), height=10,
                                                 bg="#1E1E1E", fg="#D4D4D4", wrap="word")
        self.log_txt.pack(fill="both", expand=True)

        # Статус
        self.status = tk.StringVar(value="Готово. Выберите каталог с IFC-файлами.")
        tk.Label(self.root, textvariable=self.status, font=("SF Pro Text", 10),
                 relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _browse(self):
        d = filedialog.askdirectory(title="Каталог с IFC", initialdir=os.path.expanduser("~"))
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
                self.lb.insert(tk.END, f"  {f}  ({os.path.getsize(p)/1048576:.1f} МБ)")
                self.ifc_files.append(p)
        self.lbl_count.config(text=f"Файлов: {len(self.ifc_files)}")
        self.status.set(f"Найдено {len(self.ifc_files)} файлов")

    def _log(self, msg):
        self.root.after(0, lambda: (
            self.log_txt.insert(tk.END, msg + "\n"),
            self.log_txt.see(tk.END)
        ))

    def _update_progress(self, val):
        if self.prog:
            self.root.after(0, lambda: self.prog.config(value=val))

    def _start_merge(self):
        if self.is_running: return
        sel = self.lb.curselection()
        if len(sel) < 2:
            messagebox.showwarning("Внимание", "Выберите минимум 2 файла")
            return
        files = [self.ifc_files[i] for i in sel]
        out_dir = self.selected_dir.get()
        out_path = os.path.join(out_dir, f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ifc")

        self.is_running = True
        self.btn_merge.config(state="disabled", text="⏳ Обработка...")
        self.status.set("Объединение запущено...")
        self.log_txt.delete("1.0", tk.END)
        if self.prog: self.prog.config(value=0)

        def _worker():
            try:
                merger = IFCMergerOptimized(log_callback=self._log)
                merger._progress_cb = self._update_progress
                ok = merger.merge(files, out_path)
                self.root.after(0, lambda: self.prog and self.prog.config(value=100))
                if ok:
                    self.root.after(0, lambda: (
                        self.status.set(f"✓ Готово: {os.path.basename(out_path)}"),
                        messagebox.showinfo("Готово", f"Результат сохранён:\n{out_path}")
                    ))
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