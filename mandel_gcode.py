import math
import sys

# ==========================================
# НАСТРОЙКИ МОДЕЛИ
# ==========================================
PANEL_LENGTH = 50.0
PANEL_WIDTH = 5.0
PANEL_HEIGHT = 50.0

FRACTAL_SIDE = "FRONT"  # "FRONT", "BACK", "LEFT", "RIGHT"
FRACTAL_DEPTH = 3.0

FRACTAL_SCALE = 100.0
FRACTAL_ROTATION_DEG = 0.0
FRACTAL_ORIENTATION = "NORMAL"

# ==========================================
# НАСТРОЙКИ ПЕЧАТИ (Используются только для G-code)
# ==========================================
LAYER_HEIGHT = 0.2
EXTRUSION_WIDTH = 0.4
FILAMENT_DIA = 1.75
NOZZLE_TEMP = 235.0
BED_TEMP = 80.0
PRINT_SPEED = 2400
TRAVEL_SPEED = 6000
Z_SPEED = 600
RETRACT_DIST = 0.8
RETRACT_SPEED = 1800

# ==========================================
# СЛУЖЕБНЫЕ ПЕРЕМЕННЫЕ
# ==========================================
FRACTAL_SIDE = FRACTAL_SIDE.upper()
FRACTAL_ORIENTATION = FRACTAL_ORIENTATION.upper()
COS_ROT = math.cos(math.radians(FRACTAL_ROTATION_DEG))
SIN_ROT = math.sin(math.radians(FRACTAL_ROTATION_DEG))

if FRACTAL_DEPTH >= PANEL_WIDTH:
    print(f"ОШИБКА: Глубина фрактала должна быть меньше ширины панели!")
    sys.exit(1)

# Геометрия
if FRACTAL_SIDE in ["FRONT", "BACK"]:
    FACE_LENGTH = PANEL_LENGTH
    DEPTH_AXIS = "Y"
    BASE_THICKNESS = PANEL_WIDTH - FRACTAL_DEPTH
else:
    FACE_LENGTH = PANEL_WIDTH
    DEPTH_AXIS = "X"
    BASE_THICKNESS = PANEL_LENGTH - FRACTAL_DEPTH

STEPS_Z = int(PANEL_HEIGHT / LAYER_HEIGHT)
STEPS_HORIZ = int(FACE_LENGTH / EXTRUSION_WIDTH)

# ==========================================
# ЯДРО: РАСЧЕТ МАТРИЦЫ ВЫСОТ (HEIGHTMAP)
# ==========================================
def _mandelbrot_single(c_real, c_imag, max_iter=50):
    z_r, z_i = 0.0, 0.0
    for i in range(max_iter):
        z_r_sq = z_r * z_r
        z_i_sq = z_i * z_i
        if z_r_sq + z_i_sq > 4.0: return i / max_iter
        z_i = 2.0 * z_r * z_i + c_imag
        z_r = z_r_sq - z_i_sq + c_real
    return 1.0

def calculate_heightmap():
    """Предрасчет всей панели в двумерный массив для быстрого экспорта"""
    print("Вычисление матрицы фрактала (суперсэмплинг 4x)...")
    scale = FRACTAL_SCALE / 100.0
    margin = (1.0 - scale) / 2.0
    heightmap = []

    for z_step in range(STEPS_Z):
        row = []
        z = (z_step + 0.5) * LAYER_HEIGHT # Центр слоя
        for h_step in range(STEPS_HORIZ):
            h_pos = (h_step + 0.5) * EXTRUSION_WIDTH # Центр линии

            u_coord = h_pos if FRACTAL_SIDE in ["FRONT", "LEFT"] else (FACE_LENGTH - h_pos)

            # Суперсэмплинг
            offsets = [(-0.1, -0.05), (0.1, -0.05), (-0.1, 0.05), (0.1, 0.05)]
            total_ratio = 0.0
            valid_samples = 0

            for du, dv in offsets:
                u_norm = (u_coord + du) / FACE_LENGTH
                v_norm = (z + dv) / PANEL_HEIGHT

                if FRACTAL_ORIENTATION == "MIRROR_X": u_norm = 1.0 - u_norm
                elif FRACTAL_ORIENTATION == "MIRROR_Y": v_norm = 1.0 - v_norm
                elif FRACTAL_ORIENTATION == "ROTATE_180": u_norm, v_norm = 1.0 - u_norm, 1.0 - v_norm

                if not (margin <= u_norm <= margin + scale and margin <= v_norm <= margin + scale): continue

                u_frac = (u_norm - margin) / scale - 0.5
                v_frac = (v_norm - margin) / scale - 0.5

                u_rot = u_frac * COS_ROT - v_frac * SIN_ROT + 0.5
                v_rot = u_frac * SIN_ROT + v_frac * COS_ROT + 0.5

                if not (0.0 <= u_rot <= 1.0 and 0.0 <= v_rot <= 1.0): continue
                valid_samples += 1
                total_ratio += _mandelbrot_single(-2.0 + u_rot * 2.5, -1.25 + v_rot * 2.5)

            ratio = total_ratio / valid_samples if valid_samples > 0 else 0.0
            row.append(ratio)
        heightmap.append(row)
    return heightmap

