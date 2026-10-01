"""
Доменный агент сбора информации и аналитики (ResearchAgent) multi-agent архитектуры Акакия.

Отвечает за:
- прием пользовательских исследовательских задач;
- валидацию и определение параметров исследования (тема, вопросы, источники);
- делегирование сбора и структурирования информации специализированному worker (tools/agents/research.py);
- формирование стандартизированного результата AgentResult с аналитическим отчётом (Markdown) и Artifact.

Архитектурный принцип:
Domain ResearchAgent является высокоуровневой сущностью (Domain Agent), наследующей BaseAgent.
Он не создает второй поисковый движок и не дублирует логику сбора информации,
а использует существующие механизмы worker-слоя проекта.
"""

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from agents.base import BaseAgent
from tools.agents.context import AgentContext
from tools.agents.research import ResearchAgent as SubAgentResearchWorker
from tools.agents.result import AgentResult

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """
    Высокоуровневый доменный агент исследований и аналитики Акакия.
    """

    name: str = "research"
    description: str = "Сбор информации, исследование предметных областей и формирование аналитических отчётов."
    capabilities: List[str] = [
        "research",
        "search",
        "analysis",
        "investigation",
        "information"
    ]
    tools: List[str] = [
        "research",
        "gather_information",
        "generate_report",
        "search"
    ]

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        enabled: bool = True,
        worker: Optional[SubAgentResearchWorker] = None,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any
    ):
        super().__init__(
            name=name if name is not None else self.name,
            description=description if description is not None else self.description,
            capabilities=capabilities,
            tools=tools,
            enabled=enabled,
            **kwargs
        )
        self.worker = worker
        self.output_dir = output_dir

    def _get_worker(self) -> SubAgentResearchWorker:
        """Возвращает внедрённый или стандартный экземпляр SubAgent worker."""
        if self.worker is not None:
            return self.worker
        try:
            from tools.agents.registry import get_agent_registry
            custom_worker = get_agent_registry().get("research")
            if custom_worker is not None and isinstance(custom_worker, SubAgentResearchWorker):
                return custom_worker
        except Exception:
            pass
        return SubAgentResearchWorker(output_dir=self.output_dir)

    def can_handle(self, task: str) -> float:
        """
        Оценка релевантности запроса для доменного исследовательского агента.
        Возвращает оценку 0.0 - 1.0 для AgentRouter.
        """
        if not task or not isinstance(task, str):
            return 0.0

        norm = task.strip().lower()

        # Исключения: явные команды управления другими сущностями (задачами, напоминаниями, заметками)
        if re.search(r"^(?:создай|добавь|удали|выполни|отметь|закрой)\s+(?:задач[а-я]*|напоминани[а-я]*|заметк[а-я]*|список\b)", norm):
            return 0.0
        if re.search(r"\b(?:найди|поиск)\s+(?:в\s+)?заметк[а-я]*\b", norm):
            return 0.0
        if re.search(r"^(?:напомни|будильник|список\s+(?:покупок|дел|продуктов))", norm):
            return 0.0

        # Явные маркеры исследования
        if re.search(r"\b(?:исследуй|исследуйте|исследовать|исследован[а-я]+)\b", norm):
            return 1.0
        if re.search(r"\b(?:найди|собери|подготовь)\s+(?:мне\s+)?информаци[а-я]+\b", norm):
            return 0.95
        if re.search(r"\b(?:аналитический\s+отчет|аналитический\s+отчёт|анализ\s+предметной\s+области)\b", norm):
            return 0.9

        return 0.0

    def _is_foreign_domain_task(self, task: str) -> bool:
        """
        Проверяет, относится ли запрос явно к другому домену (например, бытовому),
        не имея исследовательского контекста.
        """
        norm = task.strip().lower()

        # Если есть явные исследовательские маркеры, задача считается исследовательской
        if re.search(r"\b(?:исследуй|исследован[а-я]*|анализ[а-я]*|информаци[а-я]*|обзор|справк[а-я]*|research|investigat[a-z]*)\b", norm):
            return False

        # Явные команды других доменов
        if re.search(r"^(?:создай|добавь|удали|выполни|отметь)\s+(?:задач[а-я]*|напоминани[а-я]*|заметк[а-я]*|список\b)", norm):
            return True
        if re.search(r"^(?:напомни|будильник|список\s+(?:покупок|дел|продуктов))", norm):
            return True

        return False

    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Основная точка входа для исполнения исследовательской задачи.

        :param task: Текст исследовательской задачи или тема.
        :param context: Опциональный словарь контекста сессии.
        :param kwargs: Дополнительные параметры (topic, questions, files, sources, action и т.д.).
        :return: Канонический AgentResult.
        """
        task_str = str(task).strip() if task is not None else ""

        # 1. Проверка на отключённого агента
        if not self.enabled:
            return AgentResult.fail(
                error=f"Доменный агент '{self.name}' отключен.",
                message=f"Агент '{self.name}' в данный момент неактивен.",
                data={"agent": self.name}
            )

        # 2. Проверка неподдерживаемого действия (action)
        action = kwargs.get("action") or kwargs.get("tool") or (context.get("action") if isinstance(context, dict) else None)
        if action:
            clean_action = str(action).strip().lower()
            if clean_action not in ("research", "gather_information", "generate_report", "search", "investigate"):
                return AgentResult.fail(
                    error=f"Неподдерживаемое действие для ResearchAgent: '{action}'",
                    message=f"Действие '{action}' не поддерживается исследовательским агентом.",
                    data={"agent": self.name, "action": action}
                )

        # 3. Валидация входных данных: тема или вопросы
        has_topic = bool(kwargs.get("topic") or (context and context.get("topic")))
        has_questions = bool(kwargs.get("questions") or (context and context.get("questions")))

        if not task_str and not has_topic and not has_questions:
            return AgentResult.fail(
                error="Не указана тема или задача для исследования.",
                message="Исследовательский запрос не может быть пустым.",
                data={"agent": self.name}
            )

        # 4. Проверка на принадлежность к чужому домену
        if task_str and self._is_foreign_domain_task(task_str):
            return AgentResult.fail(
                error=f"Запрос '{task_str}' не относится к исследовательской области.",
                message="Данная задача относится к другому домену и не поддерживается ResearchAgent.",
                data={"agent": self.name, "task": task_str}
            )

        # 5. Подготовка контекста для worker
        merged_meta: Dict[str, Any] = {}
        if isinstance(context, dict):
            merged_meta.update(context)
        merged_meta.update(kwargs)

        files: List[str] = []
        if "files" in kwargs and isinstance(kwargs["files"], list):
            files = [str(f) for f in kwargs["files"]]
        elif isinstance(context, dict) and "files" in context and isinstance(context["files"], list):
            files = [str(f) for f in context["files"]]

        agent_ctx = AgentContext(
            task=task_str,
            metadata=merged_meta,
            files=files
        )

        # 6. Делегирование исполнения существующему worker
        worker = self._get_worker()

        try:
            worker_result = worker.run(agent_ctx)
        except Exception as ex:
            logger.error(f"Исключение при вызове ResearchWorker: {ex}", exc_info=True)
            return AgentResult.fail(
                error=f"Ошибка слоя ResearchWorker ({type(ex).__name__}): {ex}",
                message=f"Сбой при выполнении исследования: {ex}",
                data={"agent": self.name, "task": task_str}
            )

        # 7. Возврат результата
        if isinstance(worker_result, AgentResult):
            # Обогащаем data идентификатором доменного агента
            if isinstance(worker_result.data, dict):
                worker_result.data.setdefault("domain_agent", self.name)
            return worker_result

        return AgentResult.ok(
            message="Исследование выполнено.",
            data={"result": worker_result, "domain_agent": self.name}
        )
