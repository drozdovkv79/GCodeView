import re
import sys

import numpy as np
from vedo import Lines, Plotter, Tube


def parse_gcode_vedo(file_path):
    points = []
    current_pos = [0.0, 0.0, 0.0]
    mode = "absolute"

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.split(";")[0].strip()
            if not line:
                continue
            cmd_match = re.match(r"G(\d+)", line, re.IGNORECASE)
            if not cmd_match:
                continue
            g = int(cmd_match.group(1))

            if g == 90:
                mode = "absolute"
                continue
            if g == 91:
                mode = "relative"
                continue
            if g not in (0, 1):
                continue

            params = {}
            for ax in "XYZEF":
                m = re.search(rf"{ax}([-\d.]+)", line, re.IGNORECASE)
                if m:
                    params[ax] = float(m.group(1))

            if mode == "absolute":
                new_pos = [
                    params.get("X", current_pos[0]),
                    params.get("Y", current_pos[1]),
                    params.get("Z", current_pos[2]),
                ]
            else:
                new_pos = [
                    current_pos[0] + params.get("X", 0),
                    current_pos[1] + params.get("Y", 0),
                    current_pos[2] + params.get("Z", 0),
                ]

            is_print = g == 1 and params.get("E", 0) > 0.01

            if (
                is_print
                and np.linalg.norm(np.array(new_pos) - np.array(current_pos)) > 0.1
            ):
                points.append(new_pos)

            current_pos = new_pos

    return np.array(points)


# ====================== ЗАПУСК ======================
if len(sys.argv) < 2:
    print("Использование: python gcode_vedo.py файл.gcode")
    sys.exit(1)

points = parse_gcode_vedo(sys.argv[1])
print(f"Загружено {len(points)} точек")

plt = Plotter(bg="white", axes=1)

# Один Tube — очень быстро!
f_radius = float(sys.argv[2]) / 2
f_res = int(sys.argv[3])
tube = Tube(points, r=f_radius, c="#f5e8c7", alpha=1.0, res=f_res)

plt.add(tube)
plt.show("G-code модель — vedo", viewup="z", interactive=True)
