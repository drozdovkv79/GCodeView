import os

from llama_cpp import Llama

# Путь к файлу модели GGUF
model_path = (
    "/Users/drozdovkv/Downloads/gemma-4-E4B-it-ultra-uncensored-heretic-Q6_K.gguf"
)

if not os.path.exists(model_path):
    print(f"Ошибка: модель не найдена по пути: {model_path}")
    exit()

print("Загрузка модели...")
llm = Llama(
    model_path=model_path,
    n_gpu_layers=-1,  # Выгрузить все слои на GPU (если доступно)
    n_ctx=4096,  # Длина контекста (можно увеличить для более длинных запросов)
    verbose=True,
)

print("Модель загружена.")

# Тест генерации текста
prompt = """
<start_of_turn>user Что ты умеешь? что в тебе такого что ты такая заибись? <end_of_turn>
<start_of_turn>model
"""
output = llm(
    prompt, max_tokens=256, stop=["<end_of_turn>"], temperature=0.7, echo=False
)
try:
    text = output["choices"][0]["text"].strip()
except (KeyError, IndexError):
    # Обработка ошибки, если ключ или индекс недоступны
    text = ""
print("Сгенерированный текст:")
print(text)
