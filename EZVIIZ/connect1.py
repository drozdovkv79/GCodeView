import hashlib
import secrets
import time
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple

import requests

# Константы из нового кода
EZVIZ_CLIENT_TYPE = "1"
EZVIZ_USER_AGENT = "EZVIZ/4.9.2 (iPhone; iOS 14.3; Scale/3.00)"
EZVIZ_BASE_API_URL = "https://api.ezvizlife.com"
EZVIZ_DOMAINS_ENDPOINT = "/api/area/domain"
EZVIZ_AUTH_ENDPOINT = "/v3/users/login/v5"
EZVIZ_DEVICES_ENDPOINT = "/v3/userdevices/v1/resources/pagelist"
EZVIZ_SWITCH_STATUS_ENDPOINT = "/api/device/switchStatus"
EZVIZ_DEFENCE_MODE_ENDPOINT = "/v3/userdevices/v1/group/switchDefenceMode"
EZVIZ_DEFENCE_MODE_GET_ENDPOINT = "/v3/userdevices/v1/group/defenceMode"
API_ENDPOINT_REFRESH = "/v3/apigateway/login"
RUSSIA_AREA_ID = 114
RUSSIA_DOMAIN = "apiirus.ezvizru.com"
DEFAULT_GROUP_ID = -1


class DefenceMode(IntEnum):
    """Режимы охраны"""

    SLEEP = 0  # Снят
    ARM_HOME = 1  # Домашний режим
    ARM_AWAY = 2  # Ночной/Вне дома
    UNSET_MODE = -1