# ==========================================
# ЭКСПОРТ В STL
# ==========================================
def export_stl(heightmap, filename):
    print(f"Генерация STL полигональной сетки...")
    stl_lines = ["solid fractal_panel"]

    def add_facet(p1, p2, p3):
        # Вычисление вектора нормали для правильного отображения
        u = [p2[i] - p1[i] for i in range(3)]
        v = [p3[i] - p1[i] for i in range(3)]
        n = [u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0]]
        length = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
        if length > 0: n = [x/length for x in n]

        stl_lines.append(f"facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
        stl_lines.append("  outer loop")
        stl_lines.append(f"    vertex {p1[0]:.4f} {p1[1]:.4f} {p1[2]:.4f}")
        stl_lines.append(f"    vertex {p2[0]:.4f} {p2[1]:.4f} {p2[2]:.4f}")
        stl_lines.append(f"    vertex {p3[0]:.4f} {p3[1]:.4f} {p3[2]:.4f}")
        stl_lines.append("  endloop")
        stl_lines.append("endfacet")

    # Генерация вершин (X, Y, Z)
    vertices_front = []
    for z_i in range(STEPS_Z + 1):
        row = []
        for x_i in range(STEPS_HORIZ + 1):
            x = x_i * EXTRUSION_WIDTH
            z = z_i * LAYER_HEIGHT

            # Значение высоты (зажимаем индексы, чтобы не выйти за массив)
            safe_xi = min(x_i, STEPS_HORIZ - 1)
            safe_zi = min(z_i, STEPS_Z - 1)
            ratio = heightmap[safe_zi][safe_xi]

            depth = BASE_THICKNESS + (ratio * FRACTAL_DEPTH)

            if DEPTH_AXIS == "Y":
                row.append((x, depth, z))
            else:
                row.append((depth, x, z))
        vertices_front.append(row)

    # Задняя стенка (плоская)
    vertices_back = []
    for z_i in range(STEPS_Z + 1):
        row = []
        for x_i in range(STEPS_HORIZ + 1):
            x = x_i * EXTRUSION_WIDTH
            z = z_i * LAYER_HEIGHT
            if DEPTH_AXIS == "Y":
                row.append((x, 0.0, z))
            else:
                row.append((0.0, x, z))
        vertices_back.append(row)

    # 1. Лицевая сторона (Фрактал)
    for z_i in range(STEPS_Z):
        for x_i in range(STEPS_HORIZ):
            p1 = vertices_front[z_i][x_i]
            p2 = vertices_front[z_i][x_i+1]
            p3 = vertices_front[z_i+1][x_i+1]
            p4 = vertices_front[z_i+1][x_i]
            add_facet(p1, p2, p3)
            add_facet(p1, p3, p4)

    # 2. Задняя стенка
    for z_i in range(STEPS_Z):
        for x_i in range(STEPS_HORIZ):
            p1 = vertices_back[z_i][x_i]
            p2 = vertices_back[z_i][x_i+1]
            p3 = vertices_back[z_i+1][x_i+1]
            p4 = vertices_back[z_i+1][x_i]
            add_facet(p1, p3, p2) # Реверс нормали
            add_facet(p1, p4, p3)

    # 3, 4, 5, 6. Боковые стенки (замыкание объема)
    edges = [
        (lambda r: r[0], lambda r: r[0]), # Левая (x=0)
        (lambda r: r[-1], lambda r: r[-1]), # Правая (x=max)
        (vertices_front[0], vertices_back[0]), # Низ (z=0)
        (vertices_front[-1], vertices_back[-1]) # Верх (z=max)
    ]

    # Лево и Право
    for get_f, get_b in edges[:2]:
        for z_i in range(STEPS_Z):
            f1, f2 = get_f(vertices_front[z_i]), get_f(vertices_front[z_i+1])
            b1, b2 = get_b(vertices_back[z_i]), get_b(vertices_back[z_i+1])
            add_facet(f1, b1, f2)
            add_facet(f2, b1, b2)

    # Низ и Верх
    for f_row, b_row in edges[2:]:
        for x_i in range(STEPS_HORIZ):
            f1, f2 = f_row[x_i], f_row[x_i+1]
            b1, b2 = b_row[x_i], b_row[x_i+1]
            add_facet(f1, f2, b1)
            add_facet(f2, b2, b1)

    stl_lines.append("endsolid fractal_panel")

    with open(filename, "w") as f:
        f.write("\n".join(stl_lines))
    print(f"STL успешно сохранен: {filename}")

# ==========================================
# ЭКСПОРТ В G-CODE
# ==========================================
def export_gcode(heightmap, filename):
    filament_area = math.pi * (FILAMENT_DIA / 2) ** 2
    def calc_e(length): return (length * EXTRUSION_WIDTH * LAYER_HEIGHT) / filament_area

    gcode = []
    total_e = 0.0

    gcode.append("; --- Start G-code QIDI Q2 ---")
    gcode.append("M140 S{:.0f}".format(BED_TEMP))
    gcode.append("M104 S{:.0f}".format(NOZZLE_TEMP))
    gcode.append("G28")
    gcode.append("M109 S{:.0f}".format(NOZZLE_TEMP))
    gcode.append("M190 S{:.0f}".format(BED_TEMP))
    gcode.append("G92 E0")
    gcode.append("G1 Z2.0 F300")
    gcode.append("G1 X-10 Y10 Z0.3 F{}".format(TRAVEL_SPEED))
    gcode.append("G1 X80 Y10 Z0.3 E5.0 F{}".format(PRINT_SPEED))
    gcode.append("G92 E0")
    total_e = 0.0

    # Brim
    for b in range(3):
        e_brim = calc_e(PANEL_LENGTH)
        total_e += e_brim
        if DEPTH_AXIS == "Y":
            y_b = -b * EXTRUSION_WIDTH
            gcode.append("G1 X0 Y{:.2f} Z0.2 F{}".format(y_b, TRAVEL_SPEED))
            gcode.append("G1 X{:.2f} Y{:.2f} E{:.4f} F{}".format(PANEL_LENGTH, y_b, total_e, PRINT_SPEED))
            gcode.append("G1 E{:.4f} F{}".format(total_e - RETRACT_DIST, RETRACT_SPEED))
            total_e -= RETRACT_DIST
            gcode.append("G1 X{:.2f} Y{:.2f} F{}".format(PANEL_LENGTH, y_b - EXTRUSION_WIDTH, TRAVEL_SPEED))
            total_e += RETRACT_DIST
            gcode.append("G1 E{:.4f} F{}".format(total_e, RETRACT_SPEED))
        else:
            x_b = -b * EXTRUSION_WIDTH
            gcode.append("G1 X{:.2f} Y0 Z0.2 F{}".format(x_b, TRAVEL_SPEED))
            gcode.append("G1 X{:.2f} Y{:.2f} E{:.4f} F{}".format(x_b, PANEL_WIDTH, total_e, PRINT_SPEED))
            gcode.append("G1 E{:.4f} F{}".format(total_e - RETRACT_DIST, RETRACT_SPEED))
            total_e -= RETRACT_DIST
            gcode.append("G1 X{:.2f} Y{:.2f} F{}".format(x_b - EXTRUSION_WIDTH, PANEL_WIDTH, TRAVEL_SPEED))
            total_e += RETRACT_DIST
            gcode.append("G1 E{:.4f} F{}".format(total_e, RETRACT_SPEED))

    gcode.append("M106 S128")

    for z_step in range(STEPS_Z):
        z = (z_step + 1) * LAYER_HEIGHT
        gcode.append("G1 Z{:.2f} F{}".format(z, Z_SPEED))
        current_depth_offset = 0.0

        for h_step in range(STEPS_HORIZ):
            h_pos = h_step * EXTRUSION_WIDTH
            ratio = heightmap[z_step][h_step]

            raw_depth = BASE_THICKNESS + (ratio * FRACTAL_DEPTH)
            safe_depth = round(raw_depth / LAYER_HEIGHT) * LAYER_HEIGHT
            safe_depth = max(BASE_THICKNESS, min(safe_depth, BASE_THICKNESS + FRACTAL_DEPTH))

            if DEPTH_AXIS == "Y": x_cur, y_cur = h_pos, safe_depth
            else: x_cur, y_cur = safe_depth, h_pos

            if h_step == 0:
                gcode.append("G1 X{:.2f} Y{:.2f} F{}".format(x_cur, y_cur, TRAVEL_SPEED))
                current_depth_offset = safe_depth
            else:
                total_e += calc_e(EXTRUSION_WIDTH)
                gcode.append("G1 X{:.2f} Y{:.2f} E{:.4f} F{}".format(x_cur, y_cur, total_e, PRINT_SPEED))

                if safe_depth != current_depth_offset:
                    total_e -= RETRACT_DIST
                    gcode.append("G1 E{:.4f} F{}".format(total_e, RETRACT_SPEED))
                    axis_cmd = "Y" if DEPTH_AXIS == "Y" else "X"
                    gcode.append("G1 {}{:.2f} F{}".format(axis_cmd, safe_depth, TRAVEL_SPEED))
                    total_e += RETRACT_DIST
                    gcode.append("G1 E{:.4f} F{}".format(total_e, RETRACT_SPEED))
                    current_depth_offset = safe_depth

        total_e -= RETRACT_DIST
        gcode.append("G1 E{:.4f} F{}".format(total_e, RETRACT_SPEED))
        total_e += RETRACT_DIST

    gcode.append("\nM106 S0\nG91\nG1 Z10 F600\nG90\nG1 X0 Y200 F{}".format(TRAVEL_SPEED))
    gcode.append("M104 S0\nM140 S0\nM84\nM400")

    with open(filename, "w") as f:
        f.write("\n".join(gcode))
    print(f"G-code успешно сохранен: {filename}")

# ==========================================
# ГЛАВНОЕ МЕНЮ
# ==========================================
if __name__ == "__main__":
    print(f"Панель: {PANEL_LENGTH}x{PANEL_WIDTH}x{PANEL_HEIGHT}мм | Сторона: {FRACTAL_SIDE}")
    print(f"Масштаб: {FRACTAL_SCALE}% | Поворот: {FRACTAL_ROTATION_DEG}°\n")

    # 1. Считаем матрицу
    hmap = calculate_heightmap()

    # 2. Спрашиваем формат
    print("\nВыберите формат экспорта:")
    print("1. STL (3D модель, открыть в QIDI Studio/Cura)")
    print("2. GCODE (Готовый код для принтера)")
    print("3. ОБА ФОРМАТА")

    choice = input("Введите 1, 2 или 3: ").strip()

    if choice == "1":
        export_stl(hmap, f"Fractal_{FRACTAL_SIDE}.stl")
    elif choice == "2":
        export_gcode(hmap, f"Fractal_{FRACTAL_SIDE}.gcode")
    elif choice == "3":
        export_stl(hmap, f"Fractal_{FRACTAL_SIDE}.stl")
        export_gcode(hmap, f"Fractal_{FRACTAL_SIDE}.gcode")
    else:
        print("Неверный ввод.")
