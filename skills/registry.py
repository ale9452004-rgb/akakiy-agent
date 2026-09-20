"""
Реестр навыков (SkillRegistry) Акакия.

Обеспечивает:
- потокобезопасную регистрацию, удаление и поиск навыков;
- включение и отключение навыков без изменения ядра Agent;
- валидацию соответствия инструментов навыка реестру tools.registry.TOOLS;
- детерминированный выбор подходящего навыка для запроса пользователя;
- загрузку встроенных навыков (project, memory) и синглтон-доступ.
"""

import threading
from typing import Dict, List, Optional

from tools.registry import TOOLS
from skills.base import BaseSkill


class SkillRegistry:
    """
    Потокобезопасный реестр навыков Акакия.
    """

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}
        self._lock = threading.RLock()

    def register(self, skill: BaseSkill) -> None:
        """
        Регистрирует навык в системе.

        Проверяет:
        - тип BaseSkill;
        - непустое уникальное имя;
        - наличие каждого заявленного инструмента в tools.registry.TOOLS.
        """
        if not isinstance(skill, BaseSkill):
            raise TypeError(f"Ожидается экземпляр BaseSkill, получен {type(skill)}")

        name = getattr(skill, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Навык обязан иметь непустое строковое имя (name).")

        name = name.strip()

        with self._lock:
            # Проверяем инструменты против существующего реестра TOOLS
            for tool_name in skill.tools:
                if tool_name not in TOOLS:
                    raise ValueError(
                        f"Навык '{name}' объявляет неизвестный инструмент '{tool_name}'. "
                        f"Инструмент должен быть предварительно зарегистрирован в tools.registry.TOOLS."
                    )

            self._skills[name] = skill

    def unregister(self, name: str) -> Optional[BaseSkill]:
        """
        Удаляет навык из реестра по имени.
        """
        with self._lock:
            return self._skills.pop(name, None)

    def get(self, name: str) -> Optional[BaseSkill]:
        """
        Возвращает навык по имени или None.
        """
        with self._lock:
            return self._skills.get(name)

    def enable(self, name: str) -> bool:
        """
        Включает навык.
        """
        with self._lock:
            skill = self._skills.get(name)
            if skill is not None:
                skill.enabled = True
                return True
            return False

    def disable(self, name: str) -> bool:
        """
        Отключает навык (без удаления из реестра и без изменения ядра Agent).
        """
        with self._lock:
            skill = self._skills.get(name)
            if skill is not None:
                skill.enabled = False
                return True
            return False

    def get_all(self, enabled_only: bool = True) -> List[BaseSkill]:
        """
        Возвращает список зарегистрированных навыков.
        """
        with self._lock:
            if enabled_only:
                return [s for s in self._skills.values() if s.enabled]
            return list(self._skills.values())

    def find_matching_skill(self, user_input: str) -> Optional[BaseSkill]:
        """
        Ищет первый активный навык, детерминированно подходящий под запрос пользователя.
        Если ни один навык не подошёл, возвращает None (запрос направляется в общий Native Tool Calling).
        """
        if not user_input or not str(user_input).strip():
            return None

        clean_input = str(user_input).strip()

        with self._lock:
            for skill in self._skills.values():
                if skill.enabled and skill.matches(clean_input):
                    return skill
            return None

    def get_all_tools(self, enabled_only: bool = True) -> List[str]:
        """
        Возвращает уникальный список всех инструментов, объявленных навыками.
        """
        tools_set = []
        with self._lock:
            for skill in self.get_all(enabled_only=enabled_only):
                for t in skill.tools:
                    if t not in tools_set:
                        tools_set.append(t)
        return tools_set


# =============================================================================
# Загрузка встроенных навыков и синглтон
# =============================================================================

def load_builtin_skills(registry: Optional[SkillRegistry] = None) -> SkillRegistry:
    """
    Инициализирует и регистрирует стандартные встроенные навыки Акакия:
    - project (работа с кодовой базой и файлами проекта)
    - memory (управление долговременной памятью)
    - household (бытовой ассистент: задачи, напоминания, заметки, списки)
    """
    reg = registry if registry is not None else SkillRegistry()

    # Отложенный импорт для исключения циклических зависимостей
    from skills.project import ProjectSkill
    from skills.memory import MemorySkill
    from skills.household import HouseholdSkill

    reg.register(ProjectSkill())
    reg.register(MemorySkill())
    reg.register(HouseholdSkill())

    return reg


_global_skill_registry: Optional[SkillRegistry] = None
_global_registry_lock = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    """
    Возвращает глобальный синглтон SkillRegistry.
    """
    global _global_skill_registry
    with _global_registry_lock:
        if _global_skill_registry is None:
            _global_skill_registry = load_builtin_skills()
        return _global_skill_registry


def reset_skill_registry() -> None:
    """
    Сбрасывает синглтон (используется для изолированных тестов).
    """
    global _global_skill_registry
    with _global_registry_lock:
        _global_skill_registry = None
