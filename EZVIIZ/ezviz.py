import hashlib
import json
import secrets
from enum import IntEnum
from typing import Any, Dict, List, Optional

import requests

# Константы
EZVIZ_CLIENT_TYPE = "1"
EZVIZ_USER_AGENT = "EZVIZ/4.9.2 (iPhone; iOS 14.3; Scale/3.00)"
EZVIZ_BASE_API_URL = "https://api.ezvizlife.com"
EZVIZ_DOMAINS_ENDPOINT = "/api/area/domain"
EZVIZ_AUTH_ENDPOINT = "/v3/users/login/v5"
EZVIZ_DEVICES_ENDPOINT = "/v3/userdevices/v1/resources/pagelist"
API_ENDPOINT_REFRESH = "/v3/apigateway/login"
RUSSIA_AREA_ID = 114
RUSSIA_DOMAIN = "apiirus.ezvizru.com"
DEFAULT_GROUP_ID = -1


class DefenceMode(IntEnum):
    SLEEP = 0
    ARM_HOME = 1
    ARM_AWAY = 2
    UNSET_MODE = -1


class EzvizAPI:
    def __init__(self, email: str, password: str, area_id: int = 0, log=None):
        self.email = email
        self.password = password
        self.area_id = area_id
        self.session_id = None
        self.rf_session_id = None
        self.feature_code = None
        self.cu_name = None
        self.domain = None
        self.log = log or print

        self.email_hash = hashlib.md5(email.encode()).hexdigest()
        self.pass_hash = hashlib.md5(password.encode()).hexdigest()
        self._setup_domain()

    def _log(self, level: str, message: str):
        self.log(f"[{level}] {message}")

    def _random_str(self, length: int = 24) -> str:
        random_str = secrets.token_urlsafe(length)[:length]
        return random_str.replace("-", "0").replace("_", "0")

    def _setup_domain(self):
        if self.area_id == RUSSIA_AREA_ID:
            self.domain = f"https://{RUSSIA_DOMAIN}"
            self._log("INFO", f"Использую российский домен: {self.domain}")
            return

        if self.area_id == 0:
            try:
                self.domain = self._get_domain_by_area()
                self._log("INFO", f"Автоопределение региона: {self.domain}")
                return
            except Exception as e:
                self._log("WARNING", f"Не удалось определить регион: {e}")

        self.domain = EZVIZ_BASE_API_URL
        self._log("INFO", f"Использую домен по умолчанию: {self.domain}")

    def _get_domain_by_area(self, area_id: int = 1) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "clientType": EZVIZ_CLIENT_TYPE,
            "User-Agent": EZVIZ_USER_AGENT,
        }
        data = {"areaId": area_id}

        response = requests.post(
            f"{EZVIZ_BASE_API_URL}{EZVIZ_DOMAINS_ENDPOINT}", headers=headers, data=data
        )
        result = response.json()

        if "domain" in result:
            return f"https://{result['domain']}"
        raise Exception("Invalid domain response")

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        use_session: bool = True,
        retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{self.domain}{endpoint}"
        headers = {
            "User-Agent": EZVIZ_USER_AGENT,
            "clientType": EZVIZ_CLIENT_TYPE,
        }

        if method in ["POST", "PUT"]:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        if use_session and self.session_id:
            headers["sessionId"] = self.session_id

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=data)
            else:
                response = (
                    requests.post(url, headers=headers, data=data)
                    if method == "POST"
                    else requests.put(url, headers=headers, data=data)
                )

            if response.status_code == 401 and retries > 0:
                self._log("WARNING", "Сессия истекла, обновляем...")
                self._refresh_session()
                return self._make_request(
                    endpoint, method, data, use_session, retries - 1
                )

            return response.json()
        except Exception as e:
            self._log("ERROR", f"Ошибка запроса: {e}")
            raise

    def authenticate(self) -> bool:
        """Аутентификация и получение сессии"""
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "clienttype": EZVIZ_CLIENT_TYPE,
            "user-agent": EZVIZ_USER_AGENT,
        }

        data = {
            "account": self.email,
            "featureCode": self.email_hash,
            "password": self.pass_hash,
        }

        try:
            response = requests.post(
                f"{self.domain}{EZVIZ_AUTH_ENDPOINT}", headers=headers, data=data
            )
            auth = response.json()

            # Проверка ошибок
            if auth.get("retcode"):
                self._log("ERROR", f"Ошибка входа: {auth['retcode']}")
                return False

            if auth.get("meta", {}).get("code") == 6002:
                self._log("ERROR", "Двухфакторная аутентификация не поддерживается")
                return False

            if auth.get("meta", {}).get("code") != 200:
                self._log("ERROR", f"Ошибка входа: {auth.get('meta', {}).get('code')}")
                return False

            # Получение данных сессии
            login_session = auth.get("loginSession", {})
            session_id = login_session.get("sessionId")
            rf_session_id = login_session.get("refreshSessionId")

            if session_id:
                self.session_id = session_id
                self.rf_session_id = rf_session_id
                self.feature_code = self.email_hash
                self.cu_name = self._random_str(24)

                self._log(
                    "INFO", f"Аутентификация успешна. Session ID: {session_id[:10]}..."
                )
                return True
            else:
                self._log("ERROR", "Session ID не найден в ответе")
                return False

        except Exception as e:
            self._log("ERROR", f"Ошибка аутентификации: {e}")
            return False

    def _refresh_session(self) -> bool:
        if not all([self.rf_session_id, self.cu_name, self.feature_code]):
            self._log("ERROR", "Недостаточно данных для обновления сессии")
            return False

        query = {
            "cuName": self.cu_name,
            "featureCode": self.feature_code,
            "refreshSessionId": self.rf_session_id,
        }

        try:
            refresh_data = self._make_request(
                API_ENDPOINT_REFRESH, "PUT", data=query, use_session=False
            )

            session_info = refresh_data.get("sessionInfo", {})
            new_session_id = session_info.get("sessionId")
            new_rf_session_id = session_info.get("refreshSessionId")

            if new_session_id:
                self.session_id = new_session_id
                self.rf_session_id = new_rf_session_id
                self._log("INFO", "Сессия обновлена")
                return True
            return False
        except Exception as e:
            self._log("ERROR", f"Ошибка обновления сессии: {e}")
            return False

    def list_devices(self) -> Optional[Dict[str, Any]]:
        """Получение полного списка устройств со всей информацией"""
        if not self.session_id and not self.authenticate():
            self._log("ERROR", "Не удалось аутентифицироваться")
            return None

        params = {
            "filter": "CONNECTION,SWITCH,STATUS,NODISTURB,P2P,FEATURE,DETECTOR",
            "groupId": DEFAULT_GROUP_ID,
            "limit": 100,  # Увеличил лимит
            "offset": 0,
        }

        try:
            response = self._make_request(EZVIZ_DEVICES_ENDPOINT, "GET", data=params)
            return response
        except Exception as e:
            self._log("ERROR", f"Ошибка получения устройств: {e}")
            return None

    def get_devices_info(self) -> List[Dict[str, Any]]:
        """Получение расширенной информации об устройствах"""
        response = self.list_devices()
        if not response:
            return []

        devices_info = []

        # Получаем словари с дополнительными данными
        switches = response.get("SWITCH", {})
        statuses = response.get("STATUS", {})
        connections = response.get("CONNECTION", {})
        p2p_data = response.get("P2P", {})
        resource_infos = response.get("resourceInfos", [])

        # Основная информация об устройствах
        for device in response.get("deviceInfos", []):
            serial = device.get("deviceSerial")

            # Ищем имя устройства в resourceInfos
            resource_name = None
            for resource in resource_infos:
                if resource.get("deviceSerial") == serial:
                    resource_name = resource.get("resourceName")
                    break

            # Имя из deviceInfos или из resourceInfos
            device_name = (
                device.get("name")
                or resource_name
                or device.get("deviceName")
                or "Без имени"
            )

            device_info = {
                "serial": serial,
                "name": device_name,
                "type": device.get("deviceType"),
                "category": device.get("deviceCategory"),
                "sub_category": device.get("deviceSubCategory"),
                "status": device.get("status"),
                "status_text": "Онлайн" if device.get("status") == 1 else "Оффлайн",
                "version": device.get("version"),
                "mac": device.get("mac"),
                "channel_number": device.get("channelNumber", 1),
                "is_hik": device.get("hik", False),
                "support_ext": device.get("supportExt"),
                "user_name": device.get("userName"),
                "offline_time": device.get("offlineTime"),
                "connection": connections.get(serial, {}),
                "status_details": statuses.get(serial, {}),
                "p2p": p2p_data.get(serial, []),
                "switches": [],
                "stream_url": None,
            }

            # Обработка переключателей (алерт, звук и т.д.)
            if serial in switches:
                for switch in switches[serial]:
                    switch_type = switch.get("type")
                    switch_enable = switch.get("enable")

                    switch_name = {
                        1: "Основной выключатель",
                        2: "Инфракрасная подсветка",
                        3: "Сигнализация движения",
                        4: "Звуковой сигнал",
                        5: "Поворот/Наклон",
                        6: "Световой сигнал",
                        7: "Умное обнаружение",
                        8: "Уведомления",
                        9: "Запись",
                        10: "Голосовой вызов",
                    }.get(switch_type, f"Переключатель {switch_type}")

                    device_info["switches"].append(
                        {
                            "type": switch_type,
                            "name": switch_name,
                            "enable": switch_enable,
                            "enable_text": "Включён" if switch_enable else "Выключен",
                        }
                    )

            # Получаем RTSP URL из P2P данных
            if serial in p2p_data and p2p_data[serial]:
                p2p = p2p_data[serial][0]
                ip = p2p.get("ip")
                port = p2p.get("port")
                if ip and port:
                    device_info["stream_url"] = f"rtsp://{ip}:{port}/live"

            # Извлекаем локальный RTSP порт из connection
            if serial in connections:
                conn = connections[serial]
                local_rtsp = conn.get("localRtspPort")
                local_ip = conn.get("localIp")
                if local_ip and local_rtsp:
                    device_info["local_rtsp_url"] = (
                        f"rtsp://{local_ip}:{local_rtsp}/live"
                    )

            devices_info.append(device_info)

        return devices_info

    def print_devices_full_info(self):
        """Красивый вывод полной информации об устройствах"""
        devices = self.get_devices_info()

        if not devices:
            print("Устройства не найдены")
            return

        print(f"\n{'=' * 80}")
        print(f"НАЙДЕНО УСТРОЙСТВ: {len(devices)}")
        print(f"{'=' * 80}\n")

        for idx, device in enumerate(devices, 1):
            print(f"{idx}. 📷 {device['name']}")
            print(f"   ├─ Серийный номер: {device['serial']}")
            print(f"   ├─ Тип: {device['type']}")
            print(f"   ├─ Категория: {device['category']} / {device['sub_category']}")
            print(f"   ├─ Статус: {device['status_text']}")
            print(f"   ├─ Каналов: {device['channel_number']}")
            print(f"   ├─ MAC-адрес: {device['mac']}")
            print(f"   ├─ Версия прошивки: {device['version']}")

            # RTSP потоки
            if device.get("local_rtsp_url"):
                print(f"   ├─ Локальный RTSP: {device['local_rtsp_url']}")
            if device.get("stream_url"):
                print(f"   ├─ P2P RTSP: {device['stream_url']}")

            # Переключатели
            if device["switches"]:
                print(f"   └─ Переключатели:")
                for switch in device["switches"]:
                    icon = "✅" if switch["enable"] else "❌"
                    print(f"       {icon} {switch['name']}: {switch['enable_text']}")

            print()

        # Детальный вывод сырых данных (опционально)
        print(f"\n{'=' * 80}")
        print("СЫРЫЕ ДАННЫЕ (JSON):")
        print(f"{'=' * 80}")
        raw_data = self.list_devices()
        if raw_data:
            # Убираем большие массивы для читаемости
            if "CONNECTION" in raw_data:
                print(f"CONNECTION: {len(raw_data['CONNECTION'])} устройств")
            if "SWITCH" in raw_data:
                print(f"SWITCH: {len(raw_data['SWITCH'])} устройств")
            if "STATUS" in raw_data:
                print(f"STATUS: {len(raw_data['STATUS'])} устройств")
            # Печатаем deviceInfos подробно
            print("\nDEVICE INFOS:")
            for device in raw_data.get("deviceInfos", []):
                print(json.dumps(device, indent=2, ensure_ascii=False))
                print("-" * 40)


# ============== ИСПОЛЬЗОВАНИЕ ==============
if __name__ == "__main__":
    LOGIN = "drozdovkv79@yandex.ru"
    PASSWORD = "Luxor!2345"

    # Подключение к российскому региону
    client = EzvizAPI(LOGIN, PASSWORD, area_id=RUSSIA_AREA_ID)  #

    # Получаем и выводим полную информацию
    client.print_devices_full_info()

    # Или программно получить список устройств
    devices = client.get_devices_info()
    for device in devices:
        print(
            f"Имя: {device['name']}, Серийник: {device['serial']}, Статус: {device['status_text']}"
        )
