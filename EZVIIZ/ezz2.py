import asyncio
import json
import logging
import os
from datetime import datetime

from pyezvizapi import EzvizClient  # Исправленный импорт

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
CONFIG = {
    "username": "drozdovkv79@yandex.ru",  # Ваш email от EZVIZ
    "password": "Luxor!2345",  # Ваш пароль
    "camera_serial": "BC3951666",  # Серийный номер камеры (None = первая камера)
    "save_dir": "ezviz_images",  # Папка для сохранения
    "interval": 30.0,  # Интервал в секундах (30 сек)
    "token_file": "ezviz_token.json",  # Файл для сохранения токена
}


async def get_camera_image_async(
    client: EzvizClient, camera_serial: str
) -> bytes | None:
    """
    Асинхронно получает изображение с камеры через pyezvizapi.
    """
    try:
        # В pyezvizapi метод для получения изображения может называться async_get_image
        # или требовать вызова определённого API-метода
        image_data = await client.async_get_camera_image(camera_serial)

        if image_data:
            return image_data
        else:
            logger.warning("⚠️ Пустой ответ от камеры")
            return None

    except AttributeError:
        # Если метод не найден, пробуем альтернативный способ через API
        logger.info(
            "Метод async_get_camera_image не найден, используем прямой API-вызов..."
        )
        return await get_camera_image_via_api(client, camera_serial)
    except Exception as e:
        logger.error(f"❌ Ошибка получения изображения: {e}")
        return None


async def get_camera_image_via_api(
    client: EzvizClient, camera_serial: str
) -> bytes | None:
    """
    Альтернативный метод: прямой вызов EZVIZ API v3.
    """
    try:
        # Получаем данные сессии из клиента
        account = client._account  # EzvizAccount объект

        # Формируем URL для v3 API
        url = f"https://{account.api_url}/v3/users/{account.user_id}/devices/{camera_serial}/image"

        # Заголовки авторизации
        headers = {"Authorization": f"AccessToken {account.access_token}"}

        # Параметры: quality=1 (SD) для скорости
        params = {"quality": 1}

        # Асинхронный POST-запрос
        response = await client._session.post(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        if str(data.get("code")) == "200":
            pic_url = data["data"]["url"]
            logger.debug(f"URL изображения получен: {pic_url[:50]}...")

            # Асинхронное скачивание изображения
            img_response = await client._session.get(pic_url)
            img_response.raise_for_status()

            # Проверяем, что это JPEG
            if img_response.content[:2] == b"\xff\xd8":
                return img_response.content
            else:
                logger.warning("⚠️ Полученные данные не являются JPEG")
                return None
        else:
            error_msg = data.get("msg", "Неизвестная ошибка")
            logger.error(f"⚠️ Ошибка API: {error_msg}")
            return None

    except Exception as e:
        logger.error(f"❌ Ошибка прямого API-вызова: {e}")
        return None


async def save_images_periodically(config: dict):
    """
    Основная функция: сохраняет изображения каждые 30 секунд.
    """
    os.makedirs(config["save_dir"], exist_ok=True)

    # Инициализация клиента
    client = EzvizClient(config["username"], config["password"])

    try:
        # 1. Аутентификация с сохранением токена
        logger.info("🔄 Подключение к EZVIZ Cloud...")

        # Пытаемся загрузить сохранённый токен
        token_loaded = False
        if os.path.exists(config["token_file"]):
            try:
                with open(config["token_file"], "r") as f:
                    token_data = json.load(f)
                    client.load_token(token_data)
                    token_loaded = True
                    logger.info("✅ Загружен сохранённый токен")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить токен: {e}")

        # Если токен не загружен, логинимся
        if not token_loaded:
            await client.async_login()
            # Сохраняем токен для следующего запуска
            with open(config["token_file"], "w") as f:
                json.dump(client.get_token(), f, indent=2)
            logger.info("✅ Аутентификация успешна, токен сохранён")

        # 2. Получение списка камер
        logger.info("📷 Получение списка устройств...")
        devices = await client.async_get_device_list()

        if not devices:
            logger.error("❌ Устройства не найдены")
            return

        # Фильтруем только камеры
        cameras = [d for d in devices if d.get("deviceCategory") == "camera"]
        logger.info(f"📷 Найдено камер: {len(cameras)}")

        # 3. Выбор камеры
        camera_serial = config["camera_serial"]

        if camera_serial is None:
            # Автоматический выбор первой онлайн-камеры
            for cam in cameras:
                if cam.get("status") == 1:  # 1 = онлайн
                    camera_serial = cam.get("deviceSerial")
                    camera_name = cam.get("deviceName", "Unknown")
                    logger.info(
                        f"🔍 Автоматический выбор: {camera_name} ({camera_serial})"
                    )
                    break

            if not camera_serial:
                camera_serial = cameras[0].get("deviceSerial")
                logger.info(f"🔍 Выбрана первая камера: {camera_serial}")
        else:
            # Проверяем, что камера существует
            found = any(cam.get("deviceSerial") == camera_serial for cam in cameras)
            if not found:
                logger.error(f"❌ Камера {camera_serial} не найдена")
                return

        # 4. Основной цикл сохранения
        logger.info(f"🎯 Начинаем захват с камеры: {camera_serial}")
        logger.info(f"💾 Папка: {config['save_dir']}")
        logger.info(f"⏱️ Интервал: {config['interval']} сек.")
        logger.info("-" * 60)

        success_count = 0
        error_count = 0
        cycle_count = 0

        while True:
            cycle_count += 1
            cycle_start = datetime.now()

            try:
                # Асинхронное получение изображения
                image_data = await get_camera_image_async(client, camera_serial)

                if image_data:
                    # Генерация имени файла
                    timestamp = cycle_start.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config["save_dir"], f"ezviz_{timestamp}.jpg"
                    )

                    # Сохранение
                    with open(filename, "wb") as f:
                        f.write(image_data)

                    size_kb = len(image_data) // 1024
                    elapsed = (datetime.now() - cycle_start).total_seconds()
                    logger.info(
                        f"✅ [{cycle_count:04d}] {filename} | "
                        f"{size_kb} КБ | {elapsed:.1f} сек"
                    )
                    success_count += 1
                else:
                    logger.warning(
                        f"⚠️ [{cycle_count:04d}] Не удалось получить изображение"
                    )
                    error_count += 1

                # Статистика каждые 10 циклов
                if cycle_count % 10 == 0:
                    total = success_count + error_count
                    success_rate = (success_count / total * 100) if total > 0 else 0
                    logger.info(
                        f"📊 Статистика: {success_count}/{total} успешных "
                        f"({success_rate:.0f}%)"
                    )

            except Exception as e:
                logger.error(f"❌ [{cycle_count:04d}] Критическая ошибка: {e}")
                error_count += 1

            # Асинхронное ожидание до следующего цикла
            await asyncio.sleep(config["interval"])

    except KeyboardInterrupt:
        logger.info("\n⏹️ Остановка по запросу пользователя")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
    finally:
        # Сохраняем токен при выходе
        try:
            with open(config["token_file"], "w") as f:
                json.dump(client.get_token(), f, indent=2)
            logger.info("💾 Токен сохранён")
        except:
            pass

        logger.info("🔌 Сеанс завершён")


# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == "__main__":
    # Проверка конфигурации
    if CONFIG["username"] == "your_email@example.com":
        print("❌ ОШИБКА: Пожалуйста, укажите ваши данные в CONFIG!")
        print("Редактируйте словарь CONFIG в начале файла.")
        exit(1)

    # Запуск асинхронного цикла
    asyncio.run(save_images_periodically(CONFIG))
