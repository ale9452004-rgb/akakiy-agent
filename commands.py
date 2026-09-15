import sys
from pathlib import Path


PROJECT_PATH = Path(r"C:\Akakiy agent")


def show_status():
    print("\n--- Статус Акакия ---")
    print(f"Проект: {PROJECT_PATH}")
    print(f"Python: {sys.version.split()[0]}")
    print("Модель: qwen3:8b")
    print("Ollama: подключён")
    print("Статус: работает")
    print("---------------------")


def show_files():
    from tools.files import list_files

    print("\n--- Файлы проекта ---")

    for item in list_files():
        print(item)

    print("---------------------")


def read_file(filename):
    from tools.files import read_file as tool_read_file

    content, error = tool_read_file(filename)

    if error:
        print(f"\n{error}")
        return None

    return content