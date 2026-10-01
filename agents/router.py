"""
Маршрутизатор доменных агентов (AgentRouter) multi-agent архитектуры Акакия.

Целевая схема:
User Request
     |
     v
AgentRouter
     |
     v
agents.AgentRegistry
     |
     v
Domain Agents (Household / Research / Coding / Memory)

Принципы:
1. Детерминированная маршрутизация верхнего уровня на основе capabilities зарегистрированных агентов.
2. Использование исключительно реестра агентов (AgentRegistry). Полное отсутствие жестких зависимостей
   от конкретных классов доменных агентов (отсутствие hardcoded import конкретных агентов).
3. Router отвечает исключительно за выбор подходящего Domain Agent и не выполняет задачу сам.
4. Открытость для расширения: регистрация новых агентов или правил capabilities не требует модификации кода Router.
"""

from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Union

from agents.base import BaseAgent
from agents.registry import AgentRegistry, get_agent_registry

logger = logging.getLogger(__name__)


# Регулярные выражения исключений: термины кода и файлов проекта,
# которые не должны ложно срабатывать на общеупотребительное слово "список".
_CODE_AND_PROJECT_EXCLUSIONS = re.compile(
    r"\b(?:файлов|файлы|функций|функции|коммитов|коммиты|веток|ветки|модулей|модули|классов|классы|папок|папки|директорий|проекта|репозитория)\b",
    re.IGNORECASE
)

# Префиксы вежливости и обращений
_CALL_PREFIX_REGEX = re.compile(
    r"^(?:(?:акакий|пожалуйста|плиз|слушай|скажи)[,\s:]*)+",
    re.IGNORECASE
)


