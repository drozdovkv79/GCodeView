import math
import random
import re
import sys

# ============================================
# ВЫБЕРИТЕ ОДНУ ИЗ 5 ФУНКЦИЙ НИЖЕ
# ============================================


def surface_function(x, y, params):
    """
    Возвращает смещение по оси Z (или Y для вашего случая)
    x, y - текущие координаты
    params - словарь с параметрами эффекта
    """
    return water_ripples(x, y, params)


# ============================================
# ОСНОВНОЙ СКРИПТ (НЕ МЕНЯТЬ)
# ============================================


def apply_surface_to_gcode(input_file, output_file, effect_func, params):
    print(f"Обработка: {input_file}")
    print(f"Эффект: {params.get('name', 'Custom')}")

    with open(input_file, "r") as infile, open(output_file, "w") as outfile:
        modified = 0
        for line in infile:
            if re.match(r"^G[01]\s", line):
                # Парсим координаты
                x_match = re.search(r"X([+-]?\d*\.?\d+)", line)
                y_match = re.search(r"Y([+-]?\d*\.?\d+)", line)
                z_match = re.search(r"Z([+-]?\d*\.?\d+)", line)
                e_match = re.search(r"E([+-]?\d*\.?\d+)", line)
                f_match = re.search(r"F(\d+)", line)

                new_parts = ["G1"]
                x = float(x_match.group(1)) if x_match else None
                y = float(y_match.group(1)) if y_match else None

                if x is not None:
                    new_parts.append(f"X{x:.4f}")
                if y is not None:
                    # Применяем математическую функцию
                    if x is not None:
                        offset = effect_func(x, y if y is not None else 0, params)
                        new_parts.append(f"Y{y + offset:.4f}")
                    else:
                        new_parts.append(f"Y{y:.4f}")
                if z_match:
                    new_parts.append(f"Z{float(z_match.group(1)):.4f}")
                if e_match:
                    new_parts.append(f"E{float(e_match.group(1)):.4f}")
                if f_match:
                    new_parts.append(f"F{f_match.group(1)}")

                outfile.write(" ".join(new_parts) + "\n")
                modified += 1
            else:
                outfile.write(line)

    print(f"Готово! Изменено строк: {modified}")
    print(f"Сохранено: {output_file}\n")


# ============================================
# 5 ВАРИАНТОВ МАТЕМАТИЧЕСКИХ ПОВЕРХНОСТЕЙ
# ============================================


# 1. ЗВУКОВАЯ ВОЛНА (Сумма синусов с затуханием)
def sound_wave(x, y, params):
    """
    Имитация осциллограммы звука.
    Затухающие колебания + высокочастотное мерцание
    """
    A = params.get("amplitude", 5.0)  # Основная амплитуда
    freq = params.get("frequency", 0.15)  # Частота основной волны

    # Затухающая синусоида
    main_wave = A * math.sin(freq * x) * math.exp(-abs(x) / 500)
    # Высокочастотный "шум" (мерцание звука)
    high_freq = 1.5 * math.sin(1.5 * x) * math.cos(0.8 * y)
    # Огибающая
    envelope = 2 * math.sin(x / 200) ** 2

    return main_wave + high_freq + envelope


# 2. ВОЛНЫ НА ВОДЕ (2D рябь + круги)
def water_ripples(x, y, params):
    """
    Круги на воде с несколькими источниками.
    Классическая интерференция волн.
    """
    A = params.get("amplitude", 4.0)
    # Центры "брошенных камней"
    centers = [(0, 0), (200, 150), (-150, 100), (100, -100)]

    total = 0
    for cx, cy in centers:
        r = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        wave = math.sin(r / params.get("wavelength", 40)) * math.exp(-r / 300)
        total += wave

    return A * total / len(centers)


