from pyezvizapi import EzvizClient

# Авторизация (токен сохранится в файл)
client = EzvizClient(account="drozdovkv79@yandex.ru", password="Luxor!2345", url="ru")

# Запуск прокси для просмотра видео через VLC/FFplay
client.start_stream_proxy(
    serial="BB1486658",
    channel_no=1,
    decrypt_video=True,  # Расшифровка видео с батарейных камер
    listen_port=8558,
)
