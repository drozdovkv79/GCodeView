#!/usr/bin/env python3
"""
EZVIZ Camera Viewer — Russian region with correct relay protocol

Protocol reverse-engineered from Wireshark capture:
  Header format: [0x24][phase(1)][payload_len(2)][serial(4)][reserved(2)]
  Phase 1 (client→server): Send ECDH client public key
  Phase 2 (server→client): Receive ECDH server public key + AES-CBC encrypted payload
  Phase 3 (client→server): Send AES-CBC encrypted auth payload
  Phase 4: Receive FLV video stream
"""

import base64
import hashlib
import json
import os
import platform
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ─────────────────────────── CONSTANTS ───────────────────────────

EZVIZ_USER_AGENT = "EZVIZ/4.9.2 (iPhone; iOS 14.3; Scale/3.00)"
EZVIZ_CLIENT_TYPE = "1"

REGION_MAP = {
    "Global (EU)": ("apiieu.ezvizlife.com", 200, "apiieu.ezvizlife.com"),
    "USA": ("apiius.ezvizlife.com", 314, "apiius.ezvizlife.com"),
    "China": ("apichina.ezvizlife.com", 100, "apichina.ezvizlife.com"),
    "Australia": ("apiieu.ezvizlife.com", 501, "apiieu.ezvizlife.com"),
    "UK": ("apiieu.ezvizlife.com", 142, "apiieu.ezvizlife.com"),
    "Russia": ("api.ezvizru.com", 643, "apiirus.ezvizru.com"),
}


_FONT_UI, _FONT_MONO = "monospace", "monospace"


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class EzvizAPIError(Exception):
    pass


class _PostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        r = urllib.request.Request(
            newurl,
            data=req.data if req.get_method() == "POST" else None,
            method="POST" if req.get_method() == "POST" else "GET",
        )
        for k, v in req.header_items():
            r.add_unredirected_header(k, v)
        return r


_opener = urllib.request.build_opener(_PostRedirect)


def _post(url, data, headers=None, json_mode=False, timeout=15):
    body = (
        json.dumps(data).encode()
        if json_mode
        else urllib.parse.urlencode(data).encode()
    )
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_unredirected_header(
        "Content-Type",
        "application/json" if json_mode else "application/x-www-form-urlencoded",
    )
    req.add_unredirected_header("User-Agent", EZVIZ_USER_AGENT)
    req.add_unredirected_header("clientType", EZVIZ_CLIENT_TYPE)
    if headers:
        for k, v in headers.items():
            req.add_unredirected_header(k, str(v))
    try:
        with _opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise EzvizAPIError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except Exception as e:
        raise EzvizAPIError(str(e))


def _get(url, headers=None, timeout=15):
    req = urllib.request.Request(url)
    req.add_unredirected_header("User-Agent", EZVIZ_USER_AGENT)
    req.add_unredirected_header("clienttype", EZVIZ_CLIENT_TYPE)
    if headers:
        for k, v in headers.items():
            req.add_unredirected_header(k, str(v))
    try:
        with _opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise EzvizAPIError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except Exception as e:
        raise EzvizAPIError(str(e))


# ─────────────────────────── API CLIENT ───────────────────────────


class EzvizClient:
    def __init__(self, email, password, domain, region_code=643, streaming_domain=None):
        self.email = email
        self.password = password
        self.domain = domain
        self.region_code = region_code
        self.streaming_domain = streaming_domain or domain
        self.feature_code = md5(email)
        self.session_id = None
        self.rf_session_id = None
        self.user_id = None

    def _auth(self):
        return {
            "sessionId": self.session_id,
            "featureCode": self.feature_code,
            "language": "ru",
            "countryCode": str(self.region_code),
        }

    def login(self):
        url = f"https://{self.domain}/v3/users/login/v5"
        data = {
            "account": self.email,
            "featureCode": self.feature_code,
            "password": md5(self.password),
            "clientType": EZVIZ_CLIENT_TYPE,
            "countryCode": str(self.region_code),
            "language": "ru",
            "os": "iOS",
        }
        resp = _post(url, data)
        if (
            resp.get("meta", {}).get("code") not in (200, None)
            and "loginSession" not in resp
        ):
            raise EzvizAPIError(f"Login failed: {resp.get('meta', {})}")
        sess = resp.get("loginSession", {})
        self.session_id = sess.get("sessionId")
        self.rf_session_id = sess.get("rfSessionId")
        self.user_id = str(resp.get("userInfo", {}).get("userId", ""))
        if not self.session_id:
            raise EzvizAPIError("No sessionId")
        return resp

    def get_devices(self):
        url = (
            f"https://{self.domain}/v3/userdevices/v1/resources/pagelist"
            f"?filter=CONNECTION%2CSWITCH%2CSTATUS%2CNODISTURB%2CP2P%2CFEATURE%2CDETECTOR"
            f"&groupId=-1&limit=50&offset=0"
        )
        resp = _get(url, self._auth())
        return resp.get("deviceInfos", resp.get("deviceSummaryList", []))

    def get_relay_info(self, serial, channel=1):
        for domain in [self.streaming_domain, self.domain]:
            url = (
                f"https://{domain}/v3/streaming/query/relay/{serial}/{channel}"
                f"?channelNo={channel}&deviceSerials={serial}"
            )
            try:
                resp = _get(url, self._auth())
                if resp.get("meta", {}).get("code") == 200:
                    return resp
            except EzvizAPIError:
                pass
        return None

    def get_camera_info(self, serial):
        for ep in (
            f"/v3/userdevices/v1/devices/{serial}/info",
            f"/v3/userdevices/v1/devices/{serial}",
        ):
            try:
                return _get(f"https://{self.domain}{ep}", self._auth()) or {}
            except EzvizAPIError:
                pass
        return {}

    def logout(self):
        if not self.session_id:
            return
        try:
            _post(
                f"https://{self.domain}/v3/users/logout",
                {"sessionId": self.session_id},
                self._auth(),
            )
        except:
            pass
        self.session_id = None

    # ───────────────── Добавить в класс EzvizClient ─────────────────

    def start_live_stream(self, serial, channel=1, quality=2):
        """Get direct stream URL (HLS/FLV) - the official way!"""
        # Try multiple known endpoint patterns
        endpoints = [
            # Pattern 1: v3 live stream start (most common for RU region)
            ("POST", f"/v3/live/stream/start"),
            # Pattern 2: v2 stream start
            ("POST", f"/v2/live/stream/start"),
            # Pattern 3: Direct stream address
            ("POST", f"/v3/streaming/address"),
        ]

        for domain in [self.streaming_domain, self.domain]:
            for method, path in endpoints:
                url = f"https://{domain}{path}"
                payload = {
                    "deviceSerial": serial,
                    "channelNo": channel,
                    "quality": quality,
                    "type": 1,
                }
                try:
                    print(f"[DEBUG] {method} {url}")
                    resp = _post(url, payload, self._auth(), json_mode=True)
                    print(f"[DEBUG] Resp: {json.dumps(resp, ensure_ascii=False)[:500]}")
                    if resp.get("meta", {}).get("code") == 200:
                        return resp
                except EzvizAPIError as e:
                    print(f"[DEBUG] Fail: {str(e)[:80]}")

        # Fallback: Try GET requests with different paths
        for domain in [self.streaming_domain, self.domain]:
            for path in [
                f"/v3/live/stream/address/{serial}/{channel}",
                f"/v3/streaming/url/{serial}/{channel}",
                f"/v3/cameras/{serial}/stream",
            ]:
                url = f"https://{domain}{path}?channelNo={channel}&quality={quality}&streamType=0"
                try:
                    print(f"[DEBUG] GET {url}")
                    resp = _get(url, self._auth())
                    if resp.get("meta", {}).get("code") == 200:
                        return resp
                except EzvizAPIError:
                    pass

        return None

    def get_streaming_ticket(self, serial, channel=1):
        """Get streaming ticket (required for relay authentication!)."""
        for domain in [self.streaming_domain, self.domain]:
            url = (
                f"https://{domain}/v3/streaming/ticket/{serial}/{channel}"
                f"?channelNo={channel}&deviceSerials={serial}"
            )
            try:
                resp = _get(url, self._auth())
                if resp.get("meta", {}).get("code") == 200:
                    return resp.get("ticket", "")
            except EzvizAPIError:
                pass
        return None

    def compensate_status(self, serial):
        """Call compensate endpoint before streaming."""
        for domain in [self.streaming_domain, self.domain]:
            url = f"https://{domain}/v3/userdevices/v1/resources/compensate/STATUS?deviceSerials={serial}"
            try:
                return _get(url, self._auth())
            except EzvizAPIError:
                pass
        return None

    def get_stream_info(self, serial, channel=1):
        """Get RTSP / local stream info."""
        for ep in (
            f"/v3/userdevices/v1/cameras/{serial}/stream",
            f"/v3/userdevices/v1/devices/{serial}/stream",
        ):
            for sid in ("", f"&sessionId={self.session_id}"):
                try:
                    url = (
                        f"https://{self.domain}{ep}"
                        f"?channelNo={channel}&streamType=0{sid}"
                    )
                    return _get(url, self._auth()) or {}
                except EzvizAPIError:
                    pass
        return {}

    def compensate_status(self, serial):
        """Call compensate endpoint before streaming."""
        for domain in [self.streaming_domain, self.domain]:
            url = f"https://{domain}/v3/userdevices/v1/resources/compensate/STATUS?deviceSerials={serial}"
            try:
                return _get(url, self._auth())
            except EzvizAPIError:
                pass
        return None


