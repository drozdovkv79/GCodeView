import numpy as np
import trimesh


def create_3d_house():
    """Создает 3D модель дома с помощью trimesh"""

    # Создаем основную коробку дома
    house_width = 14
    house_depth = 14.3
    house_height = 3

    base_box = trimesh.primitives.Box(extents=[house_width, house_depth, house_height])

    # Создаем крышу
    roof_height = 2
    roof = trimesh.primitives.Extrusion(
        polygon=[[-7, -7.15], [7, -7.15], [7, 7.15], [-7, 7.15]],
        height=roof_height,
        transform=trimesh.transformations.translation_matrix([0, 0, house_height]),
    )

    # Объединяем в одну модель
    house_model = trimesh.util.concatenate([base_box, roof])

    # Сохраняем модель
    house_model.export("house_200sqm.stl")
    print("3D модель дома сохранена как 'house_200sqm.stl'")

    # Отображаем
    house_model.show()


if __name__ == "__main__":
    create_3d_house()
