"""
Скрипт живой (live) проверки работы household skill через реальную модель qwen3:8b.
"""

import sys
import tempfile
from pathlib import Path

# Обеспечиваем корректный вывод UTF-8 в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.agent import Agent
from tools.household import HouseholdManager, get_household_manager, reset_household_manager
from tools.context import ContextManager
from tools.memory import MemoryManager
from ollama_client import OllamaClient


def run_live_checks():
    print("=== LIVE CHECK: Household Assistant 1.0 с qwen3:8b ===")

    temp_dir = tempfile.TemporaryDirectory()
    storage_path = Path(temp_dir.name) / "live_household.json"

    reset_household_manager()
    hm = get_household_manager(storage_path=storage_path)

    mem = MemoryManager(storage_path=Path(temp_dir.name) / "live_memory.json")
    ctx = ContextManager(memory_manager=mem)
    ai = OllamaClient()

    agent = Agent(memory_manager=mem, context_manager=ctx, ai_client=ai)

    # 1. Создание задачи
    q1 = "Добавь задачу купить кофе"
    print(f"\n[Запрос 1]: {q1}")
    resp1 = agent.process(q1)
    print(f"[Ответ 1]: type={resp1.get('type')}, answer={resp1.get('answer') or resp1.get('result')}")
    print(f"Tasks in storage: {hm.tasks}")

    # 2. Создание заметки
    q2 = "Создай заметку Рецепт с текстом мука 200г, молоко 100мл"
    print(f"\n[Запрос 2]: {q2}")
    resp2 = agent.process(q2)
    print(f"[Ответ 2]: type={resp2.get('type')}, answer={resp2.get('answer') or resp2.get('result')}")
    print(f"Notes in storage: {hm.notes}")

    # 3. Добавление в список
    q3 = "Добавь в список покупок яблоки"
    print(f"\n[Запрос 3]: {q3}")
    resp3 = agent.process(q3)
    print(f"[Ответ 3]: type={resp3.get('type')}, answer={resp3.get('answer') or resp3.get('result')}")
    print(f"Lists in storage: {hm.lists}")

    # 4. Напоминание
    q4 = "Напомни мне позвонить коллеге в 19:00"
    print(f"\n[Запрос 4]: {q4}")
    resp4 = agent.process(q4)
    print(f"[Ответ 4]: type={resp4.get('type')}, answer={resp4.get('answer') or resp4.get('result')}")
    print(f"Reminders in storage: {hm.reminders}")

    reset_household_manager()
    temp_dir.cleanup()
    print("\n=== LIVE CHECK ЗАВЕРШЁН УСПЕШНО ===")


if __name__ == "__main__":
    run_live_checks()
