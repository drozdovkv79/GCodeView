import os
import time
from datetime import datetime

import cv2

# --- НАСТРОЙКИ ---
# URL для подключения к RTSP-потоку камеры
# Формат: rtsp://логин:пароль@IP_камеры:порт/путь_к_потоку
# Логин для Ezviz почти всегда "admin" [citation:5].
# Пароль - это проверочный код, указанный на наклейке на камере.
# В некоторых камерах порт может быть 554, а путь к потоку /ch1/main или /h264_stream [citation:5].
# Примеры:
# rtsp://admin:проверочный_код@192.168.1.100:554/ch1/main
# rtsp://admin:проверочный_код@192.168.1.100/h264_stream
RTSP_URL = "rtsp://admin:AMWQVB@192.168.1.68:554/ch1/main"

# Путь к папке для сохранения снимков
SAVE_DIR = "captures"

# Интервал между снимками в секундах
CAPTURE_INTERVAL = 2
# ------------------

# Создаём папку для сохранения, если её нет
os.makedirs(SAVE_DIR, exist_ok=True)


def capture_frame():
    """Подключается к RTSP, читает один кадр и сохраняет его."""
    # Открываем видеопоток. Флаг cv2.CAP_FFMPEG может помочь с некоторыми RTSP-потоками
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print(f"[Ошибка] Не удалось подключиться к камере по URL: {RTSP_URL}")
        return

    # Устанавливаем небольшой таймаут для чтения кадра, чтобы скрипт не завис
    # Это не гарантирует работу со всеми камерами, но обычно помогает
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Пытаемся прочитать кадр
    ret, frame = cap.read()

    if ret:
        # Генерируем имя файла на основе текущего времени
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{timestamp}.jpg"
        filepath = os.path.join(SAVE_DIR, filename)

        # Сохраняем кадр в виде JPEG
        cv2.imwrite(filepath, frame)
        print(f"[Успех] Снимок сохранён: {filepath}")

    else:
        print(f"[Ошибка] Не удалось прочитать кадр из потока в {datetime.now()}")

    # Освобождаем ресурсы, связанные с видеопотоком
    cap.release()


def main():
    """Основной цикл программы."""
    print(
        f"Скрипт запущен. Снимки будут сохраняться каждые {CAPTURE_INTERVAL} секунд в папку '{SAVE_DIR}'."
    )
    print("Для остановки нажмите Ctrl+C.")

    while True:
        start_time = time.time()

        # Выполняем захват кадра
        capture_frame()

        # Вычисляем время, затраченное на захват, и ждём остаток интервала
        elapsed = time.time() - start_time
        wait_time = max(0, CAPTURE_INTERVAL - elapsed)

        # Если захват прошёл быстро, ждём до следующего цикла
        if wait_time > 0:
            time.sleep(wait_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nСкрипт остановлен пользователем.")
