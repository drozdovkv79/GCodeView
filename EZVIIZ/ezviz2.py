import sys

import requests
from pyezvizapi import EzvizClient
from pyezvizapi.stream import (
    VtmStreamClient,
    build_stream_info_request,
    decode_vtm_packet,
    decrypt_hikvision_ps_video,
    parse_stream_info_response,
)

EMAIL = "drozdovkv79@yandex.ru"
PASSWORD = "Luxor!2345"
REGION = "apiirus.ezvizru.com"
SERIAL = "BB1487147"
CHANNEL = 1  # Номер канала, обычно 1

# Данные из раздела VTM (можно взять из ответа client.load_devices() или camera.status())
VTM_DOMAIN = "vtmrus.ezvizru.com"
VTM_PORT = 10554  # Порт из вашего JSON: 10554


def main():
    # 1. Авторизация
    client = EzvizClient(EMAIL, PASSWORD, url=REGION)
    print("Выполняю login...")
    client.login()
    print("✅ Логин выполнен успешно")
    access_token = client._token
    print("Access token:", access_token)

    # Прямой запрос к открытому API Ezviz (не требует подписки для получения информации о статусе)
    url = "https://open.ezviz.com/api/lapp/device/info"
    params = {"accessToken": access_token, "deviceSerial": SERIAL}
    resp = requests.post(url, data=params)
    print(resp.json())

    # 2. Получаем vtdu_token для камеры
    # Метод может называться get_vtdu_token, get_device_token или аналогично.
    # Проверим наличие нужного метода.
    if hasattr(client, "get_vtdu_token"):
        vtdu_token = client.get_vtdu_token(SERIAL)
    elif hasattr(client, "get_device_token"):
        vtdu_token = client.get_device_token(SERIAL)
    else:
        # Если прямого метода нет, можно использовать camera.get_vtdu_token()
        # Но у нас нет объекта camera, создадим его
        from pyezvizapi import EzvizCamera

        camera = EzvizCamera(client, SERIAL)
        vtdu_token = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEqzR4o4/j2vzZ0mBmp2ym1CJkX3jzgqS8fIxQ1lDTcil7PE50SKxCXcevwE4NaJbUf5Sk9iyUDl+8/z2WbA4MYg=="

    if not vtdu_token:
        print("❌ Не удалось получить vtdu_token для камеры.")
        return
    print(f"🔑 vtdu_token: {vtdu_token[:20]}...")

    # 3. Формируем ysproto URL
    import time

    timestamp_ms = int(time.time() * 1000)
    # Параметры запроса, аналогичные тем, что использует официальное приложение
    params = {
        "dev": SERIAL,
        "chn": str(CHANNEL),
        "stream": "1",
        "cln": "9",  # client type: 9 для мобильного
        "isp": "0",
        "auth": "1",
        "ssn": vtdu_token,
        "vip": "0",
        "timestamp": str(timestamp_ms),
    }
    from urllib.parse import urlencode

    query = urlencode(params)
    stream_url = f"ysproto://{VTM_DOMAIN}:{VTM_PORT}/live?{query}"
    print(f"🌐 VTM URL: {stream_url}")

    # 4. Подключаемся через VtmStreamClient
    vtm_client = VtmStreamClient(stream_url, timeout=15)
    print("Соединяюсь с VTM сервером...")
    try:
        stream_info = vtm_client.start()  # выполняет обмен StreamInfoReq/Rsp
        print("\n=== StreamInfoResponse ===")
        print(f"result: {stream_info.result}")
        print(f"datakey: {stream_info.datakey}")
        print(f"streamhead: {stream_info.streamhead}")
        print(f"streamssn: {stream_info.streamssn}")
        print(f"vtmstreamkey: {stream_info.vtmstreamkey}")
        print(f"serverinfo: {stream_info.serverinfo}")
        print(f"streamurl: {stream_info.streamurl}")  # может быть URL для редиректа
        print(f"srvinfo: {stream_info.srvinfo}")
        print(f"aesmd5: {stream_info.aesmd5}")  # ключ шифрования
        print(f"udptransinfo: {stream_info.udptransinfo}")
        print(f"peerpbkey: {stream_info.peerpbkey}")
        print(f"srvipv6_addr: {stream_info.srvipv6_addr}")
        print("=" * 40)
        # ... после подключения vtm_client.connect()
        request = build_stream_info_request(
            stream_url, client_version="v3.6.3.20221124"
        )
        vtm_client.send_packet(request)
        packet = vtm_client.read_packet()
        print(f"Message code: {hex(packet.message_code)}")
        print(f"Raw body (first 200 bytes): {packet.body[:200]}")

        # Попробуем распарсить как protobuf (даже если ошибка)
        stream_info = parse_stream_info_response(packet.body)
        print(f"Result: {stream_info.result}")
        # Если в теле есть текст, он может быть в нераспознанных полях,
        # выведем все поля сырого protobuf для анализа:
        from pyezvizapi.stream import _read_proto_fields

        fields = _read_proto_fields(packet.body, "ErrorResponse")
        print("All protobuf fields:", fields)
    except Exception as e:
        print(f"❌ Ошибка VTM handshake: {e}")
        return
    print("✅ VTM соединение установлено")

    # 5. Получаем ключ шифрования (обычно поле aesmd5)
    aes_key = stream_info.aesmd5
    if aes_key:
        print(f"🔐 Ключ AES: {aes_key}")
    else:
        print("⚠️ Ключ шифрования не получен, возможно поток не зашифрован")

    # 6. Сохраняем поток в файл
    output_file = "ezviz_vtm_stream.ts"
    print(f"\nЗапись видео в {output_file} ... (нажмите Ctrl+C для остановки)")

    packet_count = 0
    try:
        with open(output_file, "wb") as f:
            for payload in vtm_client.iter_payloads():
                if aes_key:
                    payload = decrypt_hikvision_ps_video(payload, aes_key)
                f.write(payload)
                packet_count += 1
                if packet_count % 100 == 0:
                    print(f"📦 Пакетов: {packet_count}, байт: {f.tell()}")
    except KeyboardInterrupt:
        print("\n⏹️ Остановка пользователем")
    finally:
        # Останавливаем трансляцию (если поддерживается)
        try:
            vtm_client.close()
        except:
            pass
        print(f"\n✅ Видео сохранено в {output_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