# ─────────────────────── RELAY STREAM WORKER ─────────────────────
# Protocol from Wireshark capture (correct implementation)


class RelayStreamWorker(QThread):
    status_update = pyqtSignal(str)
    stream_error = pyqtSignal(str)

    def __init__(
        self,
        relay_info,
        session_id,
        device_serial,
        ticket="",
        encrypt_pwd="",
        channel=1,
        quality=2,
    ):
        super().__init__()
        self.relay_info = relay_info
        self.session_id = session_id
        self.device_serial = device_serial
        self.ticket = ticket
        self.encrypt_pwd = encrypt_pwd
        self.channel = channel
        self.quality = quality
        self._stop = threading.Event()
        self.proc = None

    def run(self):
        try:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
                load_der_public_key,
            )
        except ImportError:
            self.stream_error.emit(
                "Нужна библиотека 'cryptography'.\nУстановите: pip install cryptography"
            )
            return

        cfg = self.relay_info.get("streamServerConfig", {})
        domain = cfg.get("domain", "")
        port = cfg.get("port", 0)
        pub_key_b64 = cfg.get("publicKey", {}).get("key", "")

        if not domain or not port:
            self.stream_error.emit("Нет данных relay-сервера")
            return

        self.status_update.emit(f"🔌 Подключение к {domain}:{port}…")

        try:
            sock = socket.create_connection((domain, port), timeout=10)
        except Exception as e:
            self.stream_error.emit(f"Не удалось подключиться к {domain}:{port}\n{e}")
            return

        try:
            self._handshake(
                sock,
                domain,
                port,
                pub_key_b64,
                ec,
                Encoding,
                PublicFormat,
                load_der_public_key,
                Cipher,
                algorithms,
                modes,
                default_backend,
            )
        except Exception as e:
            self.stream_error.emit(f"Relay ошибка: {e}")
        finally:
            try:
                sock.close()
            except:
                pass

    def _recv_exactly(self, sock, n, timeout=10):
        sock.settimeout(timeout)
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def _recv_msg(self, sock, timeout=10):
        hdr = self._recv_exactly(sock, 8, timeout)
        if len(hdr) < 8 or hdr[0] != 0x24:
            return hdr, -1, b""

        phase = hdr[1]
        payload_len = struct.unpack(">H", hdr[2:4])[0]
        seq = struct.unpack(">I", hdr[4:8])[0]
        print(f"[DEBUG] Recv: phase={phase} len={payload_len} seq={seq}")

        payload = b""
        if payload_len > 0:
            payload = self._recv_exactly(sock, payload_len, timeout)

        return hdr, phase, payload

    def _handshake(
        self,
        sock,
        domain,
        port,
        pub_key_b64,
        ec,
        Encoding,
        PublicFormat,
        load_der_public_key,
        Cipher,
        algorithms,
        modes,
        backend,
    ):

        # ─── STEP 1: Generate ECDH and send Phase 1 ───
        eph_key = ec.generate_private_key(ec.SECP256R1(), backend)
        client_pub_der = eph_key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        client_pub_raw = eph_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )

        # Build Phase 1 payload (342 bytes)
        payload1 = bytearray(342)
        payload1[0:3] = b"\x01\x01\x00"
        payload1[3] = 0x00
        payload1[4 : 4 + 65] = client_pub_raw
        payload1[69 : 69 + 91] = client_pub_der

        hdr1 = struct.pack(">BBHI", 0x24, 0x01, 342, 9)
        msg1 = hdr1 + bytes(payload1)

        print(f"[DEBUG] Sending Phase 1 ({len(msg1)} bytes)")
        sock.sendall(msg1)

        # ─── STEP 2: Receive Phase 2 ───
        hdr2, phase2, payload2 = self._recv_msg(sock, timeout=10)
        if phase2 == 12:
            err_code = (
                struct.unpack(">H", payload2[-2:])[0] if len(payload2) >= 2 else 0
            )
            self.stream_error.emit(f"Relay отклонил Phase 1 (код: 0x{err_code:04x})")
            return

        if phase2 != 2:
            self.stream_error.emit(f"Ожидали фазу 2, получили {phase2}")
            return

        print(f"[DEBUG] Phase 2 OK ({len(payload2)} bytes)")

        # ─── STEP 3: Derive AES Key ───
        if len(payload2) < 70:
            self.stream_error.emit(f"Слишком короткий payload фазы 2")
            return

        server_pub_raw = payload2[6 : 6 + 65]
        server_pub_der_bytes = (
            b"\x30\x56\x30\x10\x06\x07\x2a\x86\x48\xce\x3d\x02\x01"
            b"\x06\x05\x2b\x81\x04\x00\x22\x03\x42\x00" + server_pub_raw
        )
        server_key = load_der_public_key(server_pub_der_bytes, backend)
        shared_secret = eph_key.exchange(ec.ECDH(), server_key)
        aes_key = hashlib.sha256(shared_secret).digest()[:16]
        print(f"[DEBUG] AES key derived")

        # ─── STEP 4: Send Phase 3 (Auth with Ticket!) ───
        auth_dict = {
            "sessionId": self.session_id,
            "deviceSerial": self.device_serial,
            "channelNo": self.channel,
            "quality": self.quality,
            "clientType": 1,
            "clientVersion": "7.4.4.2720787",
            "checkCode": md5(self.session_id + self.device_serial),
        }

        # THIS IS THE KEY FIX: Include the ticket!
        if self.ticket:
            auth_dict["ticket"] = self.ticket

        if self.encrypt_pwd:
            auth_dict["encryptPwd"] = self.encrypt_pwd
            auth_dict["verifyCode"] = self.encrypt_pwd

        auth_json = json.dumps(auth_dict, separators=(",", ":")).encode()
        print(
            f"[DEBUG] Auth payload: ticket={'YES' if self.ticket else 'NO'}, size={len(auth_json)}"
        )

        # Encrypt auth payload using AES-CBC
        iv3 = os.urandom(16)
        pad = 16 - (len(auth_json) % 16)
        padded = auth_json + bytes([pad] * pad)
        enc3 = Cipher(algorithms.AES(aes_key), modes.CBC(iv3), backend).encryptor()
        encrypted_auth = enc3.update(padded) + enc3.finalize()

        payload3 = bytearray()
        payload3 += b"\x01\x00\x00\x00"
        payload3 += iv3
        payload3 += encrypted_auth

        hdr3 = struct.pack(">BBHI", 0x24, 0x03, len(payload3), 0)
        msg3 = hdr3 + bytes(payload3)

        print(f"[DEBUG] Sending Phase 3 ({len(msg3)} bytes)")
        sock.sendall(msg3)

        # ─── STEP 5: Receive Phase 4 (FLV Stream) ───
        self.status_update.emit("📡 Ожидание видеопотока…")
        sock.settimeout(15)

        # Read data until we find FLV signature or get an error
        buffer = b""
        try:
            while not self._stop.is_set():
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk

                # Check for error message
                if len(buffer) >= 8 and buffer[0] == 0x24 and buffer[1] == 0x0C:
                    plen = struct.unpack(">H", buffer[2:4])[0]
                    if len(buffer) >= 8 + plen:
                        err_code = struct.unpack(">H", buffer[6 + plen - 2 : 6 + plen])[
                            0
                        ]
                        self.stream_error.emit(
                            f"Relay отклонил авторизацию (код: 0x{err_code:04x})"
                        )
                        return

                # Look for FLV signature
                flv_idx = buffer.find(b"FLV")
                if flv_idx >= 0:
                    print(f"[DEBUG] FLV signature found at offset {flv_idx}!")
                    self._pipe_stream(sock, buffer[flv_idx:], domain)
                    return

        except socket.timeout:
            if buffer:
                print(
                    f"[DEBUG] Timeout, but got {len(buffer)} bytes. Trying to pipe..."
                )
                self._pipe_stream(sock, buffer, domain)
                return

        self.stream_error.emit("Не удалось получить видеопоток от relay")

    def _pipe_stream(self, sock, initial_data, domain):
        cmd = [
            "ffplay",
            "-f",
            "flv",
            "-probesize",
            "65536",
            "-analyzeduration",
            "1000000",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-window_title",
            f"EZVIZ – {self.device_serial}",
            "-x",
            "960",
            "-y",
            "540",
            "-i",
            "pipe:0",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self.stream_error.emit("ffplay не найден. Установите FFmpeg.")
            return

        self.status_update.emit(f"📹 Стриминг с {domain}…")

        try:
            self.proc.stdin.write(initial_data)
            self.proc.stdin.flush()
        except BrokenPipeError:
            pass

        sock.settimeout(30)
        while not self._stop.is_set():
            try:
                data = sock.recv(16384)
                if not data:
                    break
                try:
                    self.proc.stdin.write(data)
                    self.proc.stdin.flush()
                except BrokenPipeError:
                    break
            except socket.timeout:
                break
            except Exception:
                break

        try:
            self.proc.stdin.close()
        except:
            pass

    def stop(self):
        self._stop.set()
        if self.proc:
            try:
                self.proc.terminate()
            except:
                pass


# ─────────────────────── RTSP STREAM WORKER ──────────────────────


class RtspStreamWorker(QThread):
    status_update = pyqtSignal(str)
    stream_error = pyqtSignal(str)

    def __init__(self, url, serial):
        super().__init__()
        self.url = url
        self.serial = serial
        self._stop = threading.Event()
        self.proc = None

    def run(self):
        self.status_update.emit("🎬 Запуск RTSP…")
        cmd = [
            "ffplay",
            "-rtsp_transport",
            "tcp",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-window_title",
            f"EZVIZ – {self.serial}",
            "-x",
            "960",
            "-y",
            "540",
            self.url,
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            _, stderr = self.proc.communicate()
            if self.proc.returncode != 0 and not self._stop.is_set():
                self.stream_error.emit(
                    f"ffplay ошибка:\n{stderr.decode(errors='replace')[-300:]}"
                )
        except FileNotFoundError:
            self.stream_error.emit("ffplay не найден.")
        except Exception as e:
            self.stream_error.emit(str(e))

    def stop(self):
        self._stop.set()
        if self.proc:
            self.proc.terminate()


# ─────────────────────── WORKERS ─────────────────────────────────


class LoginWorker(QThread):
    success = pyqtSignal(object, list)
    error = pyqtSignal(str)

    def __init__(self, email, password, domain, region_code, streaming_domain):
        super().__init__()
        self.email = email
        self.password = password
        self.domain = domain
        self.region_code = region_code
        self.streaming_domain = streaming_domain

    def run(self):
        try:
            c = EzvizClient(
                self.email,
                self.password,
                self.domain,
                self.region_code,
                self.streaming_domain,
            )
            c.login()
            devs = c.get_devices()
            self.success.emit(c, devs)
        except Exception as e:
            self.error.emit(str(e))


class DeviceInfoWorker(QThread):
    done = pyqtSignal(dict, dict)
    error = pyqtSignal(str)

    def __init__(self, client, serial):
        super().__init__()
        self.client = client
        self.serial = serial

    def run(self):
        try:
            info = self.client.get_camera_info(self.serial)
            relay = self.client.get_relay_info(self.serial) or {}
            self.done.emit(info, relay)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────── VERIFY CODE DIALOG ──────────────────────


class VerifyCodeDialog(QDialog):
    def __init__(self, cam_name, serial, ip, port, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Код верификации камеры")
        self.setMinimumWidth(440)
        self.verify_code = ""
        self.ip = ip
        self.port = port
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        info = QLabel(
            f"📸 <b>{cam_name}</b><br><code>{serial}</code><br><br>"
            "Для RTSP нужен код верификации с наклейки камеры."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("ABCDEF")
        layout.addWidget(self.code_input)
        br = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(self._ok)
        cn = QPushButton("Отмена")
        cn.setObjectName("secondary")
        cn.clicked.connect(self.reject)
        br.addWidget(ok)
        br.addWidget(cn)
        layout.addLayout(br)
        self.code_input.returnPressed.connect(self._ok)

    def _ok(self):
        c = self.code_input.text().strip()
        if c:
            self.verify_code = c
            self.accept()

    def get_rtsp_urls(self):
        c, ip, p = self.verify_code, self.ip, self.port
        return [
            f"rtsp://admin:{c}@{ip}:{p}/Streaming/Channels/101",
            f"rtsp://admin:{c}@{ip}:{p}/h264/ch1/main/av_stream",
        ]


# ─────────────────────────── HELPERS ─────────────────────────────


def _extract_online_status(dev):
    for src in (dev.get("CONNECTION"), dev.get("connection"), dev.get("STATUS")):
        if isinstance(src, dict):
            v = src.get("isOnline")
            if v is not None:
                return bool(v)
    for k in ("status", "online", "isOnline"):
        v = dev.get(k)
        if v is not None:
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v != 0
    return None


def _extract_conn(dev):
    r = {}
    for key in ("CONNECTION", "connection"):
        c = dev.get(key)
        if isinstance(c, dict):
            for f in ("localIp", "localRtspPort", "netType"):
                if c.get(f) is not None:
                    r[f] = c[f]
    return r


# ─────────────────────────── UI ──────────────────────────────────

DARK_BG = "#0d1117"
PANEL_BG = "#161b22"
CARD_BG = "#1c2230"
BORDER = "#30363d"
ACCENT = "#238636"
ACCENT_HOVER = "#2ea043"
ACCENT_DANGER = "#da3633"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED = "#8b949e"
TEXT_LINK = "#58a6ff"
CAM_ONLINE = "#3fb950"
CAM_OFFLINE = "#f85149"

STYLE = f"""
QWidget {{ background-color:{DARK_BG}; color:{TEXT_PRIMARY};
    font-family:'{_FONT_UI}'; font-size:13px; }}
QMainWindow {{ background-color:{DARK_BG}; }}
QFrame#sidebar {{ background-color:{PANEL_BG}; border-right:1px solid {BORDER}; }}
QFrame#content {{ background-color:{DARK_BG}; }}
QGroupBox {{ border:1px solid {BORDER}; border-radius:8px;
    margin-top:14px; padding-top:8px; font-weight:600;
    color:{TEXT_MUTED}; font-size:11px; letter-spacing:0.8px; text-transform:uppercase; }}
QGroupBox::title {{ subcontrol-origin:margin; left:10px; top:-2px;
    padding:0 4px; background-color:{PANEL_BG}; }}
QLineEdit {{ background-color:{CARD_BG}; border:1px solid {BORDER};
    border-radius:6px; padding:8px 12px; color:{TEXT_PRIMARY}; }}
QLineEdit:focus {{ border:1px solid {TEXT_LINK}; }}
QPushButton {{ background-color:{ACCENT}; color:white; border:none;
    border-radius:6px; padding:9px 20px; font-weight:600; }}
QPushButton:hover {{ background-color:{ACCENT_HOVER}; }}
QPushButton:pressed {{ background-color:#1a6e2c; }}
QPushButton:disabled {{ background-color:#21262d; color:{TEXT_MUTED}; }}
QPushButton#danger {{ background-color:{ACCENT_DANGER}; }}
QPushButton#danger:hover {{ background-color:#f85149; }}
QPushButton#secondary {{ background-color:#21262d;
    border:1px solid {BORDER}; color:{TEXT_PRIMARY}; }}
QPushButton#secondary:hover {{ background-color:#30363d; }}
QListWidget {{ background-color:{PANEL_BG}; border:none; outline:none; padding:4px 0; }}
QListWidget::item {{ padding:10px 14px; border-bottom:1px solid #21262d; color:{TEXT_PRIMARY}; }}
QListWidget::item:selected {{ background-color:#1f3a5f; color:{TEXT_LINK}; border-left:3px solid {TEXT_LINK}; }}
QListWidget::item:hover:!selected {{ background-color:#1c2230; }}
QComboBox {{ background-color:{CARD_BG}; border:1px solid {BORDER};
    border-radius:6px; padding:7px 12px; color:{TEXT_PRIMARY}; min-width:160px; }}
QComboBox::drop-down {{ border:none; width:24px; }}
QComboBox QAbstractItemView {{ background-color:{CARD_BG};
    border:1px solid {BORDER}; color:{TEXT_PRIMARY}; selection-background-color:#1f3a5f; }}
QTextEdit {{ background-color:{CARD_BG}; border:1px solid {BORDER};
    border-radius:6px; padding:10px; color:{TEXT_PRIMARY};
    font-family:'{_FONT_MONO}'; font-size:12px; }}
QScrollBar:vertical {{ background:{PANEL_BG}; width:6px; border-radius:3px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:3px; min-height:20px; }}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
QStatusBar {{ background-color:{PANEL_BG}; border-top:1px solid {BORDER};
    color:{TEXT_MUTED}; font-size:12px; padding:0 8px; }}
QProgressBar {{ background-color:{CARD_BG}; border:1px solid {BORDER}; border-radius:4px; height:4px; }}
QProgressBar::chunk {{ background-color:{TEXT_LINK}; border-radius:4px; }}
QFrame#divider {{ background-color:{BORDER}; max-height:1px; }}
QFrame#video_placeholder {{ background-color:#050a12; border:none; border-bottom:1px solid {BORDER}; }}
QDialog {{ background-color:{PANEL_BG}; }}
"""


def make_divider():
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


class InfoRow(QWidget):
    def __init__(self, label, value):
        super().__init__()
        r = QHBoxLayout(self)
        r.setContentsMargins(0, 2, 0, 2)
        l = QLabel(label)
        l.setStyleSheet(f"color:{TEXT_MUTED};font-size:12px;min-width:140px;")
        v = QLabel(str(value) if value else "—")
        v.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:12px;")
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        r.addWidget(l)
        r.addWidget(v, 1)


# ─────────────────────────── LOGIN PANEL ───────────────────────────


class LoginPanel(QWidget):
    login_requested = pyqtSignal(str, str, str, int, str)

    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background-color:{PANEL_BG};border:1px solid {BORDER};border-radius:12px;}}"
        )
        card.setFixedWidth(440)
        lo = QVBoxLayout(card)
        lo.setContentsMargins(36, 36, 36, 36)
        lo.setSpacing(18)
        row = QHBoxLayout()
        icon = QLabel("📹")
        icon.setStyleSheet("font-size:28px;background:transparent;border:none;")
        title = QLabel("EZVIZ Viewer")
        title.setStyleSheet(
            f"font-size:22px;font-weight:700;color:{TEXT_PRIMARY};background:transparent;border:none;"
        )
        row.addWidget(icon)
        row.addWidget(title)
        row.addStretch()
        lo.addLayout(row)
        sub = QLabel("Подключитесь к вашим камерам")
        sub.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:13px;background:transparent;border:none;"
        )
        lo.addWidget(sub)
        lo.addWidget(make_divider())
        rlbl = QLabel("РЕГИОН")
        rlbl.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{TEXT_MUTED};letter-spacing:0.8px;background:transparent;border:none;"
        )
        lo.addWidget(rlbl)
        self.region_combo = QComboBox()
        for n in REGION_MAP:
            self.region_combo.addItem(n)
        self.region_combo.setCurrentIndex(list(REGION_MAP.keys()).index("Russia"))
        lo.addWidget(self.region_combo)
        for lt, ph, echo in [
            ("EMAIL", "your@email.com", QLineEdit.EchoMode.Normal),
            ("ПАРОЛЬ", "••••••••", QLineEdit.EchoMode.Password),
        ]:
            lbl = QLabel(lt)
            lbl.setStyleSheet(
                f"font-size:11px;font-weight:600;color:{TEXT_MUTED};letter-spacing:0.8px;background:transparent;border:none;"
            )
            lo.addWidget(lbl)
            inp = QLineEdit()
            inp.setPlaceholderText(ph)
            inp.setEchoMode(echo)
            lo.addWidget(inp)
            if lt == "EMAIL":
                self.email_input = inp
            else:
                self.password_input = inp
        self.login_btn = QPushButton("Войти")
        self.login_btn.setFixedHeight(42)
        lo.addWidget(self.login_btn)
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            f"color:{CAM_OFFLINE};font-size:12px;background:transparent;border:none;"
        )
        self.error_lbl.setWordWrap(True)
        self.error_lbl.hide()
        lo.addWidget(self.error_lbl)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lo.addWidget(self.progress)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.login_btn.clicked.connect(self._on_login)
        self.password_input.returnPressed.connect(self._on_login)

    def _on_login(self):
        e = self.email_input.text().strip()
        p = self.password_input.text()
        if not e or not p:
            self._show_error("Введите email и пароль.")
            return
        rname = self.region_combo.currentText()
        domain, rc, sd = REGION_MAP[rname]
        self.login_btn.setEnabled(False)
        self.progress.show()
        self.error_lbl.hide()
        self.login_requested.emit(e, p, domain, rc, sd)

    def _show_error(self, msg):
        self.error_lbl.setText(f"⛔ {msg}")
        self.error_lbl.show()
        self.login_btn.setEnabled(True)
        self.progress.hide()

    def reset(self):
        self.login_btn.setEnabled(True)
        self.progress.hide()


