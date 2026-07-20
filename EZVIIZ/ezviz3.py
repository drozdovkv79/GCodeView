import json
import socket
import struct
import subprocess
import sys
import time

from pyezvizapi import EzvizClient

# --- КОНФИГУРАЦИЯ ---
EMAIL = "drozdovkv79@yandex.ru"
PASSWORD = "Luxor!2345"
REGION = "apiirus.ezvizru.com"
SERIAL = "BB1487147"  # Удаленная камера

# ВАЖНО: Код верификации с наклейки камеры! Он используется как AES-ключ для VTM.
VALIDATION_CODE = "ISDQRA"

# =====================================================================
# ЧАСТЬ 1: Вспомогательные функции VTM из вашего файла (упрощенные)
# =====================================================================

VTM_MAGIC = 0x24
VTM_HEADER_SIZE = 8


class VtmChannel:
    MESSAGE = 0x00
    STREAM = 0x01


class VtmMessageCode:
    KEEPALIVE_REQ = 0x132
    KEEPALIVE_RSP = 0x133
    STREAMINFO_REQ = 0x13B
    STREAMINFO_RSP = 0x13C


def encode_vtm_packet(body, channel, message_code, sequence):
    header = bytes(
        [
            VTM_MAGIC,
            int(channel) & 0xFF,
            *len(body).to_bytes(2, "big"),
            *(sequence & 0xFFFF).to_bytes(2, "big"),
            *int(message_code).to_bytes(2, "big"),
        ]
    )
    return header + body


def recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_vtm_packet(sock):
    header = recv_exact(sock, VTM_HEADER_SIZE)
    if header[0] != VTM_MAGIC:
        raise ValueError("Not a VTM packet")
    length = int.from_bytes(header[2:4], "big")
    channel = header[1]
    sequence = int.from_bytes(header[4:6], "big")
    message_code = int.from_bytes(header[6:8], "big")
    body = recv_exact(sock, length) if length else b""
    return channel, sequence, message_code, body


# =====================================================================
# ЧАСТЬ 2: Заглушки для Protobuf (чтобы не тянуть тяжелую зависимость)
# =====================================================================


def build_stream_info_request(stream_url, client_version="v3.6.3.20221124"):
    # Минимальная эмуляция protobuf строк: тег (1<<3|2) = 0x0A, длина, данные
    def proto_string(field_num, data):
        tag = (field_num << 3) | 2
        return bytes([tag, len(data)]) + data.encode()

    return (
        proto_string(1, stream_url)
        + proto_string(3, client_version)
        + bytes([0x20, 0x00])  # varint 4 = 0
        + proto_string(6, client_version)
    )


def parse_stream_info_response(body):
    # Очень грубый парсер protobuf для вытаскивания строк и ключа
    # Ищем паттерн: тег строки (0x1A для поля 3, 0x22 для поля 4 и т.д.)
    result = {}
    i = 0
    while i < len(body):
        if (body[i] & 0x07) == 2:  # Это строка
            field_num = body[i] >> 3
            length = body[i + 1]
            data = body[i + 2 : i + 2 + length].decode("utf-8", errors="ignore")
            if field_num == 3:
                result["streamhead"] = data
            if field_num == 4:
                result["streamssn"] = data
            if field_num == 5:
                result["vtmstreamkey"] = data
            if field_num == 7:
                result["streamurl"] = data
            i += 2 + length
        else:
            i += 1
    return result


# =====================================================================
# ЧАСТЬ 3: Расшифровка видео (взято из вашего файла, адаптировано)
# =====================================================================

from Crypto.Cipher import AES

MPEG_PS_START_CODE = b"\x00\x00\x01\xba"
MPEG_START_CODE_PREFIX = b"\x00\x00\x01"
ANNEX_B_LONG_START_CODE = b"\x00\x00\x00\x01"
HIKVISION_NAL_ENCRYPTED_PREFIX_LENGTH = 4096
AES_BLOCK_SIZE = 16


def decrypt_ezviz_stream(data, key):
    """Упрощенная и адаптированная функция расшифровки потока"""
    key_bytes = key.encode() if isinstance(key, str) else key
    aes_key = key_bytes.ljust(AES_BLOCK_SIZE, b"\0")[:AES_BLOCK_SIZE]

    # Если это не видео-PES пакет, возвращаем как есть
    if len(data) < 4 or data[:3] != MPEG_START_CODE_PREFIX:
        return data

    output = bytearray(data)

    # Ищем NAL unit'ы (начинаются с 00 00 01 или 00 00 00 01)
    i = 0
    while i < len(output) - 4:
        # Ищем начало NAL
        if output[i : i + 4] == ANNEX_B_LONG_START_CODE:
            nal_start = i + 4
            # Пропускаем 2 байта заголовка HEVC (nalu_header_size=2 из вашего кода)
            decrypt_start = nal_start + 2

            # Расшифровываем блоки по 16 байт до лимита 4096
            bytes_decrypted = 0
            pos = decrypt_start
            while (
                pos + AES_BLOCK_SIZE <= len(output)
                and bytes_decrypted < HIKVISION_NAL_ENCRYPTED_PREFIX_LENGTH
            ):
                cipher = AES.new(aes_key, AES.MODE_CBC, iv=bytes(AES_BLOCK_SIZE))
                decrypted_block = cipher.decrypt(
                    bytes(output[pos : pos + AES_BLOCK_SIZE])
                )
                output[pos : pos + AES_BLOCK_SIZE] = decrypted_block

                pos += AES_BLOCK_SIZE
                bytes_decrypted += AES_BLOCK_SIZE

            # Перемещаем указатель дальше этого NAL (грубо)
            i = pos
        else:
            i += 1

    return bytes(output)


