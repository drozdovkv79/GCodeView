import os
import sys
import time
from collections import defaultdict

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv


class PerformanceLogger:
    """Логгер для замера времени обработки по типам элементов."""

    def __init__(self):
        self.stats = defaultdict(lambda: {"count": 0, "total_time": 0.0})
        self.start_time = time.time()

    def record(self, element_type, duration):
        """Записывает время обработки одного элемента."""
        self.stats[element_type]["count"] += 1
        self.stats[element_type]["total_time"] += duration

    def print_summary(self):
        """Выводит отсортированную таблицу производительности."""
        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY BY ELEMENT TYPE")
        print("=" * 60)
        print(
            f"{'Type':<30} | {'Count':>6} | {'Total Time (s)':>12} | {'Avg ms/obj':>10}"
        )
        print("-" * 60)

        # Сортируем по общему времени (самые долгие сверху)
        sorted_stats = sorted(
            self.stats.items(), key=lambda x: x[1]["total_time"], reverse=True
        )

        for type_name, data in sorted_stats:
            count = data["count"]
            total_t = data["total_time"]
            avg_ms = (total_t / count * 1000) if count > 0 else 0

            # Показываем только типы, которые заняли больше 0.01 сек или их много
            if total_t > 0.01 or count > 10:
                print(
                    f"{type_name:<30} | {count:>6} | {total_t:>12.4f} | {avg_ms:>10.2f}"
                )

        print("=" * 60)
        print(f"Total processing time: {time.time() - self.start_time:.2f}s")
        print("=" * 60 + "\n")


