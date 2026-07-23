#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LAS → GLB Converter v6 (High-Perf / Tiled / Multiprocessing)
=============================================================

Оптимизации относительно v5:
  1. Chunked LAS read: laspy.open() + chunk_iterator — не грузит 30+ GB в RAM.
  2. Out-of-core per-tile processing: точки пишутся в per-tile temp файлы,
     каждый тайл обрабатывается независимо. RAM ограничена размером одного тайла.
  3. ProcessPoolExecutor: настоящая параллельность по ядрам (НЕ threading — GIL).
  4. Batched PCA normals: np.linalg.eigh на (N,3,3) — в ~5-10× быстрее
     per-point svd.
  5. Streaming GLB write: без np.zeros((N, 9)) промежуточного массива.
  6. Raster decimation (2D-сетка по X,Y): физически осмысленнее для 2.5D
     облака и быстрее 3D-вокселей.

Требования:
  pip install laspy numpy scipy matplotlib
  (опционально) pip install lazrs  — для .laz файлов
"""

import os
import sys
import json
import struct
import time
import queue
import threading
import multiprocessing as mp
import tempfile
import shutil
import platform
import subprocess
import warnings
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed, wait
from pathlib import Path

import numpy as np
import laspy
from scipy.spatial import cKDTree, Delaunay

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

warnings.filterwarnings('ignore')

CPU_COUNT = os.cpu_count() or 4


# =====================================================================
                  #  WORKER FUNCTIONS (TOP-LEVEL)
                  #  (для pickle — ProcessPoolExecutor)
# =====================================================================

TILE_HEADER_SIZE = 16  # 2 × uint64 (total_n, n_chunks)


def _append_tile_chunk(path, xyz, rgb):
    """
    Append a chunk of (xyz, rgb) points to a binary tile file.
    Format:
        [16 bytes header: total_n, n_chunks  (заполняется в _finalize_tile)]
        for each chunk:
            [4 bytes: chunk_n as uint32]
            [chunk_n * 12 bytes: xyz as float32]
            [chunk_n * 12 bytes: rgb as float32]
    """
    n = len(xyz)
    if n == 0:
        return
    xyz = np.ascontiguousarray(xyz, dtype=np.float32)
    rgb = np.ascontiguousarray(rgb, dtype=np.float32)
    new_file = not os.path.exists(path)
    with open(path, 'ab') as f:
        if new_file:
            f.write(struct.pack('<QQ', 0, 0))  # placeholders
        f.write(struct.pack('<I', n))
        f.write(xyz.tobytes())
        f.write(rgb.tobytes())


def _finalize_tile(path):
    """Пройтись по chunks, записать total_n и n_chunks в header."""
    total = 0
    n_chunks = 0
    with open(path, 'rb') as f:
        f.seek(TILE_HEADER_SIZE)
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                break
            n = struct.unpack('<I', hdr)[0]
            f.seek(n * 24, 1)  # skip xyz (12n) + rgb (12n)
            total += n
            n_chunks += 1
    with open(path, 'r+b') as f:
        f.seek(0)
        f.write(struct.pack('<QQ', total, n_chunks))


def _load_tile(path):
    """Load tile, returns (xyz, rgb) as float32."""
    with open(path, 'rb') as f:
        f.seek(TILE_HEADER_SIZE)
        xyz_chunks = []
        rgb_chunks = []
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                break
            n = struct.unpack('<I', hdr)[0]
            xyz = np.frombuffer(f.read(n * 12), dtype=np.float32).reshape(n, 3).copy()
            rgb = np.frombuffer(f.read(n * 12), dtype=np.float32).reshape(n, 3).copy()
            xyz_chunks.append(xyz)
            rgb_chunks.append(rgb)
    if not xyz_chunks:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))
    return (np.concatenate(xyz_chunks, axis=0),
            np.concatenate(rgb_chunks, axis=0))


# ---------------------------------------------------------------------
#  Decimation: 2D-raster (быстрее 3D-вокселей, физически осмысленнее)
# ---------------------------------------------------------------------

def raster_decimate(xyz, rgb, target_count):
    """
    2D-raster decimation. Усредняет все точки в каждой ячейке сетки X×Y.
    Z берётся как среднее (для 2.5D данных вроде lidar — это именно "крыша").
    """
    n = len(xyz)
    if n <= target_count:
        return (xyz.astype(np.float32, copy=False),
                rgb.astype(np.float32, copy=False))

    bbox_xy = xyz[:, :2]
    extent = np.array([
        bbox_xy[:, 0].max() - bbox_xy[:, 0].min(),
        bbox_xy[:, 1].max() - bbox_xy[:, 1].min(),
    ])
    extent = np.where(extent == 0, 1.0, extent)
    area = extent[0] * extent[1]

    # Бинарный поиск хорошего cell_size
    cell = float(np.sqrt(area / target_count))
    lo, hi = cell * 0.3, cell * 3.0
    for _ in range(6):
        cell = (lo + hi) / 2
        kx = np.floor(xyz[:, 0] / cell).astype(np.int64)
        ky = np.floor(xyz[:, 1] / cell).astype(np.int64)
        n_unique = len(np.unique(kx * (1 << 32) + ky))
        if n_unique > target_count * 1.2:
            lo = cell
        elif n_unique < target_count * 0.8:
            hi = cell
        else:
            break

    # Финальная агрегация
    kx = np.floor(xyz[:, 0] / cell).astype(np.int64)
    ky = np.floor(xyz[:, 1] / cell).astype(np.int64)
    key = kx * (1 << 32) + ky
    sort_idx = np.argsort(key, kind='stable')
    s_key = key[sort_idx]
    s_xyz = xyz[sort_idx]
    s_rgb = rgb[sort_idx]

    diff = np.diff(s_key)
    starts = np.concatenate([[0], np.where(diff != 0)[0] + 1])
    ends = np.concatenate([starts[1:], [len(s_key)]])
    n_groups = len(starts)

    counts = (ends - starts).astype(np.float32)
    new_xyz = np.zeros((n_groups, 3), dtype=np.float32)
    new_xyz[:, 0] = np.add.reduceat(s_xyz[:, 0], starts) / counts
    new_xyz[:, 1] = np.add.reduceat(s_xyz[:, 1], starts) / counts
    new_xyz[:, 2] = np.add.reduceat(s_xyz[:, 2], starts) / counts

    new_rgb = np.zeros((n_groups, 3), dtype=np.float32)
    new_rgb[:, 0] = np.add.reduceat(s_rgb[:, 0], starts) / counts
    new_rgb[:, 1] = np.add.reduceat(s_rgb[:, 1], starts) / counts
    new_rgb[:, 2] = np.add.reduceat(s_rgb[:, 2], starts) / counts

    if len(new_xyz) > target_count:
        sel = np.random.choice(len(new_xyz), target_count, replace=False)
        new_xyz = new_xyz[sel]
        new_rgb = new_rgb[sel]

    return new_xyz, np.clip(new_rgb, 0.0, 1.0)


# ---------------------------------------------------------------------
#  Normals: batched EVD вместо per-point SVD
# ---------------------------------------------------------------------

def batched_pca_normals(points, k_neighbors):
    """
    Batched оценка нормалей через EVD ковариационной матрицы.
    В ~5-10× быстрее цикла по точкам с np.linalg.svd.
    """
    n = len(points)
    if n < 3:
        return np.tile([0, 0, 1], (max(n, 1), 1)).astype(np.float32)

    k = min(k_neighbors + 1, n)
    tree = cKDTree(points)
    _, indices = tree.query(points, k=k, workers=-1)
    indices = indices[:, 1:]  # drop self
    k = indices.shape[1]

    neighbors = points[indices]                         # (N, k, 3)
    centroids = neighbors.mean(axis=1, keepdims=True)
    centered = neighbors - centroids                     # (N, k, 3)

    # Ковариация: einsum — самое быстрое для батча
    cov = np.einsum('nki,nkj->nij', centered, centered) / k
    cov = (cov + cov.transpose(0, 2, 1)) * 0.5           # симметризация

    eigvals, eigvecs = np.linalg.eigh(cov)              # по возрастанию
    normals = eigvecs[:, :, 0]                          # наименьшее собств. значение

    # Ориентируем вверх по Z
    flip = normals[:, 2] < 0
    normals[flip] *= -1

    # Нормализация
    norm = np.linalg.norm(normals, axis=1, keepdims=True)
    norm = np.where(norm < 1e-10, 1.0, norm)
    normals = normals / norm

    return normals.astype(np.float32, copy=False)


# ---------------------------------------------------------------------
#  Mesh: 2D Delaunay
# ---------------------------------------------------------------------

def build_mesh(points, normals, colors, max_vertices):
    """Delaunay 2D + фильтр вырожденных треугольников. Fallback — fan."""
    if len(points) < 3:
        raise ValueError(f"Need >= 3 points, got {len(points)}")

    try:
        tri = Delaunay(points[:, :2])
        triangles = tri.simplices

        p1 = points[triangles[:, 0]]
        p2 = points[triangles[:, 1]]
        p3 = points[triangles[:, 2]]
        cross = np.cross(p2 - p1, p3 - p1)
        areas = 0.5 * np.linalg.norm(cross, axis=1)
        triangles = triangles[areas > 1e-10]
    except Exception:
        n = len(points)
        if n < 3:
            triangles = np.zeros((0, 3), dtype=np.uint32)
        else:
            triangles = np.zeros((n - 2, 3), dtype=np.uint32)
            triangles[:, 0] = 0
            triangles[:, 1] = np.arange(1, n - 1)
            triangles[:, 2] = np.arange(2, n)

    return points, triangles.astype(np.uint32), colors, normals


# ---------------------------------------------------------------------
#  GLB write: streaming, без N×9 промежуточного массива
# ---------------------------------------------------------------------
def write_glb_streaming(points, triangles, colors, normals, output_path, material_mode='basic'):
    """
    Пишет GLB напрямую в файл.
    ВАЖНО: Данные пишутся ПОСЛЕДОВАТЕЛЬНО (POS -> NORM -> COLOR),
    поэтому в bufferViews убран byteStride и созданы отдельные view для каждого атрибута.
    Также добавлена конвертация осей Z-up -> Y-up для glTF.
    """
    if len(triangles) == 0:
        raise ValueError("No triangles to write")

    n_v = len(points)
    n_t = len(triangles)

    # Конвертация осей: LAS (Z-up) -> glTF (Y-up)
    # Меняем местами Y и Z
    points_gl = points.copy()
    points_gl[:, 1], points_gl[:, 2] = points[:, 2], points[:, 1]

    normals_gl = normals.copy()
    normals_gl[:, 1], normals_gl[:, 2] = normals[:, 2], normals[:, 1]

    points_gl = np.ascontiguousarray(points_gl, dtype=np.float32)
    normals_gl = np.ascontiguousarray(normals_gl, dtype=np.float32)
    colors = np.ascontiguousarray(np.clip(colors, 0.0, 1.0), dtype=np.float32)

    pmax = points_gl.max(axis=0).tolist()
    pmin = points_gl.min(axis=0).tolist()

    gltf = {
        "asset": {"version": "2.0", "generator": "LAS→GLB v6 (Optimized)"},
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
                "metallicFactor": 0.0,
                "roughnessFactor": 0.8,
            },
            "doubleSided": True,
            "alphaMode": "OPAQUE",
        }],
        "accessors": [
            # 0: POSITION
            {"bufferView": 0, "byteOffset": 0, "componentType": 5126, "count": n_v, "type": "VEC3", "max": pmax, "min": pmin},
            # 1: NORMAL
            {"bufferView": 1, "byteOffset": 0, "componentType": 5126, "count": n_v, "type": "VEC3"},
            # 2: COLOR_0
            {"bufferView": 2, "byteOffset": 0, "componentType": 5126, "count": n_v, "type": "VEC3"},
            # 3: INDICES
            {"bufferView": 3, "byteOffset": 0, "componentType": 5125, "count": n_t * 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            # Раздельные bufferViews вместо одного interleaved
            {"buffer": 0, "byteOffset": 0,         "byteLength": n_v * 12, "target": 34962},
            {"buffer": 0, "byteOffset": n_v * 12,  "byteLength": n_v * 12, "target": 34962},
            {"buffer": 0, "byteOffset": n_v * 24,  "byteLength": n_v * 12, "target": 34962},
            {"buffer": 0, "byteOffset": n_v * 36,  "byteLength": n_t * 12, "target": 34963},
        ],
        "buffers": [{"byteLength": n_v * 36 + n_t * 12}],
    }

    if material_mode == 'basic':
        gltf["materials"][0]["extensions"] = {"KHR_materials_unlit": {}}
        gltf["extensionsUsed"] = ["KHR_materials_unlit"]

    json_bytes = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b' ' * pad

    json_chunk_len = len(json_bytes)
    bin_chunk_len = n_v * 36 + n_t * 12
    total = 12 + 8 + json_chunk_len + 8 + bin_chunk_len

    with open(output_path, 'wb') as f:
        # Заголовок GLB
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        # JSON chunk
        f.write(struct.pack('<II', json_chunk_len, 0x4E4F534A))
        f.write(json_bytes)
        # BIN chunk
        f.write(struct.pack('<II', bin_chunk_len, 0x004E4942))

        # Запись данных (строго последовательная, как описано в bufferViews)
        f.write(points_gl.tobytes())  # 12 * n_v байт
        f.write(normals_gl.tobytes()) # 12 * n_v байт
        f.write(colors.tobytes())     # 12 * n_v байт

        idx = triangles.astype(np.uint32).ravel()
        idx_bytes = idx.tobytes()
        # Отступ до 4 байт (хотя n_t * 12 всегда кратно 4, оставляем для безопасности)
        idx_pad = (4 - len(idx_bytes) % 4) % 4
        f.write(idx_bytes)
        if idx_pad:
            f.write(b'\x00' * idx_pad)

def write_glb_streaming1(points, triangles, colors, normals, output_path, material_mode='basic'):
    """
    Пишет GLB напрямую в файл. Не создаёт np.zeros((N, 9)).
    Layout: pos(12N) | norm(12N) | col(12N) | idx(12T) — interleaved по vertex
    благодаря byteStride=36 + accessor byteOffset 0/12/24.
    """
    if len(triangles) == 0:
        raise ValueError("No triangles to write")

    n_v = len(points)
    n_t = len(triangles)

    points = np.ascontiguousarray(points, dtype=np.float32)
    normals = np.ascontiguousarray(normals, dtype=np.float32)
    colors = np.ascontiguousarray(np.clip(colors, 0.0, 1.0), dtype=np.float32)

    pmax = points.max(axis=0).tolist()
    pmin = points.min(axis=0).tolist()

    gltf = {
        "asset": {"version": "2.0", "generator": "LAS→GLB v6 (Optimized)"},
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
                "metallicFactor": 0.0,
                "roughnessFactor": 0.8,
            },
            "doubleSided": True,
            "alphaMode": "OPAQUE",
        }],
        "accessors": [
            {"bufferView": 0, "byteOffset": 0, "componentType": 5126,
             "count": n_v, "type": "VEC3", "max": pmax, "min": pmin},
            {"bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": n_v, "type": "VEC3"},
            {"bufferView": 0, "byteOffset": 24, "componentType": 5126, "count": n_v, "type": "VEC3"},
            {"bufferView": 1, "byteOffset": 0, "componentType": 5125, "count": n_t * 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": n_v * 36, "target": 34962, "byteStride": 36},
            {"buffer": 0, "byteOffset": n_v * 36, "byteLength": n_t * 12, "target": 34963},
        ],
        "buffers": [{"byteLength": n_v * 36 + n_t * 12}],
    }

    if material_mode == 'basic':
        gltf["materials"][0]["extensions"] = {"KHR_materials_unlit": {}}
        gltf["extensionsUsed"] = ["KHR_materials_unlit"]

    json_bytes = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b' ' * pad

    json_chunk_len = len(json_bytes)
    bin_chunk_len = n_v * 36 + n_t * 12
    total = 12 + 8 + json_chunk_len + 8 + bin_chunk_len

    with open(output_path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', json_chunk_len, 0x4E4F534A))
        f.write(json_bytes)
        f.write(struct.pack('<II', bin_chunk_len, 0x004E4942))
        f.write(points.tobytes())
        f.write(normals.tobytes())
        f.write(colors.tobytes())
        idx = triangles.astype(np.uint32).ravel()
        idx_bytes = idx.tobytes()
        idx_pad = (4 - len(idx_bytes) % 4) % 4
        f.write(idx_bytes)
        if idx_pad:
            f.write(b'\x00' * idx_pad)


# ---------------------------------------------------------------------
#  Worker: один тайл end-to-end
# ---------------------------------------------------------------------

def process_tile_worker(args):
    """
    Runs in a separate process. Полный пайплайн для одного тайла:
    load -> decimate -> normals -> mesh -> GLB.
    """
    (tile_id, tile_path, output_path, decimate_target, k_neighbors,
     max_vertices, color_mode, material_mode, log_queue) = args

    t0 = time.time()
    tag = f"tile_{tile_id:04d}"

    try:
        log_queue.put(('log_tiles', f"[{tag}] Loading..."))
        xyz, rgb = _load_tile(tile_path)
        n_in = len(xyz)

        if n_in < 3:
            log_queue.put(('log_tiles', f"[{tag}] Only {n_in} pts, skip"))
            return {'tile_id': tile_id, 'skipped': True, 'time': time.time() - t0}

        log_queue.put(('log_tiles', f"[{tag}] Loaded {n_in:,} points"))

        # 1) Decimation
        if n_in > decimate_target:
            t_d = time.time()
            log_queue.put(('log_perf', f"[{tag}] Decimating {n_in:,} -> ~{decimate_target:,}"))
            xyz, rgb = raster_decimate(xyz, rgb, decimate_target)
            log_queue.put(('log_perf', f"[{tag}] Decimated to {len(xyz):,} in {time.time()-t_d:.1f}s"))

        # 2) Color mode
        if color_mode == 'gray':
            gray = (0.299 * rgb[:, 0] + 0.587 * rgb[:, 1] + 0.114 * rgb[:, 2])
            rgb = np.column_stack([gray, gray, gray]).astype(np.float32)

        # 3) Normals (batched EVD)
        k_n = min(k_neighbors, max(3, len(xyz) - 1))
        t_n = time.time()
        log_queue.put(('log_perf', f"[{tag}] Normals k={k_n}, pts={len(xyz):,}"))
        normals = batched_pca_normals(xyz, k_n)
        log_queue.put(('log_perf', f"[{tag}] Normals done in {time.time()-t_n:.1f}s"))

        # 4) Mesh
        t_m = time.time()
        log_queue.put(('log_perf', f"[{tag}] Building mesh..."))
        points, triangles, colors, normals = build_mesh(xyz, normals, rgb, max_vertices)
        log_queue.put(('log_perf',
                       f"[{tag}] Mesh: {len(points):,}v / {len(triangles):,}t "
                       f"in {time.time()-t_m:.1f}s"))

        if len(triangles) == 0:
            return {'tile_id': tile_id, 'skipped': True, 'time': time.time() - t0}

        # 5) GLB write
        t_w = time.time()
        log_queue.put(('log_perf', f"[{tag}] Writing GLB..."))
        write_glb_streaming(points, triangles, colors, normals, output_path, material_mode)
        log_queue.put(('log_perf', f"[{tag}] GLB written in {time.time()-t_w:.1f}s"))

        result = {
            'tile_id': tile_id,
            'output': output_path,
            'n_in': n_in,
            'n_verts': len(points),
            'n_tris': len(triangles),
            'time': time.time() - t0,
        }
        log_queue.put(('tile_done', result))
        return result

    except Exception as e:
        log_queue.put(('error', f"[{tag}] {e}\n{traceback.format_exc()}"))
        return {'tile_id': tile_id, 'error': str(e)}


# =====================================================================
                  #  CORE PIPELINE
# =====================================================================

def get_las_info(las_path):
    """
    Только заголовок LAS — без загрузки точек. Возвращает bbox, count, color flag.
    """
    with laspy.open(las_path) as f:
        hdr = f.header
        # Padding на всякий случай (реальные точки могут выходить за header bounds)
        eps = 1e-3
        xmin = float(hdr.mins[0]) - eps
        ymin = float(hdr.mins[1]) - eps
        xmax = float(hdr.maxs[0]) + eps
        ymax = float(hdr.maxs[1]) + eps
        n_points = int(hdr.point_count)
        version = str(hdr.version)
        point_format = int(hdr.point_format.id)
        # Цвет: проверяем через sample, чтобы не угадывать
        sample = next(iter(f.chunk_iterator(10)))
        has_color = hasattr(sample, 'red')

    return {
        'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax,
        'n_points': n_points, 'version': version, 'point_format': point_format,
        'has_color': has_color,
    }


def stream_las_to_tiles(las_path, tile_dir, xmin, ymin, tw, tl, overlap, nx, ny,
                        chunk_size, log_queue, cancel_event, progress_cb=None):
    """
    Pass 1: стримит LAS чанками, раскидывает точки по per-tile .bin файлам.
    Возвращает {tile_id: tile_path} для непустых тайлов.
    RAM: O(chunk_size) — 24 МБ на 1М точек.
    """
    tile_paths = {}
    ny_t = ny

    with laspy.open(las_path) as f:
        total = f.header.point_count
        if progress_cb:
            progress_cb(0, total, f"Pass 1: 0 / {total:,} pts")

        processed = 0
        chunk_idx = 0
        for chunk in f.chunk_iterator(chunk_size):
            if cancel_event.is_set():
                raise InterruptedError("Cancelled during pass 1")

            xyz = np.column_stack([
                np.asarray(chunk.x, dtype=np.float32),
                np.asarray(chunk.y, dtype=np.float32),
                np.asarray(chunk.z, dtype=np.float32),
            ])

            has_color = hasattr(chunk, 'red')
            if has_color:
                r = np.asarray(chunk.red, dtype=np.float32)
                g = np.asarray(chunk.green, dtype=np.float32)
                b = np.asarray(chunk.blue, dtype=np.float32)
                m = max(int(r.max()) if len(r) else 0,
                        int(g.max()) if len(g) else 0,
                        int(b.max()) if len(b) else 0, 1)
                scale = 65535.0 if m > 255 else 255.0
                rgb = np.column_stack([r, g, b]) / scale
            else:
                rgb = np.full((len(xyz), 3), 0.5, dtype=np.float32)

            # Tile assignment
            ix = np.clip(((xyz[:, 0] - xmin) / tw).astype(np.int64), 0, nx - 1)
            iy = np.clip(((xyz[:, 1] - ymin) / tl).astype(np.int64), 0, ny - 1)
            tile_idx = ix * ny_t + iy

            # Сортируем и режем на группы по тайлам — для последовательной записи
            sort_order = np.argsort(tile_idx, kind='stable')
            s_tiles = tile_idx[sort_order]
            s_xyz = xyz[sort_order]
            s_rgb = rgb[sort_order]

            diff = np.diff(s_tiles)
            starts = np.concatenate([[0], np.where(diff != 0)[0] + 1, [len(s_tiles)]])

            for bi in range(len(starts) - 1):
                s, e = starts[bi], starts[bi + 1]
                t = int(s_tiles[s])
                if t not in tile_paths:
                    tile_paths[t] = os.path.join(tile_dir, f"tile_{t:06d}.bin")
                _append_tile_chunk(tile_paths[t], s_xyz[s:e], s_rgb[s:e])

            processed += len(xyz)
            chunk_idx += 1

            if chunk_idx % 5 == 0 and progress_cb:
                progress_cb(processed, total,
                            f"Pass 1: {processed:,} / {total:,} pts")

    # Финализируем заголовки всех файлов
    log_queue.put(('log_tiles', f"Finalizing {len(tile_paths)} tile files..."))
    for path in tile_paths.values():
        _finalize_tile(path)

    return tile_paths


def run_conversion(params, log_queue, cancel_event,
                   progress_cb, status_cb, all_done_cb, error_cb):
    """
    Оркестратор. Запускается в daemon-потоке GUI.
    Pass 1: stream_las_to_tiles (низкая RAM).
    Pass 2: ProcessPoolExecutor по тайлам (настоящий параллелизм).
    """
    temp_dir = None
    try:
        las_path = params['las_path']
        output_dir = params['output_dir']
        tw = float(params['tw'])
        tl = float(params['tl'])
        overlap = float(params['overlap'])
        chunk_size = int(params['chunk_size'])
        n_workers = int(params['n_workers'])
        cleanup = bool(params['cleanup_temp'])
        use_tiling = bool(params['use_tiling'])
        decimate_target = int(params['decimate_target'])
        k_neighbors = int(params['k_neighbors'])
        max_vertices = int(params['max_vertices'])
        color_mode = params['color_mode']
        material_mode = params['material_mode']

        if not use_tiling:
            log_queue.put(('error', "Single-GLB режим не поддерживается в v6 — используйте тайлинг"))
            return

        os.makedirs(output_dir, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix='las_tiles_')
        log_queue.put(('log_main', f"=== Конвертация {os.path.basename(las_path)} ==="))
        log_queue.put(('log_main', f"Выход: {output_dir}"))
        log_queue.put(('log_main', f"Temp:   {temp_dir}"))
        log_queue.put(('log_main', f"Воркеров: {n_workers}, чанк: {chunk_size:,} pts"))

        total_start = time.time()

        # === Pass 0: bounds ===
        status_cb("Чтение заголовка LAS...")
        log_queue.put(('log_main', "Pass 0: чтение заголовка LAS..."))
        las_info = get_las_info(las_path)
        xmin, ymin = las_info['xmin'], las_info['ymin']
        xmax, ymax = las_info['xmax'], las_info['ymax']
        n_points = las_info['n_points']
        has_color = las_info['has_color']

        log_queue.put(('log_las', f"Bounds: X[{xmin:.2f}, {xmax:.2f}] Y[{ymin:.2f}, {ymax:.2f}]"))
        log_queue.put(('log_las', f"Total points: {n_points:,}"))
        log_queue.put(('log_las', f"Point format: {las_info['point_format']}, color: {has_color}"))

        nx = max(1, int(np.ceil((xmax - xmin) / tw)))
        ny = max(1, int(np.ceil((ymax - ymin) / tl)))
        n_tiles = nx * ny
        log_queue.put(('log_main', f"Тайлинг: {nx}×{ny} = {n_tiles} тайлов"))
        log_queue.put(('log_tiles', f"Tile size: {tw}×{tl} m, overlap: {overlap} m"))

        # === Pass 1: stream to tiles ===
        status_cb("Pass 1: разбиение LAS по тайлам...")
        log_queue.put(('log_main', "Pass 1: streaming LAS → temp файлы тайлов"))

        def pass1_progress(processed, total, msg):
            pct = 5 + (processed / max(total, 1)) * 35
            progress_cb(pct, msg)
            status_cb(msg)

        tile_paths = stream_las_to_tiles(
            las_path, temp_dir, xmin, ymin, tw, tl, overlap, nx, ny,
            chunk_size, log_queue, cancel_event, progress_cb=pass1_progress
        )
        n_nonempty = len(tile_paths)
        log_queue.put(('log_main', f"Pass 1 done: {n_nonempty} non-empty tiles"))
        log_queue.put(('log_tiles', f"Non-empty: {n_nonempty} / {n_tiles}"))

        if cancel_event.is_set():
            raise InterruptedError("Cancelled after pass 1")

        if n_nonempty == 0:
            log_queue.put(('log_main', "Нет точек — конвертация невозможна"))
            progress_cb(100, "Готово (пусто)")
            all_done_cb({'files': [], 'n_files': 0, 'total_verts': 0, 'total_tris': 0})
            return

        # === Pass 2: parallel processing ===
        status_cb(f"Pass 2: параллельная обработка ({n_workers} воркеров)...")
        log_queue.put(('log_main', f"Pass 2: ProcessPoolExecutor × {n_workers}"))

        base_name = Path(las_path).stem
        jobs = []
        for tile_id, tile_path in tile_paths.items():
            i = tile_id // ny
            j = tile_id % ny
            output_path = os.path.join(output_dir, f"{base_name}_tile_{i:03d}_{j:03d}.glb")
            jobs.append((tile_id, tile_path, output_path,
                         decimate_target, k_neighbors, max_vertices,
                         color_mode, material_mode, log_queue))

        # Сортируем задачи по tile_id для предсказуемого порядка в логах
        jobs.sort(key=lambda x: x[0])

        results = []
        tiles_done = 0
        progress_per_tile = 50.0 / max(1, n_nonempty)

        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(process_tile_worker, job): job[0] for job in jobs}

            for future in as_completed(futures):
                if cancel_event.is_set():
                    log_queue.put(('log_main', "Отмена: прекращаем ожидание"))
                    break
                try:
                    result = future.result(timeout=300)
                    if result and 'error' not in result:
                        results.append(result)
                        if not result.get('skipped'):
                            log_queue.put(('log_main',
                                f"✓ Tile {result['tile_id']:04d}: "
                                f"{result['n_in']:,}→{result['n_verts']:,}v/{result['n_tris']:,}t "
                                f"({result['time']:.1f}s)"))
                except Exception as e:
                    log_queue.put(('log_main', f"Tile exception: {e}"))

                tiles_done += 1
                pct = 40 + tiles_done * progress_per_tile
                msg = f"Pass 2: {tiles_done} / {n_nonempty} tiles"
                progress_cb(pct, msg)
                status_cb(msg)

        if cancel_event.is_set():
            raise InterruptedError("Cancelled during pass 2")

        # === Summary ===
        total_v = sum(r.get('n_verts', 0) for r in results)
        total_t = sum(r.get('n_tris', 0) for r in results)
        total_t_in = sum(r.get('n_in', 0) for r in results)
        total_wall = time.time() - total_start
        files = [r['output'] for r in results if r.get('output')]

        log_queue.put(('log_main', "=" * 50))
        log_queue.put(('log_main',
            f"Готово! Файлов: {len(files)}, "
            f"исх. точек: {total_t_in:,}, "
            f"вершин: {total_v:,}, треуг: {total_t:,}"))
        log_queue.put(('log_main', f"Общее время: {total_wall:.1f} сек"))

        # Генерация карты тайлов
        try:
            grid_img = _create_grid_map(
                output_dir, base_name, nx, ny, tw, tl,
                xmin, ymin, xmax, ymax, overlap,
                set(tile_paths.keys()), log_queue
            )
            if grid_img:
                files.insert(0, grid_img)
                log_queue.put(('log_main', f"Карта тайлов: {grid_img}"))
        except Exception as e:
            log_queue.put(('log_main', f"⚠️ Не удалось создать карту: {e}"))

        all_done_cb({
            'files': files,
            'n_files': len([f for f in files if f.endswith('.glb')]),
            'total_in_points': total_t_in,
            'total_verts': total_v,
            'total_tris': total_t,
            'time': total_wall,
        })

    except InterruptedError as e:
        log_queue.put(('log_main', f"Отменено: {e}"))
    except Exception as e:
        log_queue.put(('error', f"{e}\n{traceback.format_exc()}"))
        error_cb(str(e))
    finally:
        if cleanup and temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            log_queue.put(('log_main', "Временные файлы удалены"))


def _create_grid_map(output_dir, base_name, nx, ny, tw, tl,
                     xmin, ymin, xmax, ymax, overlap, non_empty_tiles, log_queue):
    """PNG с сеткой тайлов (та же логика, что в v5)."""
    try:
        def wrap_text(text, max_chars=12):
            parts = text.split('_')
            lines, cur = [], ""
            for part in parts:
                if not cur:
                    cur = part
                elif len(cur) + len(part) + 1 <= max_chars:
                    cur += '_' + part
                else:
                    lines.append(cur)
                    cur = part
                while len(cur) > max_chars:
                    lines.append(cur[:max_chars])
                    cur = cur[max_chars:]
            if cur:
                lines.append(cur)
            return '\n'.join(lines)

        font_size = max(4, min(10, 400 / max(nx, ny)))
        fig_w = max(8, nx * 0.8)
        fig_h = max(8, ny * 0.8)
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        grid_xmax = xmin + nx * tw
        grid_ymax = ymin + ny * tl

        for i in range(nx):
            for j in range(ny):
                x0 = xmin + i * tw
                y0 = ymin + j * tl
                is_non_empty = (i * ny + j) in non_empty_tiles
                face_color = 'lightgreen' if is_non_empty else 'lightgray'
                edge_color = 'green' if is_non_empty else 'gray'
                rect = patches.Rectangle(
                    (x0, y0), tw, tl,
                    linewidth=1, edgecolor=edge_color,
                    facecolor=face_color, alpha=0.6,
                )
                ax.add_patch(rect)
                fname = f"{base_name}_tile_{i:03d}_{j:03d}.glb"
                label = fname if is_non_empty else "Пусто"
                rotation = 90 if tw < tl * 0.5 else 0
                text_obj = ax.text(
                    x0 + tw/2, y0 + tl/2, wrap_text(label, 12),
                    ha='center', va='center', fontsize=font_size,
                    color='black', rotation=rotation,
                )
                text_obj.set_clip_path(rect)

        margin_x = tw * 0.05
        margin_y = tl * 0.05
        ax.set_xlim(xmin - margin_x, grid_xmax + margin_x)
        ax.set_ylim(ymin - margin_y, grid_ymax + margin_y)
        ax.set_aspect('equal', adjustable='box')
        ax.set_title(f"Карта тайлов: {nx}×{ny}", fontsize=14)
        ax.set_xlabel("X (м)")
        ax.set_ylabel("Y (м)")
        ax.grid(True, linestyle=':', alpha=0.5)

        img_path = os.path.join(output_dir, f"{base_name}_grid_map.png")
        plt.tight_layout()
        plt.savefig(img_path, dpi=150)
        plt.close(fig)
        return img_path
    except Exception:
        log_queue.put(('log_main', "⚠️ matplotlib недоступен, карта пропущена"))
        return None


# =====================================================================
                  #  GUI
# =====================================================================

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
            ("tiles", "Тайлы"),
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
        self.root.title("Конвертер LAS → GLB (High-Perf v6 — Tiled + Multiprocessing)")
        self.root.geometry("800x900")
        self.root.resizable(True, True)

        # === State ===
        self.input_file = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.max_vertices = tk.IntVar(value=100_000)
        self.k_neighbors = tk.IntVar(value=15)
        self.decimate_before = tk.IntVar(value=500_000)
        self.open_after_convert = tk.BooleanVar(value=True)
        self.color_mode = tk.StringVar(value="color")
        self.material_mode = tk.StringVar(value="basic")
        self.status = tk.StringVar(value="Готов к работе")
        self.progress = tk.DoubleVar(value=0)

        # Tiling
        self.use_tiling = tk.BooleanVar(value=True)
        self.tile_width = tk.DoubleVar(value=100.0)
        self.tile_length = tk.DoubleVar(value=100.0)
        self.tile_overlap = tk.DoubleVar(value=0.0)
        self.open_first_tile_only = tk.BooleanVar(value=True)

        # Multiprocessing (NEW)
        self.use_all_cores = tk.BooleanVar(value=False)
        self.chunk_size_m = tk.DoubleVar(value=2.0)  # млн точек
        self.cleanup_temp = tk.BooleanVar(value=True)

        # Cross-process state
        self._cancel_event = mp.Event()
        self._cancel_event.clear()
        self._manager = None
        self._log_queue = None
        self._poller_after_id = None
        self._worker_thread = None

        self.log_window = LogWindow(root)
        self.log_window.hide()

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        ttk.Label(main_frame,
                 text="Конвертер LAS → GLB v6 (Multiprocessing)",
                 font=("Arial", 16, "bold")
                 ).grid(row=0, column=0, columnspan=3, pady=10)

        # === Input / Output ===
        ttk.Label(main_frame, text="Входной LAS:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.input_file, width=50).grid(
            row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_input_file).grid(
            row=1, column=2, padx=5, pady=5)

        ttk.Label(main_frame, text="Выходная папка:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.output_dir, width=50).grid(
            row=2, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
        ttk.Button(main_frame, text="Обзор...", command=self.select_output_dir).grid(
            row=2, column=2, padx=5, pady=5)

        ttk.Separator(main_frame, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # === Parameters ===
        params_frame = ttk.LabelFrame(main_frame, text="Параметры меша", padding="10")
        params_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        params_frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(params_frame, text="Макс. вершин в тайле:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=2_000_000, increment=10_000,
                    textvariable=self.max_vertices, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(финальное упрощение)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Децимация (точек/тайл):").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=1_000, to=10_000_000, increment=50_000,
                    textvariable=self.decimate_before, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(до нормалей)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Соседей для нормалей:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=3, to=100,
                    textvariable=self.k_neighbors, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(больше = точнее, медленнее)").grid(row=row, column=2, sticky=tk.W, padx=5, pady=2)

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

        # === Tiling ===
        row += 1
        ttk.Separator(params_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        row += 1
        ttk.Checkbutton(params_frame,
                       text="Разбить на тайлы (рекомендуется для 30+ GB)",
                       variable=self.use_tiling).grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(params_frame, text="Ширина тайла (м, X):").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=5, to=100_000, increment=10,
                    textvariable=self.tile_width, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Длина тайла (м, Y):").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=5, to=100_000, increment=10,
                    textvariable=self.tile_length, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Label(params_frame, text="Перекрытие (м):").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=0, to=1000, increment=1,
                    textvariable=self.tile_overlap, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)

        # === NEW: Multiprocessing ===
        row += 1
        ttk.Separator(params_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)

        row += 1
        n_cpu = os.cpu_count() or 4
        ttk.Checkbutton(params_frame,
                       text=f"Использовать все {n_cpu} ядер (по умолчанию {n_cpu-1})",
                       variable=self.use_all_cores).grid(
            row=row, column=0, columnspan=3, sticky=tk.W, pady=2)

        row += 1
        ttk.Label(params_frame, text="Размер чанка (млн точек):").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Spinbox(params_frame, from_=0.5, to=20, increment=0.5,
                    textvariable=self.chunk_size_m, width=15).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(params_frame, text="(больше = быстрее, но больше RAM)").grid(
            row=row, column=2, sticky=tk.W, padx=5, pady=2)

        row += 1
        ttk.Checkbutton(params_frame,
                       text="Удалить временные файлы после конвертации",
                       variable=self.cleanup_temp).grid(
            row=row, column=0, columnspan=3, sticky=tk.W, pady=2)

        row += 1
        ttk.Checkbutton(params_frame,
                       text="Открыть первый тайл после конвертации",
                       variable=self.open_first_tile_only).grid(
            row=row, column=0, columnspan=3, sticky=tk.W, pady=2)

        # === Buttons ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)
        self.convert_button = ttk.Button(btn_frame, text="Начать конвертацию",
                                        command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)
        self.cancel_button = ttk.Button(btn_frame, text="Отмена",
                                        command=self.cancel_conversion,
                                        state='disabled')
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Детальные логи",
                   command=self.log_window.toggle).pack(side=tk.LEFT, padx=5)

        # === Progress ===
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress,
                                            maximum=100, length=400)
        self.progress_bar.grid(row=6, column=0, columnspan=3, pady=5, sticky=(tk.W, tk.E))

        self.status_label = ttk.Label(main_frame, textvariable=self.status,
                                      font=("Arial", 9), wraplength=700)
        self.status_label.grid(row=7, column=0, columnspan=3, pady=5)

        self.main_log = tk.Text(main_frame, height=10, width=80,
                                state='disabled', wrap=tk.WORD)
        self.main_log.grid(row=8, column=0, columnspan=3, pady=10,
                           sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(8, weight=1)

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical",
                                  command=self.main_log.yview)
        scrollbar.grid(row=8, column=3, sticky=(tk.N, tk.S))
        self.main_log['yscrollcommand'] = scrollbar.set

        # === Info ===
        info_frame = ttk.LabelFrame(main_frame, text="v6 — Что нового", padding="5")
        info_frame.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        n_cpu = os.cpu_count() or 4
        info_text = (
            "✓ Chunked LAS read: 30+ GB без OOM\n"
            "✓ Per-tile out-of-core: RAM ограничена размером одного тайла\n"
            f"✓ ProcessPoolExecutor: {n_cpu} процессов в параллель (НЕ threading)\n"
            "✓ Batched EVD для нормалей: ~10× быстрее per-point SVD\n"
            "✓ Streaming GLB write: без N×9 промежуточного массива\n"
            "✓ Raster decimation: 2D-сетка по X,Y (вместо 3D вокселей)"
        )
        ttk.Label(info_frame, text=info_text, font=("Arial", 9),
                  justify=tk.LEFT).grid(row=0, column=0, sticky=tk.W)

        self.update_status("Готов к работе")

    # ----------------------------------------------------------------
    #  File dialogs
    # ----------------------------------------------------------------

    def select_input_file(self):
        path = filedialog.askopenfilename(
            title="Выберите LAS файл",
            filetypes=[("LAS files", "*.las *.laz"), ("All files", "*.*")])
        if path:
            self.input_file.set(path)
            if not self.output_dir.get():
                self.output_dir.set(os.path.splitext(path)[0] + '_tiles')
            self.update_status(f"Выбран: {os.path.basename(path)}")
            self.preview_las_info(path)

    def select_output_dir(self):
        path = filedialog.askdirectory(title="Выберите папку для тайлов")
        if path:
            self.output_dir.set(path)

    def preview_las_info(self, file_path):
        """Только заголовок — НЕ грузим весь файл в RAM."""
        try:
            self.log_window.clear_all()
            self.log_window.show()
            info = get_las_info(file_path)
            n = info['n_points']
            size_mb = os.path.getsize(file_path) / (1024 * 1024)

            lines = [
                "=" * 60,
                "ИНФОРМАЦИЯ О LAS ФАЙЛЕ",
                "=" * 60,
                f"Файл: {file_path}",
                f"Версия LAS: {info['version']}",
                f"Point format: {info['point_format']}",
                f"Количество точек: {n:,}",
                f"Размер файла: {size_mb:.1f} MB ({size_mb/1024:.2f} GB)",
                f"Цвет: {'да' if info['has_color'] else 'нет'}",
                "",
                f"Bounds:",
                f"  X: [{info['xmin']:.2f}, {info['xmax']:.2f}]  "
                f"(dx={info['xmax']-info['xmin']:.2f} м)",
                f"  Y: [{info['ymin']:.2f}, {info['ymax']:.2f}]  "
                f"(dy={info['ymax']-info['ymin']:.2f} м)",
            ]

            tw = self.tile_width.get()
            tl = self.tile_length.get()
            if tw > 0 and tl > 0:
                nx = int(np.ceil((info['xmax'] - info['xmin']) / tw))
                ny = int(np.ceil((info['ymax'] - info['ymin']) / tl))
                lines.append("")
                lines.append(f"Тайлинг {tw}×{tl} м:")
                lines.append(f"  Сетка: {nx} × {ny} = {nx*ny} участков")
                lines.append(f"  ~{n/max(1, nx*ny):,.0f} точек на тайл (в среднем)")

            lines.append("")
            lines.append("РЕКОМЕНДАЦИИ:")
            if n > 100_000_000:
                lines.append(f"  ⚠️  {n:,} точек — ОБЯЗАТЕЛЬНО тайлинг + ProcessPool!")
                self.use_tiling.set(True)
            elif n > 10_000_000:
                lines.append(f"  ⚠️  {n:,} точек — рекомендуется тайлинг")
                self.use_tiling.set(True)
            elif n > 1_000_000:
                lines.append(f"  ℹ️  {n:,} точек — желательна децимация")
            else:
                lines.append(f"  ✅  {n:,} точек — файл небольшой, должно быть быстро")

            for line in lines:
                self.log_window.log(line, "las")

            self.main_log_message("LAS проанализирован. См. 'Детальные логи'.")

        except Exception as e:
            self.log_window.log(f"Ошибка анализа: {e}", "las")
            self.main_log_message(f"Ошибка: {e}")

    # ----------------------------------------------------------------
    #  UI helpers
    # ----------------------------------------------------------------

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
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.run(["open", file_path], check=True)
            else:
                for viewer in [["xdg-open", file_path], ["gnome-open", file_path]]:
                    try:
                        subprocess.run(viewer, check=True)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
        except Exception as e:
            self.main_log_message(f"Не удалось открыть {file_path}: {e}")

    # ----------------------------------------------------------------
    #  Conversion lifecycle
    # ----------------------------------------------------------------

    def cancel_conversion(self):
        self._cancel_event.set()
        self.main_log_message("Отмена запрошена...")
        self.cancel_button.config(state='disabled')

    def start_conversion(self):
        if not self.input_file.get():
            messagebox.showerror("Ошибка", "Выберите входной LAS файл")
            return
        if not self.output_dir.get():
            messagebox.showerror("Ошибка", "Укажите выходную папку")
            return
        if self.use_tiling.get():
            if self.tile_width.get() <= 0 or self.tile_length.get() <= 0:
                messagebox.showerror("Ошибка", "Размеры тайла должны быть > 0")
                return

        self.log_window.clear_all()
        self.log_window.show()

        self.convert_button.config(state='disabled')
        self.cancel_button.config(state='normal')

        self._cancel_event.clear()
        # Manager().Queue() — прокси-объект, корректно пиклится через fork-границы
        # (mp.Queue() напрямую не работает с ProcessPoolExecutor на Linux)
        if self._manager is None:
            self._manager = mp.Manager()
            self._log_queue = self._manager.Queue()
        self.update_status("Запуск...")
        self.main_log.config(state='normal')
        self.main_log.delete(1.0, tk.END)
        self.main_log.config(state='disabled')
        self.progress.set(0)

        # Запускаем поллер логов (в главном Tk-потоке, через root.after)
        self._start_log_poller()

        # Собираем параметры
        n_workers = CPU_COUNT if self.use_all_cores.get() else max(1, CPU_COUNT - 1)
        params = {
            'las_path': self.input_file.get(),
            'output_dir': self.output_dir.get(),
            'use_tiling': self.use_tiling.get(),
            'tw': float(self.tile_width.get()),
            'tl': float(self.tile_length.get()),
            'overlap': float(self.tile_overlap.get()),
            'chunk_size': int(self.chunk_size_m.get() * 1_000_000),
            'n_workers': n_workers,
            'cleanup_temp': self.cleanup_temp.get(),
            'decimate_target': int(self.decimate_before.get()),
            'k_neighbors': int(self.k_neighbors.get()),
            'max_vertices': int(self.max_vertices.get()),
            'color_mode': self.color_mode.get(),
            'material_mode': self.material_mode.get(),
        }

        # Запускаем оркестратор в daemon-потоке
        self._worker_thread = threading.Thread(
            target=self._orchestrator_wrapper,
            args=(params,),
            daemon=True,
        )
        self._worker_thread.start()

    def _orchestrator_wrapper(self, params):
        """Обёртка: вызывает run_conversion с коллбэками, безопасными для Tk."""
        def progress_cb(value, msg):
            self.root.after(0, lambda: self.update_progress(value))
            if msg:
                self.root.after(0, lambda: self.update_status(msg))

        def status_cb(msg):
            self.root.after(0, lambda: self.update_status(msg))

        def all_done_cb(result):
            # Планируем финализацию в UI-потоке
            self.root.after(0, lambda: self._on_all_done(result))

        def error_cb(msg):
            self.root.after(0, lambda: self.show_error(msg))

        run_conversion(
            params, self._log_queue, self._cancel_event,
            progress_cb, status_cb, all_done_cb, error_cb,
        )

        # Сигнал поллеру остановиться
        self._log_queue.put(('__stop__', None))

    def _start_log_poller(self):
        """Поллинг mp.Queue в Tk-потоке через root.after."""
        def poll():
            if self._log_queue is None:
                return
            try:
                while True:
                    try:
                        item = self._log_queue.get_nowait()
                    except queue.Empty:
                        break
                    self._dispatch_log(item)
            except Exception as e:
                print(f"Log poller error: {e}", file=sys.stderr)
            self._poller_after_id = self.root.after(100, poll)
        self._poller_after_id = self.root.after(100, poll)

    def _dispatch_log(self, item):
        if not isinstance(item, tuple) or len(item) < 1:
            return
        msg_type = item[0]

        if msg_type == '__stop__':
            if self._poller_after_id:
                self.root.after_cancel(self._poller_after_id)
                self._poller_after_id = None
            return

        if len(item) < 2:
            return
        data = item[1]

        if msg_type == 'log_main':
            self.main_log_message(str(data))
        elif msg_type.startswith('log_'):
            tag = msg_type[4:] or 'general'
            self.log_window.log(str(data), tag)
        elif msg_type == 'error':
            self.log_window.log(str(data), 'general')
            self.main_log_message(f"❌ {str(data).splitlines()[0]}")
        elif msg_type == 'progress':
            # Старый формат: tuple из progress_cb — здесь не используется
            pass
        elif msg_type == 'tile_done':
            pass  # уже отправлено в log_main
        elif msg_type == 'all_done':
            pass  # обрабатывается через _on_all_done

    def _on_all_done(self, result):
        self.update_progress(100)
        self.update_status("Готово!")
        self.convert_button.config(state='normal')
        self.cancel_button.config(state='disabled')

        files = result.get('files', [])
        n_glb = result.get('n_files', 0)

        msg = (
            f"Конвертация завершена!\n\n"
            f"GLB файлов: {n_glb}\n"
            f"Исходных точек: {result.get('total_in_points', 0):,}\n"
            f"Всего вершин: {result.get('total_verts', 0):,}\n"
            f"Всего треугольников: {result.get('total_tris', 0):,}\n"
            f"Время: {result.get('time', 0):.1f} сек\n\n"
            f"Файлы:\n  " +
            "\n  ".join(os.path.basename(f) for f in files[:10]) +
            ("\n  ..." if len(files) > 10 else "")
        )
        self.show_success(msg)

        """
        if self.open_after_convert.get() and files:
            if self.open_first_tile_only.get():
                # Открываем первый GLB (пропускаем PNG карту)
                glb_files = [f for f in files if f.endswith('.glb')]
                if glb_files:
                    self.open_glb_file(glb_files[0])
            else:
                for f in files:
                    if f.endswith('.glb'):
                        self.open_glb_file(f)
        """


def main():
    if sys.platform == 'win32':
        # На Windows по умолчанию 'spawn' — корректно работает с ProcessPoolExecutor
        try:
            mp.set_start_method('spawn', force=False)
        except RuntimeError:
            pass  # уже установлен
    root = tk.Tk()
    app = LASConverterGUI(root)

    def on_closing():
        if app._worker_thread and app._worker_thread.is_alive():
            if messagebox.askyesno("Подтверждение", "Идёт конвертация. Отменить?"):
                app.cancel_conversion()
                root.after(2000, root.destroy)
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    # На Windows обязательно для multiprocessing в PyInstaller
    mp.freeze_support()
    main()