class EzvizAPI:
    def __init__(self, email: str, password: str, area_id: int = 0, log=None):
        """
        Инициализация клиента Ezviz API

        Args:
            email: Логин (email)
            password: Пароль
            area_id: ID региона (0 - автоопределение, 114 - Россия)
            log: Функция логирования (опционально)
        """
        self.email = email
        self.password = password
        self.area_id = area_id
        self.session_id = None
        self.rf_session_id = None
        self.feature_code = None
        self.cu_name = None
        self.domain = None
        self.log = log or print

        # Хэши для аутентификации
        self.email_hash = hashlib.md5(email.encode()).hexdigest()
        self.pass_hash = hashlib.md5(password.encode()).hexdigest()

        # Получаем домен для региона
        self._setup_domain()

    def _log(self, level: str, message: str):
        """Внутреннее логирование"""
        self.log(f"[{level}] {message}")

    def _random_str(self, length: int = 24) -> str:
        """Генерация случайной строки"""
        random_str = secrets.token_urlsafe(length)[:length]
        return random_str.replace("-", "0").replace("_", "0")

    def _setup_domain(self):
        """Определение домена на основе региона"""
        # Если указана Россия
        if self.area_id == RUSSIA_AREA_ID:
            self.domain = f"https://{RUSSIA_DOMAIN}"
            self._log("INFO", f"Использую российский домен: {self.domain}")
            return

        # Если регион не указан или нужно автоопределение
        if self.area_id == 0:
            # Пробуем получить домен автоматически
            try:
                self.domain = self._get_domain_by_area()
                self._log("INFO", f"Автоопределение региона: {self.domain}")
                return
            except Exception as e:
                self._log("WARNING", f"Не удалось определить регион: {e}")

        # Домен по умолчанию
        self.domain = EZVIZ_BASE_API_URL
        self._log("INFO", f"Использую домен по умолчанию: {self.domain}")

    def _get_domain_by_area(self, area_id: int = 1) -> str:
        """
        Получение домена для указанного региона
        Обычно area_id = 1 для международного API
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "clientType": EZVIZ_CLIENT_TYPE,
            "User-Agent": EZVIZ_USER_AGENT,
        }

        data = {"areaId": area_id}

        try:
            response = requests.post(
                f"{EZVIZ_BASE_API_URL}{EZVIZ_DOMAINS_ENDPOINT}",
                headers=headers,
                data=data,
            )
            result = response.json()

            if "domain" in result:
                return f"https://{result['domain']}"
            else:
                raise Exception("Invalid domain response")
        except Exception as e:
            self._log("ERROR", f"Ошибка получения домена: {e}")
            raise

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        use_session: bool = True,
        retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Универсальный метод для отправки запросов с поддержкой обновления сессии

        Args:
            endpoint: API эндпоинт
            method: HTTP метод (GET, POST, PUT)
            data: Данные для отправки (для POST/PUT)
            use_session: Использовать ли session_id в заголовках
            retries: Количество попыток при 401 ошибке
        """
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

            response_data = response.json()

            # Проверка на 401 Unauthorized (сессия истекла)
            if response.status_code == 401 and retries > 0:
                self._log("WARNING", "Сессия истекла, обновляем...")
                self._refresh_session()
                return self._make_request(
                    endpoint, method, data, use_session, retries - 1
                )

            return response_data

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
        """Обновление сессии с использованием refresh_token"""
        if not self.rf_session_id or not self.cu_name or not self.feature_code:
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
                self._log("INFO", "Сессия успешно обновлена")
                return True
            else:
                self._log("ERROR", "Не удалось обновить сессию")
                return False

        except Exception as e:
            self._log("ERROR", f"Ошибка обновления сессии: {e}")
            return False

    def list_devices(self) -> Optional[Dict[str, Any]]:
        """Получение списка устройств"""
        if not self.session_id and not self.authenticate():
            self._log("ERROR", "Не удалось аутентифицироваться")
            return None

        params = {
            "filter": "CONNECTION,SWITCH,STATUS,NODISTURB,P2P,FEATURE,DETECTOR",
            "groupId": DEFAULT_GROUP_ID,
            "limit": 30,
            "offset": 0,
        }

        try:
            response = self._make_request(EZVIZ_DEVICES_ENDPOINT, "GET", data=params)
            return response
        except Exception as e:
            self._log("ERROR", f"Ошибка получения устройств: {e}")
            return None

    def get_defence_mode(self, group_id: int = DEFAULT_GROUP_ID) -> DefenceMode:
        """Получение текущего режима охраны"""
        if not self.session_id and not self.authenticate():
            self._log("ERROR", "Не удалось аутентифицироваться")
            return DefenceMode.UNSET_MODE

        params = {"groupId": group_id}

        try:
            response = self._make_request(
                EZVIZ_DEFENCE_MODE_GET_ENDPOINT, "GET", data=params
            )

            # Извлечение режима из ответа
            mode = (
                response.get("mode")
                or response.get("defenceMode")
                or response.get("data", {}).get("mode")
            )

            if mode is not None:
                mode_int = int(mode) if isinstance(mode, str) else mode
                return DefenceMode(mode_int)
            else:
                return DefenceMode.UNSET_MODE

        except Exception as e:
            self._log("ERROR", f"Ошибка получения режима охраны: {e}")
            return DefenceMode.UNSET_MODE


# ============== ПРИМЕР ИСПОЛЬЗОВАНИЯ ==============
if __name__ == "__main__":
    # Ваши данные
    LOGIN = "drozdovkv79@yandex.ru"
    PASSWORD = "Luxor!2345"

    # Вариант 1: Автоопределение региона
    print("=== Вариант 1: Автоопределение региона ===")
    client1 = EzvizAPI(LOGIN, PASSWORD, area_id=0)

    if client1.authenticate():
        devices = client1.list_devices()
        if devices:
            print("\nСписок устройств:")
            device_list = devices.get("deviceInfos", [])
            for device in device_list:
                print(
                    f"  - {device.get('deviceName')} (SN: {device.get('deviceSerial')})"
                )

    # Вариант 2: Принудительно Россия
    print("\n=== Вариант 2: Российский регион ===")
    client2 = EzvizAPI(LOGIN, PASSWORD, area_id=RUSSIA_AREA_ID)

    if client2.authenticate():
        # Получаем устройства
        devices = client2.list_devices()
        if devices:
            print("\nСписок устройств (Россия):")
            device_list = devices.get("deviceInfos", [])
            for device in device_list:
                status = "Онлайн" if device.get("status") == 1 else "Оффлайн"
                print(f"  - {device.get('deviceName')} [{status}]")

        # Получаем режим охраны
        mode = client2.get_defence_mode()
        print(f"\nРежим охраны: {mode.name}")