# ─────────────────────────── MAIN WINDOW ───────────────────────────


class CameraListItem(QListWidgetItem):
    def __init__(self, device):
        self.device = device
        s = device.get("deviceSerial", "?")
        n = device.get("deviceName", s)
        c = device.get("deviceCategory", "")
        on = _extract_online_status(device)
        dot = "🟢" if on is True else ("🔴" if on is False else "⚪")
        super().__init__(f"{dot}  {n}\n     {s}  ·  {c}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EZVIZ Camera Viewer")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 780)
        self.client = None
        self.devices = []
        self._stream_worker = None
        self._current_serial = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.stack = QWidget()
        self.stack_lo = QVBoxLayout(self.stack)
        self.stack_lo.setContentsMargins(0, 0, 0, 0)
        self.login_panel = LoginPanel()
        self.login_panel.login_requested.connect(self._do_login)
        app_w = QWidget()
        app_w.hide()
        app_lo = QHBoxLayout(app_w)
        app_lo.setContentsMargins(0, 0, 0, 0)
        app_lo.setSpacing(0)

        # Sidebar
        sb = QFrame()
        sb.setObjectName("sidebar")
        sb.setFixedWidth(280)
        sb_lo = QVBoxLayout(sb)
        sb_lo.setContentsMargins(0, 0, 0, 0)
        sb_lo.setSpacing(0)
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background-color:{PANEL_BG};border-bottom:1px solid {BORDER};"
        )
        hdr.setFixedHeight(64)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hi = QLabel("📹")
        hi.setStyleSheet("font-size:20px;background:transparent;")
        ht = QLabel("EZVIZ Viewer")
        ht.setStyleSheet(
            f"font-size:15px;font-weight:700;color:{TEXT_PRIMARY};background:transparent;"
        )
        hl.addWidget(hi)
        hl.addWidget(ht)
        hl.addStretch()
        sb_lo.addWidget(hdr)
        cr = QWidget()
        cr.setStyleSheet(f"background-color:{PANEL_BG};")
        cr.setFixedHeight(36)
        crl = QHBoxLayout(cr)
        crl.setContentsMargins(16, 0, 16, 0)
        cl = QLabel("КАМЕРЫ")
        cl.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;"
        )
        self.cam_count = QLabel("")
        self.cam_count.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:10px;background:transparent;"
        )
        crl.addWidget(cl)
        crl.addStretch()
        crl.addWidget(self.cam_count)
        sb_lo.addWidget(cr)
        self.cam_list = QListWidget()
        self.cam_list.setSpacing(1)
        self.cam_list.currentItemChanged.connect(self._on_camera_selected)
        sb_lo.addWidget(self.cam_list, 1)
        lr = QWidget()
        lr.setStyleSheet(f"background-color:{PANEL_BG};border-top:1px solid {BORDER};")
        lr.setFixedHeight(56)
        lrl = QHBoxLayout(lr)
        lrl.setContentsMargins(12, 8, 12, 8)
        self.user_lbl = QLabel("")
        self.user_lbl.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:11px;background:transparent;"
        )
        lb = QPushButton("Выйти")
        lb.setObjectName("secondary")
        lb.setFixedWidth(80)
        lb.setFixedHeight(32)
        lb.clicked.connect(self._do_logout)
        lrl.addWidget(self.user_lbl, 1)
        lrl.addWidget(lb)
        sb_lo.addWidget(lr)
        app_lo.addWidget(sb)

        # Content
        ct = QFrame()
        ct.setObjectName("content")
        ct_lo = QVBoxLayout(ct)
        ct_lo.setContentsMargins(0, 0, 0, 0)
        ct_lo.setSpacing(0)
        tb = QWidget()
        tb.setStyleSheet(
            f"background-color:{PANEL_BG};border-bottom:1px solid {BORDER};"
        )
        tb.setFixedHeight(64)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(24, 0, 24, 0)
        self.cam_name_lbl = QLabel("Выберите камеру")
        self.cam_name_lbl.setStyleSheet(
            f"font-size:16px;font-weight:700;color:{TEXT_PRIMARY};background:transparent;"
        )
        self.cam_serial_lbl = QLabel("")
        self.cam_serial_lbl.setStyleSheet(
            f"font-size:12px;color:{TEXT_MUTED};background:transparent;font-family:monospace;"
        )
        self.status_badge = QLabel("")
        self.status_badge.setStyleSheet("background:transparent;")
        self.status_badge.hide()
        self.stream_btn = QPushButton("▶  Облачный поток")
        self.stream_btn.setFixedHeight(36)
        self.stream_btn.setEnabled(False)
        self.stream_btn.clicked.connect(self._start_cloud_stream)
        self.rtsp_btn = QPushButton("🏠  Локальный RTSP")
        self.rtsp_btn.setObjectName("secondary")
        self.rtsp_btn.setFixedHeight(36)
        self.rtsp_btn.setEnabled(False)
        self.rtsp_btn.clicked.connect(self._start_local_rtsp)
        self.stop_btn = QPushButton("⏹  Стоп")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_stream)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        tv.addWidget(self.cam_name_lbl)
        tv.addWidget(self.cam_serial_lbl)
        tbl.addLayout(tv)
        tbl.addStretch()
        tbl.addWidget(self.status_badge)
        tbl.addSpacing(12)
        tbl.addWidget(self.stream_btn)
        tbl.addSpacing(6)
        tbl.addWidget(self.rtsp_btn)
        tbl.addSpacing(6)
        tbl.addWidget(self.stop_btn)
        ct_lo.addWidget(tb)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        vf = QFrame()
        vf.setObjectName("video_placeholder")
        vfl = QVBoxLayout(vf)
        vfl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_hint = QLabel("🎥\n\nВыберите камеру и нажмите «Облачный поток»")
        self.video_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_hint.setStyleSheet(
            f"color:#3d444d;font-size:14px;background:transparent;"
        )
        vfl.addWidget(self.video_hint)
        self.url_lbl = QLabel("")
        self.url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_lbl.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:11px;background:transparent;font-family:monospace;"
        )
        self.url_lbl.setWordWrap(True)
        self.url_lbl.hide()
        vfl.addWidget(self.url_lbl)
        splitter.addWidget(vf)

        iw = QWidget()
        iw.setStyleSheet(f"background-color:{DARK_BG};")
        il = QHBoxLayout(iw)
        il.setContentsMargins(20, 16, 20, 16)
        il.setSpacing(20)
        pg = QGroupBox("Параметры устройства")
        pg.setStyleSheet(
            f"QGroupBox{{background-color:{PANEL_BG};border:1px solid {BORDER};border-radius:8px;margin-top:14px;padding:12px;font-weight:600;color:{TEXT_MUTED};font-size:11px;}}QGroupBox::title{{subcontrol-origin:margin;left:10px;top:-2px;padding:0 4px;background-color:{PANEL_BG};}}"
        )
        self.props_lo = QVBoxLayout(pg)
        self.props_lo.setSpacing(4)
        ph = QLabel("Выберите камеру")
        ph.setStyleSheet(f"color:{TEXT_MUTED};font-size:12px;")
        self.props_lo.addWidget(ph)
        self.props_lo.addStretch()
        lg = QGroupBox("Ответ API / Диагностика")
        lg.setStyleSheet(pg.styleSheet())
        lgl = QVBoxLayout(lg)
        self.json_view = QTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setPlaceholderText("JSON-ответ API появится здесь…")
        lgl.addWidget(self.json_view)
        il.addWidget(pg, 1)
        il.addWidget(lg, 1)
        splitter.addWidget(iw)
        splitter.setSizes([420, 260])
        ct_lo.addWidget(splitter, 1)
        app_lo.addWidget(ct, 1)
        self.stack_lo.addWidget(self.login_panel)
        self.stack_lo.addWidget(app_w)
        self.app_widget = app_w
        root.addWidget(self.stack)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готово")

    def _do_login(self, email, password, domain, region_code, streaming_domain):
        self.status_bar.showMessage(f"Подключение к {domain}…")
        w = LoginWorker(email, password, domain, region_code, streaming_domain)
        w.success.connect(self._on_login_ok)
        w.error.connect(self._on_login_fail)
        w.start()
        self._login_worker = w

    def _on_login_ok(self, client, devices):
        self.client = client
        self.devices = devices
        self.user_lbl.setText(client.email[:28])
        self._populate_cameras(devices)
        self.login_panel.reset()
        self.login_panel.hide()
        self.app_widget.show()
        self.status_bar.showMessage(f"✓ Вошли  |  Устройств: {len(devices)}")

    def _on_login_fail(self, msg):
        self.login_panel._show_error(msg)

    def _do_logout(self):
        self._stop_stream()
        if self.client:
            threading.Thread(target=self.client.logout, daemon=True).start()
            self.client = None
        self.cam_list.clear()
        self.devices = []
        self._current_serial = None
        self.cam_name_lbl.setText("Выберите камеру")
        self.cam_serial_lbl.setText("")
        self.stream_btn.setEnabled(False)
        self.rtsp_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_badge.hide()
        self.json_view.clear()
        self._clear_props()
        self.url_lbl.hide()
        self.video_hint.show()
        self.app_widget.hide()
        self.login_panel.show()

    def _populate_cameras(self, devices):
        self.cam_list.clear()
        for d in devices:
            self.cam_list.addItem(CameraListItem(d))
        self.cam_count.setText(str(len(devices)))

    def _on_camera_selected(self, current, _prev):
        if not isinstance(current, CameraListItem):
            return
        dev = current.device
        serial = dev.get("deviceSerial", "")
        name = dev.get("deviceName", serial)
        self._current_serial = serial
        self.cam_name_lbl.setText(name)
        self.cam_serial_lbl.setText(serial)
        on = _extract_online_status(dev)
        self.status_badge.show()
        if on is True:
            self.status_badge.setText("● Online")
            self.status_badge.setStyleSheet(
                f"background-color:#0d2818;color:{CAM_ONLINE};border:1px solid #1a6e2c;border-radius:10px;padding:3px 12px;font-size:11px;font-weight:600;"
            )
        elif on is False:
            self.status_badge.setText("● Offline")
            self.status_badge.setStyleSheet(
                f"background-color:#2d1117;color:{CAM_OFFLINE};border:1px solid #6e1a1a;border-radius:10px;padding:3px 12px;font-size:11px;font-weight:600;"
            )
        else:
            self.status_badge.setText("● ?")
            self.status_badge.setStyleSheet(
                f"background-color:#21262d;color:{TEXT_MUTED};border:1px solid {BORDER};border-radius:10px;padding:3px 12px;font-size:11px;font-weight:600;"
            )
        self.stream_btn.setEnabled(True)
        self.rtsp_btn.setEnabled(True)
        self.video_hint.show()
        self.url_lbl.hide()
        self._clear_props()
        self.json_view.clear()
        self._show_device_props(dev)
        if self.client:
            w = DeviceInfoWorker(self.client, serial)
            w.done.connect(self._on_device_info)
            w.start()
            self._info_worker = w

    def _clear_props(self):
        while self.props_lo.count():
            it = self.props_lo.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _show_device_props(self, dev):
        self._clear_props()
        on = _extract_online_status(dev)
        ci = _extract_conn(dev)
        fields = [
            ("Серийный номер", dev.get("deviceSerial")),
            ("Название", dev.get("deviceName")),
            ("Категория", dev.get("deviceCategory")),
            ("Модель", dev.get("deviceType", dev.get("model"))),
            ("Версия ПО", dev.get("deviceVersion")),
            (
                "Статус",
                "Онлайн" if on is True else ("Офлайн" if on is False else "Неизвестно"),
            ),
        ]
        if ci:
            fields += [
                ("Локальный IP", ci.get("localIp")),
                ("RTSP порт", str(ci.get("localRtspPort", ""))),
            ]
        for nk in ("CONNECTION", "connection", "STATUS", "SWITCH", "FEATURE", "P2P"):
            n = dev.get(nk)
            if isinstance(n, dict):
                for k, v in n.items():
                    if v is not None and not isinstance(v, (dict, list)):
                        fields.append((f"{nk}.{k}", str(v)))
        for label, val in fields:
            if val and str(val).strip():
                self.props_lo.addWidget(InfoRow(label, str(val)))
        self.props_lo.addStretch()

    def _on_device_info(self, info, relay):
        combined = {}
        if info:
            combined["deviceInfo"] = info
        if relay:
            combined["relayInfo"] = relay
        self.json_view.setPlainText(
            json.dumps(combined, indent=2, ensure_ascii=False, default=str)
        )

    def _start_cloud_stream(self):
        if not self._current_serial or not self.client:
            return
        serial = self._current_serial
        self.status_bar.showMessage("Поиск потокового URL…")
        self._set_streaming_ui(True)

        def fetch():
            # 1. Try direct HLS/FLV stream URL via API
            live = self.client.start_live_stream(serial)
            if live:
                urls = []
                info = live.get("liveStreamInfo", live.get("data", live))

                def find_urls(d):
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if (
                                isinstance(v, str)
                                and v.startswith("http")
                                and len(v) > 15
                            ):
                                urls.append((k, v))
                            elif isinstance(v, dict):
                                find_urls(v)

                find_urls(info)

                if urls:
                    url = urls[0][1]
                    for k, v in urls:
                        if "hls" in k.lower() or "flv" in k.lower():
                            url = v
                            break
                    print(f"[DEBUG] Found direct URL: {url}")
                    QTimer.singleShot(0, lambda: self._play_url(url))
                    return

            # 2. Try getting RTSP URL from stream info
            stream = self.client.get_stream_info(serial)
            if stream:
                for k in ("rtspUrl", "rtsp_url", "streamUrl", "url"):
                    url = stream.get(k)
                    if url and isinstance(url, str) and "rtsp" in url:
                        print(f"[DEBUG] Found RTSP URL: {url}")
                        QTimer.singleShot(0, lambda: self._play_url(url))
                        return

            # 3. If no direct URLs, show helpful dialog instead of broken Relay
            self.status_bar.showMessage("Прямой URL не найден. Формируем RTSP…")
            comp = self.client.compensate_status(serial) or {}
            status_data = comp.get("STATUS", {}).get(serial, {})
            encrypt_pwd = status_data.get("encryptPwd", "")

            # Get device connection info
            dev = next((d for d in self.devices if d.get("deviceSerial") == serial), {})
            conn = dev.get("CONNECTION", dev.get("connection", {}))
            local_ip = conn.get("localIp", "") if isinstance(conn, dict) else ""
            rtsp_port = (
                conn.get("localRtspPort", 554) if isinstance(conn, dict) else 554
            )
            wan_ip = ""
            if status_data.get("optionals"):
                wan_ip = status_data["optionals"].get("wanIp", "")

            # Build RTSP URLs
            rtsp_urls = []
            if encrypt_pwd:
                if local_ip:
                    rtsp_urls.append(
                        f"rtsp://admin:{encrypt_pwd}@{local_ip}:{rtsp_port}/Streaming/Channels/101"
                    )
                if wan_ip and wan_ip != local_ip:
                    rtsp_urls.append(
                        f"rtsp://admin:{encrypt_pwd}@{wan_ip}:{rtsp_port}/Streaming/Channels/101"
                    )

            msg = "Прямой HLS/FLV поток недоступен через API.\n\n"
            if rtsp_urls:
                msg += "📺 Попробуйте открыть RTSP в VLC или ffplay:\n\n"
                for u in rtsp_urls:
                    msg += f"{u}\n\n"
                msg += "💡 Пароль для RTSP — это encryptPwd из настроек камеры."
            else:
                msg += "Не удалось автоматически сформировать RTSP URL.\n"
                msg += "Используйте «Локальный RTSP» и введите код верификации вручную."

            QTimer.singleShot(0, lambda: QMessageBox.information(self, "Поток", msg))
            QTimer.singleShot(0, lambda: self._set_streaming_ui(False))

        threading.Thread(target=fetch, daemon=True).start()

    def _play_url(self, url):
        self._stop_stream()
        self.video_hint.hide()
        self.url_lbl.setText(f"📡 {url[:80]}")
        self.url_lbl.show()

        is_rtsp = url.startswith("rtsp://")
        is_hls = ".m3u8" in url

        cmd = ["ffplay"]
        if is_rtsp:
            cmd += ["-rtsp_transport", "tcp"]
        elif is_hls:
            cmd += ["-allowed_extensions", "ALL"]
        else:
            cmd += ["-f", "flv"]

        cmd += [
            "-probesize",
            "32768",
            "-analyzeduration",
            "500000",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-window_title",
            f"EZVIZ – {self._current_serial}",
            "-x",
            "960",
            "-y",
            "540",
            url,
        ]

        print(f"[DEBUG] Running: {' '.join(cmd[:6])}... {url}")
        try:
            self._stream_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            self._set_streaming_ui(True)
        except FileNotFoundError:
            QMessageBox.warning(self, "Ошибка", "ffplay не найден. Установите FFmpeg.")
            self._set_streaming_ui(False)

    def _play_url(self, url):
        self._stop_stream()
        self.video_hint.hide()
        self.url_lbl.setText(f"📡 {url[:80]}")
        self.url_lbl.show()
        is_hls = ".m3u8" in url
        cmd = ["ffplay"]
        if is_hls:
            cmd += ["-allowed_extensions", "ALL"]
        else:
            cmd += ["-f", "flv"]
        cmd += [
            "-probesize",
            "32768",
            "-analyzeduration",
            "500000",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-window_title",
            f"EZVIZ – {self._current_serial}",
            "-x",
            "960",
            "-y",
            "540",
            url,
        ]
        try:
            self._stream_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
            self._set_streaming_ui(True)
        except FileNotFoundError:
            QMessageBox.warning(self, "Ошибка", "ffplay не найден.")
            self._set_streaming_ui(False)

    def _start_local_rtsp(self):
        if not self._current_serial or not self.client:
            return
        dev = next(
            (d for d in self.devices if d.get("deviceSerial") == self._current_serial),
            {},
        )
        ci = _extract_conn(dev)
        ip = ci.get("localIp", "")
        port = ci.get("localRtspPort", 554)
        if not ip:
            QMessageBox.information(
                self,
                "RTSP",
                "Локальный IP неизвестен.\n\nВведите RTSP вручную в VLC:\nrtsp://admin:КОД@IP:554/Streaming/Channels/101",
            )
            return
        dlg = VerifyCodeDialog(
            dev.get("deviceName", self._current_serial),
            self._current_serial,
            ip,
            port,
            self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.verify_code:
            self._stop_stream()
            urls = dlg.get_rtsp_urls()
            self.video_hint.hide()
            self.url_lbl.setText(f"📡 {urls[0]}")
            self.url_lbl.show()
            self._stream_worker = RtspStreamWorker(urls[0], self._current_serial)
            self._stream_worker.status_update.connect(self.status_bar.showMessage)
            self._stream_worker.stream_error.connect(self._on_stream_error)
            self._stream_worker.start()
            self._set_streaming_ui(True)

    def _set_streaming_ui(self, streaming):
        if streaming:
            self.stream_btn.setEnabled(False)
            self.rtsp_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.stream_btn.setEnabled(bool(self._current_serial))
            self.rtsp_btn.setEnabled(bool(self._current_serial))
            self.stop_btn.setEnabled(False)

    def _stop_stream(self):
        if self._stream_worker and self._stream_worker.isRunning():
            self._stream_worker.stop()
            self._stream_worker.wait(3000)
        self._stream_worker = None
        self._set_streaming_ui(False)
        self.status_bar.showMessage("Поток остановлен")

    def _on_stream_error(self, msg):
        self._set_streaming_ui(False)
        self.video_hint.show()
        self.url_lbl.hide()
        QMessageBox.warning(self, "Ошибка потока", msg)

    def closeEvent(self, event):
        self._stop_stream()
        if self.client:
            threading.Thread(target=self.client.logout, daemon=True).start()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EZVIZ Viewer")
    app.setStyleSheet(STYLE)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
