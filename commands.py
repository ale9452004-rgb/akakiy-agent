import sys
from pathlib import Path
import requests


from config import PROJECT_PATH


def show_status():
    print("\n--- Статус Акакия ---")
    print(f"Проект: {PROJECT_PATH}")
    print(f"Python: {sys.version.split()[0]}")
    print("Модель: qwen3:8b")

    ollama_status = "недоступен"
    system_status = "ошибка (нет связи с Ollama)"

    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = [m.get("name", "") for m in response.json().get("models", [])]
            if any("qwen3:8b" in m for m in models):
                ollama_status = "подключён"
                system_status = "работает"
            else:
                ollama_status = "подключён (модель qwen3:8b не найдена)"
                system_status = "требуется загрузка модели"
        else:
            ollama_status = f"ошибка (HTTP {response.status_code})"
            system_status = "сервис недоступен"
    except requests.RequestException:
        ollama_status = "недоступен (сервер не запущен)"
        system_status = "ошибка (нет связи с Ollama)"

    print(f"Ollama: {ollama_status}")
    print(f"Статус: {system_status}")
    print("---------------------")


def show_help():
    print("\n--- Справка по командам Акакия ---")
    print("Быстрые команды CLI:")
    print("  статус                   - показать статус системы")
    print("  помощь                   - показать эту справку")
    print("  выход                    - завершить работу")
    print("\nРабота с планами:")
    print("  план: <задача>           - составить план выполнения задачи")
    print("  покажи план              - показать текущий план")
    print("  выполни план             - запустить текущий план на выполнение")
    print("  очисти план              - сбросить текущий план")
    print("\nЗапросы к инструментам:")
    print("  покажи список файлов     - список всех файлов проекта")
    print("  найди файл <имя>         - найти файл по имени в проекте")
    print("  найди функцию <имя>      - найти определение функции в кодовой базе")
    print("  поиск по проекту <текст> - найти текст в файлах проекта")
    print("----------------------------------")


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