from tkinter import Tk, filedialog

import pyvista as pv
import trimesh


def open_viewer():
    # 1. Диалоговое окно выбора файла
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Выберите GLB модель",
        filetypes=[("GLB files", "*.glb"), ("All files", "*.*")],
    )
    root.destroy()

    if not file_path:
        return

    try:
        # Загружаем через trimesh
        tm_scene = trimesh.load(file_path)

        # Исправление Deprecation: используем to_geometry() вместо dump()
        if isinstance(tm_scene, trimesh.Scene):
            geometry = tm_scene.to_geometry()
            mesh = pv.wrap(geometry)
        else:
            mesh = pv.wrap(tm_scene)

        plotter = pv.Plotter(title=f"macOS 3D Viewer - {file_path.split('/')[-1]}")
        plotter.set_background("slategray")

        # Основной меш
        main_actor = plotter.add_mesh(
            mesh, color="tan", smooth_shading=True, label="Model"
        )

        # --- 1. СЕКУЩАЯ ПЛОСКОСТЬ ---
        plotter.add_mesh_clip_plane(mesh, color="orange", assign_to_axis="z")

        # --- 2. ПЕРЕКЛЮЧАТЕЛЬ WIREFRAME (Исправлено) ---
        def toggle_wireframe(flag):
            if flag:
                main_actor.prop.style = "wireframe"
            else:
                main_actor.prop.style = "surface"

        # В PyVista текст для чекбокса добавляется через add_text рядом с ним
        plotter.add_checkbox_button_widget(
            toggle_wireframe, value=False, color_on="yellow", position=(10, 70)
        )
        plotter.add_text("Wireframe", position=(50, 70), font_size=10, color="white")

        # --- 3. ГАБАРИТЫ И ТЕКСТ ---
        plotter.add_bounding_box(color="white")
        bounds = mesh.bounds
        size_info = f"Size: X:{bounds[1] - bounds[0]:.2f} Y:{bounds[3] - bounds[2]:.2f} Z:{bounds[5] - bounds[4]:.2f}"
        plotter.add_text(size_info, position="lower_left", font_size=10, color="white")

        # --- 4. ИЗМЕРЕНИЕ РАССТОЯНИЯ ---
        plotter.add_measurement_widget()

        plotter.add_axes()

        print("Управление на macOS:")
        print("- Нажмите 'm' для активации линейки")
        print("- Зажмите 'Ctrl' + ЛКМ для выбора точек измерения")

        plotter.show()

    except Exception as e:
        print(f"Произошла ошибка: {e}")


if __name__ == "__main__":
    open_viewer()