# 3. ПУСТЫННЫЕ БАРХАНЫ (Асимметричные дюны)
def sand_dunes(x, y, params):
    """
    Асимметричные песчаные дюны с крутым склоном.
    Формула: комбинация арктангенсов и синусов.
    """
    A = params.get("amplitude", 7.0)
    spacing = params.get("spacing", 60)

    # Главный гребень дюны
    main_dune = A * (math.sin(x / spacing) + 0.3 * math.sin(3 * x / spacing))
    # Асимметрия через arctan (крутой склон)
    asymmetry = A * 0.5 * (2 / math.pi) * math.atan(5 * math.sin(x / spacing))
    # Мелкая рябь от ветра
    ripples = 1.5 * math.sin(x / 12) * math.sin(y / 20)

    return main_dune + asymmetry + ripples


# 4. ТЕХНО-ГЛИТЧ (Хаотичные разрывы + тренд)
def glitch_effect(x, y, params):
    """
    Эффект цифрового глитча: ступеньки, скачки, хаос.
    """
    A = params.get("amplitude", 8.0)
    glitch_density = params.get("density", 0.03)  # Частота глитчей

    # Рваная ступенька
    step = A * math.floor(math.sin(x / 50) * 3) / 3

    # Случайные скачки (детерминированный псевдо-рандом)
    seed = int(abs(x / 15)) % 10
    glitch = 0
    if seed > 7:  # Внезапные сбои
        glitch = A * 0.6 * math.sin(x * 0.5) * (seed - 7)

    # Низкочастотный дрейф
    drift = 2 * math.sin(x / 180)

    return step + glitch + drift


# 5. ЖИДКИЙ МЕТАЛЛ / МЕРКУРИЙ (Сложная интерференция)
def liquid_mercury(x, y, params):
    """
    Текучая, меняющаяся поверхность.
    Комбинация радиальных и линейных волн.
    """
    A = params.get("amplitude", 6.0)

    # Радиальные волны от воображаемых источников
    radial = 0
    for angle in [0, math.pi / 3, 2 * math.pi / 3, math.pi]:
        nx = x * math.cos(angle) - y * math.sin(angle)
        ny = x * math.sin(angle) + y * math.cos(angle)
        r = math.sqrt(nx**2 + ny**2) / 45
        radial += math.sin(r) / (1 + r * 0.3)

    # Перекрестные волны
    cross = 0.5 * math.sin(x / 25) * math.sin(y / 25)
    cross += 0.3 * math.sin(x / 12) * math.cos(y / 18)

    # Нелинейное смешение фаз
    nonlinear = 1.2 * math.sin((x * y) / 2000)

    return A * (radial / 4 + cross + nonlinear)


# ============================================
# ПРИМЕРЫ ЗАПУСКА (раскомментируйте нужный)
# ============================================

if __name__ == "__main__":
    input_file = "/Users/drozdovkv/platefull.gcode"

    # === ВАРИАНТ 1: Звуковая волна ===
    # apply_surface_to_gcode(
    #     input_file,
    #     "/Users/drozdovkv/sound_wave.gcode",
    #     sound_wave,
    #     {"name": "Sound Wave", "amplitude": 5.0, "frequency": 0.15},
    # )

    # === ВАРИАНТ 2: Круги на воде ===
    # apply_surface_to_gcode(
    #    input_file,
    #    "/Users/drozdovkv/water_ripples.gcode",
    #    water_ripples,
    #     {"name": "Water Ripples", "amplitude": 4.0, "wavelength": 45},
    # )

    # === ВАРИАНТ 3: Пустынные барханы ===
    # apply_surface_to_gcode(
    #    input_file,
    #     "/Users/drozdovkv/sand_dunes.gcode",
    #     sand_dunes,
    #     {"name": "Sand Dunes", "amplitude": 7.0, "spacing": 55},
    # )

    # === ВАРИАНТ 4: Техно-глитч ===
    apply_surface_to_gcode(
        input_file,
        "/Users/drozdovkv/glitch_effect.gcode",
        glitch_effect,
        {"name": "Glitch", "amplitude": 8.0, "density": 0.03},
    )

    # === ВАРИАНТ 5: Жидкий металл ===
    # apply_surface_to_gcode(
    #     input_file,
    #     "liquid_mercury.gcode",
    #     liquid_mercury,
    #     {"name": "Liquid Mercury", "amplitude": 6.0},
    # )