# =====================================================================
# ЧАСТЬ 4: Основной цикл подключения и воспроизведения
# =====================================================================


def main():
    print("=== Подключение к облаку Ezviz (VTM Stream) ===\n")

    client = EzvizClient(EMAIL, PASSWORD, url=REGION)
    try:
        print("Выполняю login...")
        client.login()
        print("✅ Логин выполнен успешно\n")
    except Exception as e:
        print(f"❌ Ошибка логина: {e}")
        return

    # 1. Получаем VTM данные
    print("Получение VTM данных...")
    try:
        # Метод может называться по разному в разных версиях pyezvizapi
        if hasattr(client, "get_service_urls"):
            urls = client.get_service_urls()
        elif hasattr(client, "get_vtm_urls"):
            urls = client.get_vtm_urls()
        else:
            urls = client._api_get_service_urls()

        vtm_data = urls.get("VTM", {})
        if not vtm_data:
            print("❌ Не удалось получить VTM адреса")
            # return

        # Берем первый попавшийся VTM сервер
        vtm_server = list(vtm_data.values())[0]
        VTM_HOST = "vtmrus.ezvizru.com"  # vtm_server["domain"]
        VTM_PORT = 10554  # vtm_server["port"]
        print(f"✅ VTM Сервер: {VTM_HOST}:{VTM_PORT}")

    except Exception as e:
        print(f"❌ Ошибка получения VTM: {e}")
        print("Пробуем хардкод вашего сервера...")
        VTM_HOST = "vtmrus.ezvizru.com"
        VTM_PORT = 10554

    # 2. Формируем URL для StreamInfoReq
    # Формат: ysproto://host:port/live?dev=SERIAL&chn=1&stream=1&ssn=TOKEN
    # Токен (ssn) мы берем из сессии авторизации API (RtspSteamSession или похожее)
    try:
        # Попытка получить токен сессии из API
        stream_ssn = (
            client.get_rtsp_stream_url(serial=SERIAL, channel_no=1)
            .split("@")[0]
            .split(":")[1]
        )
    except:
        # Если не вышло, генерируем фейковый, иногда серверу все равно
        stream_ssn = "api_session_token_placeholder"

    stream_url = f"ysproto://{VTM_HOST}:{VTM_PORT}/live?dev={SERIAL}&chn=1&stream=1&ssn={stream_ssn}"

    print(f"\n🎬 Подключение к VTM потоку...")
    print(f"Сервер: {VTM_HOST}:{VTM_PORT}")

    # Запускаем FFplay (из состава FFmpeg) через PIPE для передачи видеопотока без файла
    # FFplay отлично играет сырой MPEG-PS поток
    try:
        ffplay_process = subprocess.Popen(
            [
                "ffplay",
                "-i",
                "pipe:0",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
            ],
            stdin=subprocess.PIPE,
        )
    except FileNotFoundError:
        print(
            "\n❌ FFplay не найден! Установите FFmpeg (ffplay должен быть в комплекте)."
        )
        print("Скачайте: https://ffmpeg.org/download.html")
        return

    # 3. Подключаемся к VTM по TCP
    try:
        sock = socket.create_connection((VTM_HOST, VTM_PORT), timeout=10)
        print("✅ TCP соединение установлено")

        # Отправляем запрос на начало стрима
        req = build_stream_info_request(stream_url)
        packet = encode_vtm_packet(
            req, VtmChannel.MESSAGE, VtmMessageCode.STREAMINFO_REQ, 0
        )
        sock.sendall(packet)
        print("➡️ Отправлен StreamInfoReq")

        stream_started = False
        keepalive_seq = 1

        # Основной цикл чтения пакетов
        while True:
            try:
                channel, seq, msg_code, body = read_vtm_packet(sock)

                # Обработка служебных сообщений
                if channel == VtmChannel.MESSAGE:
                    if msg_code == VtmMessageCode.STREAMINFO_RSP:
                        info = parse_stream_info_response(body)
                        print(
                            f"⬅️ Получен StreamInfoRsp: {info.get('streamhead', '...')}"
                        )
                        stream_started = True

                    elif msg_code == VtmMessageCode.KEEPALIVE_REQ:
                        # Отвечаем на пинг, чтобы сервер не закрыл соединение
                        pong = encode_vtm_packet(
                            body,
                            VtmChannel.MESSAGE,
                            VtmMessageCode.KEEPALIVE_RSP,
                            keepalive_seq,
                        )
                        sock.sendall(pong)
                        keepalive_seq += 1

                # Обработка видеопотока
                elif channel == VtmChannel.STREAM and stream_started:
                    if body and len(body) > 4:
                        # Расшифровываем видео с помощью кода из вашего файла
                        decrypted_data = decrypt_ezviz_stream(body, VALIDATION_CODE)

                        # Пишем сырые расшифрованные данные в FFplay
                        try:
                            ffplay_process.stdin.write(decrypted_data)
                        except BrokenPipeError:
                            print("FFplay закрыт пользователем.")
                            break

            except socket.timeout:
                # Если нет пакетов, шлем свой Keepalive
                if stream_started:
                    ka_body = (
                        b"\x0a\x10" + b"0" * 16
                    )  # Фейковый сессионный ID для поддержания жизни
                    ka_pkt = encode_vtm_packet(
                        ka_body,
                        VtmChannel.MESSAGE,
                        VtmMessageCode.KEEPALIVE_REQ,
                        keepalive_seq,
                    )
                    sock.sendall(ka_pkt)
                    keepalive_seq += 1
            except Exception as e:
                print(f"Ошибка чтения: {e}")
                break

    except Exception as e:
        print(f"❌ Ошибка подключения VTM: {e}")
    finally:
        sock.close()
        ffplay_process.kill()


if __name__ == "__main__":
    main()
