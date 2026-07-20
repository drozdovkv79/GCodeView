import base64
import binascii
import hashlib
import json
import re
import socket
import struct
import subprocess
import sys
import time

import requests
from Crypto.Cipher import AES

# ========================= КОНФИГУРАЦИЯ =========================
EMAIL = "drozdovkv79@yandex.ru"
PASSWORD = "Luxor!2345"
SERIAL = "BB1486658"
VALIDATION_CODE = "HVUMAV"

CHANNEL = 1
STREAM_TYPE = 0  # 0 или 1
FOLLOW_REDIRECT = True
MAX_REDIRECTS = 3
DEBUG = True  # полные дампы
# ================================================================


class VtmChannel:
    MESSAGE = 0x00
    STREAM = 0x01


class VtmMessageCode:
    KEEPALIVE_REQ = 0x0132
    KEEPALIVE_RSP = 0x0133
    STREAMINFO_REQ = 0x013B
    STREAMINFO_RSP = 0x013C


VTM_MAGIC = 0x24
HEADER_SIZE = 8


def hexdump(data, label="", max_len=None):
    if not data:
        print(f"{label} [0 байт]")
        return
    hex_str = binascii.hexlify(data).decode()
    if max_len and len(hex_str) > max_len:
        hex_str = hex_str[:max_len] + "..."
    print(f"{label} [{len(data)} байт]: {hex_str}")


def encode_varint(value):
    buf = b""
    while value > 0x7F:
        buf += bytes([(value & 0x7F) | 0x80])
        value >>= 7
    buf += bytes([value])
    return buf


def decode_varint(data, offset=0):
    result = 0
    shift = 0
    pos = offset
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def encode_packet(body: bytes, channel: int, msg_code: int, seq: int = 0) -> bytes:
    length = len(body)
    header = struct.pack(">BBHHH", VTM_MAGIC, channel, length, seq & 0xFFFF, msg_code)
    packet = header + body
    if DEBUG:
        hexdump(packet, f"➡️ Send (ch={channel} code=0x{msg_code:04X} seq={seq})")
    return packet


def recv_exact(sock, length):
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Сервер закрыл соединение")
        data += chunk
    return data


def read_packet(sock):
    header = recv_exact(sock, HEADER_SIZE)
    if DEBUG:
        hexdump(header, "📦 Header")
    length = struct.unpack(">H", header[2:4])[0]
    channel = header[1]
    seq = struct.unpack(">H", header[4:6])[0]
    msg_code = struct.unpack(">H", header[6:8])[0]
    body = recv_exact(sock, length) if length else b""
    print(f"← [ch={channel} code=0x{msg_code:04X} len={len(body)} seq={seq}]")
    if DEBUG or body:
        hexdump(body, "   Body", max_len=512 if not DEBUG else None)
    return channel, seq, msg_code, body


def parse_redirect(body: bytes):
    try:
        text = body.decode("utf-8", errors="ignore")
        match = re.search(
            r'(ysproto|Xysproto)://([\w\.-]+):(\d+)(/live\?[^"\s]+)',
            text,
            re.IGNORECASE,
        )
        if match:
            protocol = match.group(1).lower()
            host = match.group(2)
            port = int(match.group(3))
            path = match.group(4)
            new_url = f"{protocol}://{host}:{port}{path}"
            print(f"🔄 Найден редирект: {new_url}")
            return host, port, new_url
    except:
        pass
    return None, None, None


def parse_error_code(body: bytes):
    if not body or body[0] != 0x08:
        return None
    code, _ = decode_varint(body, 1)
    return code


# ====================== ЛОГИН через api.ezvizru.com ======================
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "okhttp/3.12.1",
        "clienttype": "3",
        "clientversion": "5.9.8.0215",
        "language": "ru_RU",
    }
)


def login_ezviz():
    print("🔐 Авторизация в Ezviz RU...")
    pwd_md5 = hashlib.md5(PASSWORD.encode("utf-8")).hexdigest()
    payload = {
        "account": EMAIL,
        "password": pwd_md5,
        "featureCode": "896be422a6df398453e3dd4a6894721c",
        "msgType": "0",
        "bizType": "",
        "cuName": base64.b64encode(b"PythonVTMClient").decode(),
        "smsCode": "",
    }
    r = session.post(
        "https://api.ezvizru.com/v3/users/login/v5", data=payload, timeout=15
    )
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    resp = r.json()
    if DEBUG:
        print("Ответ сервера:", json.dumps(resp, ensure_ascii=False, indent=2)[:1000])
    meta = resp.get("meta", {})
    if meta.get("code") != 200:
        raise Exception(f"Ошибка логина: {meta.get('code')} - {meta.get('message')}")
    login_session = resp.get("loginSession", {})
    session_id = login_session.get("sessionId")
    if not session_id:
        raise Exception("Не получен sessionId")
    session.headers.update(
        {
            "sessionid": session_id,
            "areaid": str(resp.get("loginArea", {}).get("areaId", 1)),
        }
    )
    print("✅ Логин в Ezviz RU успешен")
    return session_id