class FastIfcViewer:
    def __init__(self, ifc_path):
        if not os.path.exists(ifc_path):
            raise FileNotFoundError(f"File not found: {ifc_path}")

        self.ifc_path = ifc_path
        self.model = None
        self.settings = None
        self.perf_logger = PerformanceLogger()

    def init_settings(self):
        """
        Инициализирует настройки геометрии для максимальной скорости.
        """
        settings = ifcopenshell.geom.settings()

        flags = [
            ("USE_WORLD_COORDS", "use-world-coords", True),
            ("DISABLE_OPENING_SUBTRACTIONS", "disable-opening-subtractions", True),
            ("NO_NORMALS", "no-normals", True),
            ("APPLY_DEFAULT_MATERIALS", "apply-default-materials", False),
            ("TRIANGULATE", "triangulate", True),
            ("SEW_SHELLS", "sew-shells", False),
            ("INCLUDE_CURVES", "include-curves", False),
        ]

        for const_name, str_name, value in flags:
            try:
                attr = getattr(settings, const_name, None)
                if attr is not None:
                    settings.set(attr, value)
                else:
                    raise AttributeError
            except AttributeError:
                try:
                    settings.set(str_name, value)
                except Exception:
                    pass

        return settings

    def load_and_visualize(self):
        start_total = time.time()

        print(f"Loading IFC file: {self.ifc_path}")
        t0 = time.time()

        try:
            self.model = ifcopenshell.open(self.ifc_path)
        except Exception as e:
            print(f"Error opening file: {e}")
            return

        print(f"File loaded in {time.time() - t0:.2f}s")

        self.settings = self.init_settings()

        products = self.model.by_type("IfcProduct")
        print(f"Total IfcProduct elements: {len(products)}")

        elements_with_geom = []
        for p in products:
            if hasattr(p, "Representation") and p.Representation:
                elements_with_geom.append(p)

        print(f"Elements with geometry representations: {len(elements_with_geom)}")

        if not elements_with_geom:
            print("No geometry found in the file.")
            return

        print("Converting geometry to meshes...")
        t1 = time.time()

        batch_size = 500
        meshes_blocks = []

        batch_verts = []
        batch_faces = []
        batch_ids = []
        processed_count = 0

        for element in elements_with_geom:
            elem_type = element.is_a()
            elem_start = time.time()

            try:
                shape = ifcopenshell.geom.create_shape(self.settings, element)

                if not shape:
                    # Записываем даже неудачные попытки, если они заняли время
                    duration = time.time() - elem_start
                    self.perf_logger.record(elem_type, duration)
                    continue

                verts = shape.geometry.verts
                faces = shape.geometry.faces

                if not verts or not faces:
                    duration = time.time() - elem_start
                    self.perf_logger.record(elem_type, duration)
                    continue

                v = np.array(verts, dtype=np.float64).reshape(-1, 3)
                f = np.array(faces, dtype=np.int32).reshape(-1, 3)

                num_faces_in_elem = len(f)
                if num_faces_in_elem == 0:
                    duration = time.time() - elem_start
                    self.perf_logger.record(elem_type, duration)
                    continue

                batch_verts.append(v)
                batch_faces.append(f)

                elem_id_array = np.full(
                    num_faces_in_elem, element.GlobalId, dtype=object
                )
                batch_ids.append(elem_id_array)

                processed_count += 1

                # Замеряем время успешно обработанного элемента
                duration = time.time() - elem_start
                self.perf_logger.record(elem_type, duration)

                if processed_count % batch_size == 0:
                    combined_mesh = self._combine_batch(
                        batch_verts, batch_faces, batch_ids
                    )
                    if combined_mesh:
                        meshes_blocks.append(combined_mesh)

                    batch_verts = []
                    batch_faces = []
                    batch_ids = []

                    if processed_count % 1000 == 0:
                        elapsed = time.time() - t1
                        print(
                            f"  Processed {processed_count} elements in {elapsed:.1f}s..."
                        )

            except Exception as e:
                duration = time.time() - elem_start
                self.perf_logger.record(elem_type + "_ERROR", duration)
                continue

        # Обрабатываем последний пакет
        if batch_verts:
            combined_mesh = self._combine_batch(batch_verts, batch_faces, batch_ids)
            if combined_mesh:
                meshes_blocks.append(combined_mesh)

        conversion_time = time.time() - t1
        print(f"\nGeometry conversion completed in {conversion_time:.2f}s")

        # Выводим статистику производительности
        self.perf_logger.print_summary()

        if not meshes_blocks:
            print("No valid geometry was converted.")
            return

        # --- Визуализация ---
        print("Starting PyVista viewer...")
        plotter = pv.Plotter()

        for i, mesh in enumerate(meshes_blocks):
            plotter.add_mesh(
                mesh, color="lightgray", show_edges=False, smooth_shading=False
            )

        plotter.add_title(
            f"IFC Viewer: {os.path.basename(self.ifc_path)}\n{processed_count} elements"
        )
        plotter.show_axes()
        plotter.show()

        total_time = time.time() - start_total
        print(f"Session finished. Total time: {total_time:.2f}s")

    def _combine_batch(self, verts_list, faces_list, ids_list):
        if not verts_list:
            return None

        offset = 0
        combined_v = []
        combined_f = []
        combined_ids = []

        for v, f, ids in zip(verts_list, faces_list, ids_list):
            combined_v.append(v)
            combined_f.append(f + offset)
            combined_ids.append(ids)
            offset += len(v)

        if not combined_v:
            return None

        final_verts = np.vstack(combined_v)
        final_faces = np.vstack(combined_f)
        final_ids = np.concatenate(combined_ids)

        num_faces = len(final_faces)
        face_counts = np.full(num_faces, 3, dtype=np.int8)
        faces_pv = (
            np.hstack([face_counts.reshape(-1, 1), final_faces])
            .flatten()
            .astype(np.int64)
        )

        mesh = pv.PolyData(final_verts, faces_pv)
        mesh.cell_data["GlobalId"] = final_ids

        return mesh


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ifc_file_path = sys.argv[1]
    else:
        ifc_file_path = "/Users/drozdovkv/Downloads/Test2/43m.ifc"
        print(f"No file specified. Using default: {ifc_file_path}")
        print("Usage: python fast_ifc_viewer.py <path_to_ifc_file>")

    try:
        viewer = FastIfcViewer(ifc_file_path)
        viewer.load_and_visualize()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()