@dataclass
class RouteResult:
    """
    Результат работы AgentRouter.

    Содержит:
    - agent: найденный экземпляр BaseAgent (или None, если агент не найден);
    - capability: доменная возможность, по которой произошло сопоставление;
    - confidence: оценка уверенности выбора (0.0 - 1.0);
    - reason: текстовое пояснение решения маршрутизатора;
    - success: флаг успешного нахождения активного агента;
    - is_disabled: флаг того, что подходящий агент был найден, но отключен в реестре.
    """
    agent: Optional[BaseAgent] = None
    capability: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    success: bool = False
    is_disabled: bool = False

    @property
    def agent_name(self) -> Optional[str]:
        """Имя выбранного агента."""
        return self.agent.name if self.agent is not None else None

    def __bool__(self) -> bool:
        """Позволяет использовать `if result:` для проверки успешного сопоставления."""
        return self.success

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация результата маршрутизации в словарь."""
        return {
            "success": self.success,
            "agent": self.agent_name,
            "capability": self.capability,
            "confidence": self.confidence,
            "reason": self.reason,
            "is_disabled": self.is_disabled,
        }

    @classmethod
    def match(
        cls,
        agent: BaseAgent,
        capability: Optional[str] = None,
        confidence: float = 1.0,
        reason: str = ""
    ) -> "RouteResult":
        """Фабрика успешного сопоставления с активным агентом."""
        return cls(
            agent=agent,
            capability=capability,
            confidence=confidence,
            reason=reason or f"Запрос направлен агенту '{agent.name}' (capability: '{capability}').",
            success=True,
            is_disabled=False
        )

    @classmethod
    def no_match(cls, reason: str = "Подходящий доменный агент не найден.") -> "RouteResult":
        """Фабрика результата при отсутствии совпадений."""
        return cls(
            agent=None,
            capability=None,
            confidence=0.0,
            reason=reason,
            success=False,
            is_disabled=False
        )

    @classmethod
    def disabled(
        cls,
        agent: BaseAgent,
        capability: Optional[str] = None,
        reason: str = ""
    ) -> "RouteResult":
        """Фабрика результата, когда агент найден, но отключен."""
        return cls(
            agent=agent,
            capability=capability,
            confidence=0.0,
            reason=reason or f"Агент '{agent.name}' для возможности '{capability}' отключен.",
            success=False,
            is_disabled=True
        )

    def __repr__(self) -> str:
        if self.success:
            return f"<RouteResult agent='{self.agent_name}' cap='{self.capability}' conf={self.confidence:.2f}>"
        if self.is_disabled:
            return f"<RouteResult disabled agent='{self.agent_name}' cap='{self.capability}'>"
        return f"<RouteResult no_match reason='{self.reason}'>"


class AgentRouter:
    """
    Высокоуровневый детерминированный маршрутизатор доменных агентов.
    Определяет целевого агента через AgentRegistry на основе семантических правил capabilities.
    """

    def __init__(self, registry: Optional[AgentRegistry] = None) -> None:
        self.registry = registry
        self._capability_rules: Dict[str, List[re.Pattern]] = {}
        self._init_default_capability_rules()

    def _get_registry(self) -> AgentRegistry:
        """Возвращает внедрённый или глобальный экземпляр AgentRegistry."""
        if self.registry is not None:
            return self.registry
        return get_agent_registry()

    def _clean_input(self, text: str) -> str:
        """Очищает запрос от префиксов обращения и краевых пробелов."""
        stripped = _CALL_PREFIX_REGEX.sub("", text).strip()
        return stripped if stripped else text.strip()

    def register_capability_rule(
        self,
        capability: str,
        patterns: Union[str, Sequence[str], re.Pattern, Sequence[re.Pattern]]
    ) -> None:
        """
        Регистрирует или расширяет регулярные выражения для распознавания указанной capability.
        Позволяет подключать новые доменные области без модификации исходного кода Router.
        """
        clean_cap = str(capability).strip().lower()
        if not clean_cap:
            raise ValueError("Имя capability не может быть пустым.")

        if clean_cap not in self._capability_rules:
            self._capability_rules[clean_cap] = []

        if isinstance(patterns, (str, re.Pattern)):
            patterns = [patterns]

        for p in patterns:
            if isinstance(p, re.Pattern):
                self._capability_rules[clean_cap].append(p)
            elif isinstance(p, str) and p.strip():
                self._capability_rules[clean_cap].append(re.compile(p.strip(), re.IGNORECASE))

    def _init_default_capability_rules(self) -> None:
        """
        Инициализирует базовые контекстные шаблоны для стандартных возможностей.
        Связаны исключительно с абстрактными capability, а не с конкретными классами агентов.
        """
        # 1. Задачи (tasks)
        self.register_capability_rule("tasks", [
            r"\b(?:задач[а-я]*|список\s+дел|дела\s+на\s+сегодня|туду|todo)\b",
            r"\b(?:добавь|создай|поставь|новая|выполни|закрой|отметь|сделай|удали|стереть|покажи)\s+(?:мне\s+)?задач[а-я]*\b",
            r"^задача:\s*.+$",
            r"^(?:мои\s+)?задачи$",
            r"^(?:активные|невыполненные|выполненные|завершенные)\s+задачи$"
        ])

        # 2. Напоминания (reminders)
        self.register_capability_rule("reminders", [
            r"\b(?:напомни[а-я]*|напоминан[а-я]*|будильник[а-я]*)\b",
            r"\b(?:создай|поставь|новое|удали|отмени|покажи)\s+(?:мне\s+)?напоминани[а-я]*\b",
            r"^(?:мои\s+)?напоминания$"
        ])

        # 3. Заметки (notes)
        self.register_capability_rule("notes", [
            r"\b(?:заметк[а-я]*|заметок)\b",
            r"\b(?:запиши\s+(?:в\s+)?заметк[а-я]*|создай\s+заметку|найди\s+заметку|покажи\s+заметки)\b",
            r"\b(?:создай|добавь|новая|запиши|найди|удали|покажи)\s+(?:мне\s+)?заметк[а-я]*\b",
            r"^(?:мои\s+)?заметки$"
        ])

        # 4. Списки (lists)
        self.register_capability_rule("lists", [
            r"\b(?:список\s+(?:покупок|продуктов|вещей|фильмов|книг|желаний))\b",
            r"\b(?:создай|сделай|новый|покажи|открой|выведи|очисти|удали)\s+(?:мне\s+)?список(?:\s+[а-яa-z0-9_-]+)?\b",
            r"\b(?:добавь|запиши|внеси|вычеркни|удали|отметь)\s+(?:пункт\s+)?(?:в|из)\s+списк[а-я]*\b",
            r"^(?:покажи\s+)?списки$",
            r"^список\s+[а-яa-z0-9_-]+$"
        ])

        # 5. Общие бытовые дела (household)
        self.register_capability_rule("household", [
            r"\b(?:быт|бытов[а-я]+|уборк[а-я]+|стирк[а-я]+|по\s+дому|домашние\s+дела)\b"
        ])

        # 6. Исследования и сбор информации (research)
        self.register_capability_rule("research", [
            r"\b(?:исследуй|исследуйте|исследовать|исследован[а-я]+)\b",
            r"\b(?:проведи|проведите|провести|сделай|сделайте|сделать|подготовь|подготовьте|подготовить)\s+(?:мне\s+)?исследован[а-я]+\b",
            r"\b(?:найди|найти|собери|собрать)\s+(?:мне\s+)?информаци[а-я]+(?:\s+(?:по|про|о|об|для))?\b",
            r"^исследование:\s*.+$",
            r"\b(?:аналитический\s+отчет|аналитический\s+отчёт|анализ\s+предметной\s+области)\b"
        ])

    def route(self, task: str) -> RouteResult:
        """
        Главная точка маршрутизации пользовательского запроса к доменному агенту.

        Алгоритм:
        1. Проверка на пустой ввод.
        2. Интроспекция зарегистрированных агентов (проверка пользовательских can_handle/patterns).
        3. Сопоставление с правилами capabilities и поиск агента в AgentRegistry.
        4. Проверка статуса агента (enabled/disabled).
        5. Возврат структурированного RouteResult.

        :param task: Текст пользовательского запроса.
        :return: RouteResult с выбранным агентом или причиной отказа.
        """
        if task is None or not isinstance(task, str) or not task.strip():
            return RouteResult.no_match(reason="Получен пустой запрос для маршрутизации.")

        clean_task = self._clean_input(task)
        registry = self._get_registry()

        # 1. Проверяем собственную самооценку агентов (can_handle / метаданные паттернов), если они определены
        for agent in registry.list_agents(enabled_only=False):
            # Метод can_handle(task)
            can_handle_fn = getattr(agent, "can_handle", None)
            if callable(can_handle_fn):
                try:
                    score = float(can_handle_fn(clean_task))
                    if score > 0.5:
                        primary_cap = agent.capabilities[0] if agent.capabilities else agent.name
                        if not agent.enabled:
                            return RouteResult.disabled(
                                agent=agent,
                                capability=primary_cap,
                                reason=f"Агент '{agent.name}' подходит для запроса, но в данный момент отключен."
                            )
                        return RouteResult.match(
                            agent=agent,
                            capability=primary_cap,
                            confidence=score,
                            reason=f"Агент '{agent.name}' подтвердил обработку запроса (can_handle={score:.2f})."
                        )
                except Exception as ex:
                    logger.warning(f"Ошибка вызова can_handle у агента '{agent.name}': {ex}")

            # Паттерны в metadata агента
            agent_patterns = agent.metadata.get("patterns") if isinstance(agent.metadata, dict) else None
            if agent_patterns and isinstance(agent_patterns, (list, tuple)):
                for pat in agent_patterns:
                    if isinstance(pat, (str, re.Pattern)):
                        pattern_obj = pat if isinstance(pat, re.Pattern) else re.compile(pat, re.IGNORECASE)
                        if pattern_obj.search(clean_task):
                            primary_cap = agent.capabilities[0] if agent.capabilities else agent.name
                            if not agent.enabled:
                                return RouteResult.disabled(
                                    agent=agent,
                                    capability=primary_cap,
                                    reason=f"Агент '{agent.name}' подходит по шаблону, но в данный момент отключен."
                                )
                            return RouteResult.match(
                                agent=agent,
                                capability=primary_cap,
                                confidence=1.0,
                                reason=f"Совпадение по явному шаблону агента '{agent.name}'."
                            )

        # 2. Проверяем сопоставление по зарегистрированным capability rules
        is_code_or_project = bool(_CODE_AND_PROJECT_EXCLUSIONS.search(clean_task))

        for capability, patterns in self._capability_rules.items():
            # Если запрос содержит явные маркеры кода/файлов проекта, не направляем его в бытовые списки
            if capability == "lists" and is_code_or_project:
                continue

            for pattern in patterns:
                if pattern.search(clean_task):
                    # Найдена подходящая возможность (capability)
                    # Ищем агента в реестре, обладающего этой возможностью
                    candidates = registry.find_by_capability(capability, enabled_only=False)

                    if not candidates:
                        # Запасной поиск по имени инструмента, если capability совпадает с инструментом
                        candidates = registry.find_by_tool(capability, enabled_only=False)

                    if candidates:
                        # Проверяем наличие активного агента
                        active_candidates = [a for a in candidates if a.enabled]
                        if active_candidates:
                            selected = active_candidates[0]
                            return RouteResult.match(
                                agent=selected,
                                capability=capability,
                                confidence=1.0,
                                reason=f"Запрос сопоставлен с возможностью '{capability}', выбран агент '{selected.name}'."
                            )
                        else:
                            # Все подходящие агенты отключены
                            disabled_agent = candidates[0]
                            return RouteResult.disabled(
                                agent=disabled_agent,
                                capability=capability,
                                reason=f"Агент '{disabled_agent.name}' для возможности '{capability}' в данный момент отключен."
                            )

        # 3. Дополнительная проверка прямого совпадения с именами возможностей активных агентов
        for agent in registry.list_agents(enabled_only=False):
            for cap in agent.capabilities:
                # Поиск целого слова названия capability в запросе
                cap_pattern = re.compile(rf"\b{re.escape(cap)}\b", re.IGNORECASE)
                if cap_pattern.search(clean_task):
                    if not agent.enabled:
                        return RouteResult.disabled(
                            agent=agent,
                            capability=cap,
                            reason=f"Агент '{agent.name}' для возможности '{cap}' отключен."
                        )
                    return RouteResult.match(
                        agent=agent,
                        capability=cap,
                        confidence=0.8,
                        reason=f"Прямое упоминание возможности '{cap}' в запросе."
                    )

        # 4. Если совпадений не обнаружено
        return RouteResult.no_match(
            reason=f"Не найден подходящий доменный агент для запроса: '{clean_task}'"
        )