# ====================== ЛОГИН через open.ys7.com для получения accessToken ======================
def get_ys7_access_token():
    print("🔑 Получение accessToken через open.ys7.com...")
    url = "https://open.ys7.com/api/lapp/v2/user/login"
    pwd_md5 = hashlib.md5(PASSWORD.encode("utf-8")).hexdigest()
    data = {"userName": EMAIL, "password": pwd_md5}
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            resp = r.json()
            if resp.get("code") == "200":
                token = resp.get("data", {}).get("accessToken")
                if token:
                    print("✅ accessToken получен")
                    return token
                else:
                    print("⚠️ accessToken отсутствует в ответе")
            else:
                print(f"⚠️ Ошибка open API: {resp.get('code')} - {resp.get('msg')}")
        else:
            print(f"⚠️ HTTP {r.status_code} от open.ys7.com")
    except Exception as e:
        print(f"⚠️ Исключение при получении accessToken: {e}")
    return None


def get_ssn_from_open_api(access_token, serial, channel, stream_type):
    """Запрашивает ssn через open.ys7.com"""
    print(
        f"📡 Запрос live address через open API для {serial}/{channel} stream_type={stream_type}"
    )
    url = "https://open.ys7.com/api/lapp/v2/live/address/get"
    params = {
        "accessToken": access_token,
        "deviceSerial": serial,
        "channelNo": channel,
        "streamType": stream_type,
        "protocol": 1,  # 1 = RTSP, 2 = HLS, 3 = RTMP, но нас интересует ssn
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            resp = r.json()
            if resp.get("code") == "200":
                data = resp.get("data", {})
                # В ответе может быть поле "ssn", а также "liveAddress"
                ssn = data.get("ssn")
                if ssn:
                    print("✅ ssn получен через open API")
                    return ssn
                else:
                    print(f"⚠️ ssn не найден в ответе open API: {data.keys()}")
            else:
                print(f"⚠️ Ошибка open API: {resp.get('code')} - {resp.get('msg')}")
        else:
            print(f"⚠️ HTTP {r.status_code} от open API")
    except Exception as e:
        print(f"⚠️ Исключение: {e}")
    return None


# ====================== VTM ПОДКЛЮЧЕНИЕ ======================
def connect_vtm(
    host: str,
    port: int,
    stream_url: str,
    redirect_count=0,
    stream_type_override=None,
    ssn_override=None,
):
    global STREAM_TYPE
    current_stream_type = (
        stream_type_override if stream_type_override is not None else STREAM_TYPE
    )

    print(
        f"\n🔌 Подключаемся к {host}:{port} (попытка {redirect_count + 1}, stream_type={current_stream_type})"
    )
    sock = socket.create_connection((host, port), timeout=15)
    sock.settimeout(10)

    if ssn_override:
        stream_url = re.sub(r"ssn=[^&]+", f"ssn={ssn_override}", stream_url)
        print(f"   Используем обновлённый ssn")
    stream_url = re.sub(r"stream=\d+", f"stream={current_stream_type}", stream_url)
    print(f"   URL: {stream_url[:200]}...")

    req_body = (
        b"\x0a"
        + encode_varint(len(stream_url))
        + stream_url.encode()
        + b"\x1a\x0b"
        + b"v5.9.8.0215"
        + b"\x20\x00\x28\x01\x30\x01"
    )
    packet = encode_packet(
        req_body, VtmChannel.MESSAGE, VtmMessageCode.STREAMINFO_REQ, 1
    )
    sock.sendall(packet)

    stream_started = False
    seq = 2
    ffplay = None
    last_ka = time.time()

    try:
        ffplay = subprocess.Popen(
            [
                "ffplay",
                "-i",
                "pipe:0",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-probesize",
                "10000000",
                "-analyzeduration",
                "10000000",
                "-sync",
                "ext",
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        while True:
            try:
                channel, _, msg_code, body = read_packet(sock)

                if channel == VtmChannel.MESSAGE:
                    if msg_code == VtmMessageCode.STREAMINFO_RSP:
                        if len(body) <= 10:
                            err_code = parse_error_code(body)
                            if err_code is not None:
                                print(f"❌ Сервер отказал, код ошибки: {err_code}")
                                if err_code == 6110:
                                    print(
                                        "   Код 6110: недействительная сессия / неверный тип потока"
                                    )
                                    # Пробуем получить новый ssn через open API
                                    access_token = get_ys7_access_token()
                                    if access_token:
                                        new_ssn = get_ssn_from_open_api(
                                            access_token,
                                            SERIAL,
                                            CHANNEL,
                                            current_stream_type,
                                        )
                                        if new_ssn:
                                            print(
                                                f"🔄 Повторяем подключение с новым ssn"
                                            )
                                            sock.close()
                                            return connect_vtm(
                                                host,
                                                port,
                                                stream_url,
                                                redirect_count + 1,
                                                current_stream_type,
                                                new_ssn,
                                            )
                                    # Если не получили ssn, пробуем сменить тип потока
                                    new_type = 1 if current_stream_type == 0 else 0
                                    print(
                                        f"🔄 Повторяем подключение с stream_type={new_type}"
                                    )
                                    sock.close()
                                    return connect_vtm(
                                        host,
                                        port,
                                        stream_url,
                                        redirect_count + 1,
                                        new_type,
                                        ssn_override,
                                    )
                                else:
                                    print(f"   Неизвестная ошибка, завершаем")
                                    break
                            else:
                                print(f"❌ Неизвестный короткий ответ: {body.hex()}")
                                break
                        else:
                            print("✅ StreamInfoRsp получен (длинный ответ)")
                            new_host, new_port, new_url = parse_redirect(body)
                            if FOLLOW_REDIRECT and new_host and new_host != host:
                                if redirect_count >= MAX_REDIRECTS:
                                    print("❌ Превышено количество редиректов")
                                    break
                                print("🔄 Выполняем редирект...")
                                sock.close()
                                # При редиректе попробуем получить свежий ssn через open API
                                access_token = get_ys7_access_token()
                                new_ssn = None
                                if access_token:
                                    new_ssn = get_ssn_from_open_api(
                                        access_token,
                                        SERIAL,
                                        CHANNEL,
                                        current_stream_type,
                                    )
                                return connect_vtm(
                                    new_host,
                                    new_port,
                                    new_url,
                                    redirect_count + 1,
                                    current_stream_type,
                                    new_ssn,
                                )
                            else:
                                stream_started = True
                                print("🎥 Ожидание видеопотока...")

                    elif msg_code == VtmMessageCode.KEEPALIVE_REQ:
                        print("↔ Keepalive от сервера")
                        pong = encode_packet(
                            body or b"\x00",
                            VtmChannel.MESSAGE,
                            VtmMessageCode.KEEPALIVE_RSP,
                            seq,
                        )
                        sock.sendall(pong)
                        seq += 1
                        last_ka = time.time()

                elif channel == VtmChannel.STREAM:
                    if stream_started and len(body) > 80:
                        print(f"📹 Видеопакет {len(body)} байт")
                        decrypted = decrypt_stream(body, VALIDATION_CODE)
                        try:
                            ffplay.stdin.write(decrypted)
                            ffplay.stdin.flush()
                        except BrokenPipeError:
                            print("FFplay закрыт")
                            break
                    elif DEBUG and len(body) <= 80:
                        print(f"📦 Малый STREAM пакет ({len(body)} байт), игнорируем")

            except socket.timeout:
                if stream_started and time.time() - last_ka > 8:
                    print("⏰ Отправляем Keepalive")
                    ka = encode_packet(
                        b"", VtmChannel.MESSAGE, VtmMessageCode.KEEPALIVE_REQ, seq
                    )
                    sock.sendall(ka)
                    seq += 1
                    last_ka = time.time()
            except Exception as e:
                print(f"Ошибка в цикле: {e}")
                break
    finally:
        if sock:
            sock.close()
        if ffplay:
            ffplay.kill()


def main():
    try:
        session_id = login_ezviz()
    except Exception as e:
        print("❌ Ошибка логина в Ezviz RU:", e)
        return

    # Пытаемся получить ssn через open API сразу (чтобы использовать его в основном URL)
    access_token = get_ys7_access_token()
    ssn = None
    if access_token:
        ssn = get_ssn_from_open_api(access_token, SERIAL, CHANNEL, STREAM_TYPE)
    if not ssn:
        # fallback: используем sessionId как ssn
        ssn = session_id
        print(f"⚠️ Используем sessionId как ssn (может не работать)")

    initial_url = f"ysproto://vtmrus.ezvizru.com:10554/live?dev={SERIAL}&chn={CHANNEL}&stream={STREAM_TYPE}&ssn={ssn}"
    print(f"Initial URL: {initial_url}")

    try:
        connect_vtm("vtmrus.ezvizru.com", 10554, initial_url)
    except Exception as e:
        print("❌ Ошибка во время потока:", e)


def decrypt_stream(data: bytes, key: str) -> bytes:
    if len(data) < 40:
        return data
    key_bytes = key.encode("utf-8").ljust(16, b"\0")[:16]
    output = bytearray(data)
    i = 0
    while i < len(output) - 32:
        if (
            output[i : i + 3] == b"\x00\x00\x01"
            or output[i : i + 4] == b"\x00\x00\x00\x01"
        ):
            start = i + 4 if output[i + 3] == 1 else i + 3
            pos = start + 2
            while pos + 16 <= len(output) and (pos - start) < 8192:
                cipher = AES.new(key_bytes, AES.MODE_CBC, iv=b"\x00" * 16)
                block = output[pos : pos + 16]
                if len(block) == 16:
                    output[pos : pos + 16] = cipher.decrypt(block)
                pos += 16
            i = pos
        else:
            i += 1
    return bytes(output)


if __name__ == "__main__":
    main()
