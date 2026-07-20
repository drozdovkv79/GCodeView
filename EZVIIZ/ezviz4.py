import json
import platform
import subprocess

from pyezvizapi import EzvizClient

# --- КОНФИГУРАЦИЯ ---
# rtsp://admin:AMWQVB@192.168.1.68:554/ch1/main
EMAIL = "drozdovkv79@yandex.ru"
PASSWORD = "Luxor!2345"
REGION = "apiirus.ezvizru.com"
SERIAL = "BC3951666"  # Серийный номер камеры ("кухня")

# ВАЖНО: Введите код верификации с наклейки на камере (6 заглавных букв)
# Если меняли в приложении Ezviz, укажите свой.
VALIDATION_CODE = "AMWQVB"


def main():
    print("=== Подключение к камерам Ezviz ===\n")

    client = EzvizClient(EMAIL, PASSWORD, url=REGION)

    # 1. Авторизация
    try:
        print("Выполняю login...")
        client.login()
        print("✅ Логин выполнен успешно\n")
    except Exception as e:
        print(f"❌ Ошибка логина: {e}")
        return

    # 2. Чтение словаря устройств
    print("=== Список устройств ===")
    try:
        devices = client.load_devices()

        if not isinstance(devices, dict) or not devices:
            print("Устройства не найдены.")
            return

        for srl, dev in devices.items():
            name = dev.get("name", "Без имени")
            status = "🟢 Онлайн" if dev.get("status") == 1 else "🔴 Оффлайн"
            local_ip = dev.get("local_ip", "N/A")
            marker = " 👈 [ВЫБРАНА]" if srl == SERIAL else ""

            print(f"- {name} (SN: {srl}, IP: {local_ip}) - {status}{marker}")

    except Exception as e:
        print(f"❌ Ошибка получения устройств: {e}")
        return

    # 3. Формирование локальной RTSP ссылки
    if SERIAL not in devices:
        print(f"\n⚠️ Камера {SERIAL} не найдена!")
        return

    cam_info = devices[SERIAL]
    local_ip = cam_info.get("local_ip")

    if not local_ip or local_ip == "0.0.0.0":
        print(
            "❌ У камеры нет локального IP. Убедитесь, что она подключена к той же сети."
        )
        return

    if VALIDATION_CODE == "ABCDEF":
        print("\n⚠️ ВНИМАНИЕ: Вы используете код верификации по умолчанию (ABCDEF).")
        print(
            "Если вы не меняли его на наклейке камеры, замените VALIDATION_CODE в скрипте."
        )
        # return # Раскомментируйте, если хотите обязательно ввести свой код

    # Формируем ссылку по спецификации Ezviz
    rtsp_url = f"rtsp://admin:{VALIDATION_CODE}@{local_ip}:554/{SERIAL}"
    print(f"\n=== Локальная ссылка на поток ===")
    print(f"🔗 {rtsp_url}\n")

    # 4. Воспроизведение потока
    print("=== Воспроизведение видеопотока ===")
    print("Запускаю VLC Player...\n")

    vlc_command = "vlc"
    if platform.system() == "Windows":
        import os

        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        vlc_path_win = os.path.join(program_files, "VideoLAN", "VLC", "vlc.exe")
        if os.path.exists(vlc_path_win):
            vlc_command = f'"{vlc_path_win}"'

    try:
        subprocess.Popen(
            [
                vlc_command,
                "--intf",
                "dummy",
                rtsp_url,
                "--network-caching=300",
                f"--meta-title=Ezviz - {cam_info.get('name', SERIAL)}",
            ]
        )
        print(
            "✅ VLC запущен! Если видео не появилось, проверьте код верификации (VALIDATION_CODE)."
        )
    except FileNotFoundError:
        print("❌ VLC не найден. Установите его: https://www.videolan.org/vlc/")
        print(
            f"\nВы можете скопировать эту ссылку и открыть в VLC вручную:\n{rtsp_url}"
        )


if __name__ == "__main__":
    main()
