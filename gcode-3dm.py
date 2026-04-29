import os
import re
import sys
import tkinter as tk
from tkinter import filedialog

import rhino3dm


def select_gcode_file():
    """Визуальный выбор G-code файла"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Выберите G-code файл",
        filetypes=[("G-code files", "*.gcode *.gco *.g *.nc"), ("All files", "*.*")],
    )
    return file_path


def parse_gcode_by_layers(gcode_path):
    """
    Парсит G-code и группирует точки по слоям (по Z).
    Возвращает: dict {z_height: [list_of_rhino3dm.Point3d]}
    """
    layers = {}  # z_key -> list of Point3d
    current_x = 0.0
    current_y = 0.0
    current_z = 0.0
    absolute_mode = True
    current_layer_points = []

    with open(gcode_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            # Режим координат G90 / G91
            if "G90" in line:
                absolute_mode = True
            elif "G91" in line:
                absolute_mode = False

            # Только G0 и G1
            if not re.match(r"G[01]\s", line):
                continue

            x_match = re.search(r"X([-\d.]+)", line)
            y_match = re.search(r"Y([-\d.]+)", line)
            z_match = re.search(r"Z([-\d.]+)", line)
            e_match = re.search(r"E([-\d.]+)", line)

            # Вычисляем координаты
            x = float(x_match.group(1)) if x_match else current_x
            y = float(y_match.group(1)) if y_match else current_y
            z = float(z_match.group(1)) if z_match else current_z

            if not absolute_mode:
                x = current_x + x if x_match else current_x
                y = current_y + y if y_match else current_y
                z = current_z + z if z_match else current_z

            # Проверяем наличие экструзии
            has_extrusion = False
            if e_match:
                e_value = float(e_match.group(1))
                if e_value > 0.0001:  # отсекаем ретракты
                    has_extrusion = True

            # При смене Z сохраняем предыдущий слой
            if z_match and abs(z - current_z) > 0.001 and current_layer_points:
                z_key = round(current_z, 4)
                if z_key not in layers:
                    layers[z_key] = []
                layers[z_key].extend(current_layer_points)
                current_layer_points = []

            # Добавляем точку, если есть экструзия
            if has_extrusion:
                current_layer_points.append(rhino3dm.Point3d(x, y, z))

            # Обновляем текущее положение
            current_x, current_y, current_z = x, y, z

    # Добавляем последний слой
    if current_layer_points:
        z_key = round(current_z, 4)
        if z_key not in layers:
            layers[z_key] = []
        layers[z_key].extend(current_layer_points)

    print(f"Найдено {len(layers)} слоёв с экструзией.")
    return layers


def main():
    print("=== G-code → rhino3dm (кривые по слоям) ===\n")

    gcode_file = select_gcode_file()
    if not gcode_file:
        print("Файл не выбран.")
        return

    print(f"Обработка файла: {gcode_file}")

    layers = parse_gcode_by_layers(gcode_file)

    if not layers:
        print("Не найдено движений с экструзией.")
        return

    # Создаём новый 3dm файл
    model = rhino3dm.File3dm()

    created_curves = 0
    created_tubes = 0

    for z_height in sorted(layers.keys()):
        points = layers[z_height]
        if len(points) < 2:
            continue

        # Создаём интерполированную кривую (как InterpCrv в Rhino)
        #
        curve = rhino3dm.Curve.CreateControlPointCurve(points, degree=3)
        # Mesh.CreateFromCurvePipe(curve, 3)
        # curve = rhino3dm.Curve.CreateInterpolatedCurve(points, degree=3)

        if curve:
            # Добавляем атрибуты (имя)
            attr = rhino3dm.ObjectAttributes()
            attr.Name = f"Layer_Z_{z_height:.4f}"

            model.Objects.Add(curve, attr)
            created_curves += 1
        else:
            print(f"Не удалось создать кривую для слоя Z = {z_height}")

    print(f"\nСоздано {created_curves} кривых.")
    # Сохранение файла
    default_name = os.path.splitext(os.path.basename(gcode_file))[0] + "_layers.3dm"

    root = tk.Tk()
    root.withdraw()
    save_path = filedialog.asksaveasfilename(
        title="Сохранить 3DM файл",
        defaultextension=".3dm",
        filetypes=[("Rhino 3D Model", "*.3dm")],
        initialfile=default_name,
    )

    if save_path:
        success = model.Write(save_path, version=8)  # версия 8 — рекомендуется
        if success:
            print(f"Файл успешно сохранён:\n{save_path}")
        else:
            print("Ошибка при сохранении файла.")
    else:
        print("Сохранение отменено.")


if __name__ == "__main__":
    main()
