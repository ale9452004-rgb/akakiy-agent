"""
Модуль специализированного Sub-Agent'а безопасной работы с файлами (FileAgent).

Обеспечивает:
- приём задач по поиску, чтению, созданию, копированию, перемещению и получению метаданных файлов через AgentContext;
- безопасную валидацию путей в пределах рабочей директории и защиту от path traversal;
- явный запрет на удаление файлов;
- возврат стандартизированного AgentResult с моделью Artifact для созданных и прочитанных файлов.
"""

from datetime import datetime
import mimetypes
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union

from config import PROJECT_PATH
from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.files import (
    find_file,
    list_files,
    read_file,
    resolve_safe_path,
    search_files,
    write_file,
)


class FileAgent(SubAgent):
    """
    Специализированный Sub-Agent для безопасных операций с файловой системой.
    """

    name: str = "file"
    description: str = "Специализированный sub-agent для безопасной работы с файлами (поиск, чтение, создание, копирование, перемещение, метаданные)."
    capabilities: List[str] = [
        "file",
        "files",
        "search",
        "read",
        "create",
        "write",
        "copy",
        "move",
        "metadata",
        "stat",
    ]

    def __init__(
        self,
        project_path: Optional[Union[str, Path]] = None,
        enabled: bool = True
    ):
        super().__init__(
            name=self.name,
            description=self.description,
            capabilities=self.capabilities,
            enabled=enabled
        )
        self.project_path = (
            Path(project_path).resolve()
            if project_path
            else PROJECT_PATH.resolve()
        )

    # =========================================================================
    # Разрешение путей
    # =========================================================================

    def resolve_path(self, filename: str) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
        """
        Проверяет и возвращает безопасный путь внутри рабочей директории.
        """
        return resolve_safe_path(filename, base_path=self.project_path)

    # =========================================================================
    # Разбор задачи и параметров
    # =========================================================================

    def parse_task(
        self,
        task: str,
        metadata: Optional[Dict[str, Any]] = None,
        context_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Определяет файловое действие и извлекает целевые аргументы.
        """
        meta = dict(metadata or {})
        task_str = task.strip()

        action = meta.get("action")
        target_file = (
            meta.get("filename")
            or meta.get("file")
            or meta.get("path")
            or meta.get("target_file")
        )
        source = meta.get("source") or meta.get("src")
        destination = meta.get("destination") or meta.get("dst")
        content = meta.get("content")
        query = meta.get("query")
        search_content = bool(meta.get("search_content", False))

        if action:
            act_norm = str(action).lower().strip()
            if act_norm in ("file", "files", "run", "do"):
                action = None
            else:
                action_map = {
                    "find": "search",
                    "search": "search",
                    "read": "read",
                    "cat": "read",
                    "view": "read",
                    "create": "create",
                    "write": "create",
                    "copy": "copy",
                    "cp": "copy",
                    "move": "move",
                    "mv": "move",
                    "rename": "move",
                    "metadata": "metadata",
                    "stat": "metadata",
                    "info": "metadata",
                    "delete": "delete",
                    "remove": "delete",
                    "unlink": "delete",
                }
                action = action_map.get(act_norm, act_norm)

        # Если действие не задано явно в метаданных, парсим из текста задачи
        if not action:
            # 1. Запрещённые операции удаления
            if re.search(r"^(?:удали|удалить|сотри|стереть|delete|remove|unlink)\b", task_str, re.IGNORECASE):
                action = "delete"

            # 2. Копирование: скопируй [файл] <src> в [файл] <dst>
            elif re.search(r"^(?:скопируй|скопировать|копируй|копировать|copy|cp)\b", task_str, re.IGNORECASE):
                action = "copy"
                cp_m = re.match(
                    r"^(?:скопируй|скопировать|копируй|копировать|copy|cp)\s+(?:файл\s+)?(.+?)\s+(?:в|to|в\s+файл)\s+(.+)$",
                    task_str,
                    re.IGNORECASE
                )
                if cp_m:
                    source = source or cp_m.group(1).strip().strip("\"'")
                    destination = destination or cp_m.group(2).strip().strip("\"'")

            # 3. Перемещение / переименование: перемести [файл] <src> в <dst>
            elif re.search(r"^(?:перемести|переместить|переименуй|переименовать|move|mv|rename)\b", task_str, re.IGNORECASE):
                action = "move"
                mv_m = re.match(
                    r"^(?:перемести|переместить|переименуй|переименовать|move|mv|rename)\s+(?:файл\s+)?(.+?)\s+(?:в|to|на|в\s+файл)\s+(.+)$",
                    task_str,
                    re.IGNORECASE
                )
                if mv_m:
                    source = source or mv_m.group(1).strip().strip("\"'")
                    destination = destination or mv_m.group(2).strip().strip("\"'")

            # 4. Метаданные / stat / info: метаданные [файла] <path>
            elif re.search(r"^(?:метаданные|информация|инфо|статистика|stat|metadata|info)\b", task_str, re.IGNORECASE):
                action = "metadata"
                st_m = re.match(
                    r"^(?:метаданные|информация|инфо|статистика|stat|metadata|info)\s+(?:о\s+файле\s+|файла\s+|файл\s+)?(.+)$",
                    task_str,
                    re.IGNORECASE
                )
                if st_m:
                    target_file = target_file or st_m.group(1).strip().strip("\"'")

            # 5. Создание / запись: создай [файл] <path> [: <content> / с содержимым <content>]
            elif re.search(r"^(?:создай|создать|запиши|записать|create|write)\b", task_str, re.IGNORECASE):
                action = "create"
                # Сначала проверяем явный разделитель 'с содержимым' / 'содержимое'
                cr_m_content = re.match(
                    r"^(?:создай|создать|запиши|записать|create|write)\s+(?:файл\s+)?(.+?)\s+(?:с\s+содержимым|содержимое)\s+(.+)$",
                    task_str,
                    re.IGNORECASE | re.DOTALL
                )
                if cr_m_content:
                    target_file = target_file or cr_m_content.group(1).strip().strip("\"'")
                    content = content if content is not None else cr_m_content.group(2).strip()
                else:
                    # Разделитель ':' с поддержкой Windows диска C:\...
                    cr_m_colon = re.match(
                        r"^(?:создай|создать|запиши|записать|create|write)\s+(?:файл\s+)?((?:[a-zA-Z]:[\\/][^:]+|[^:]+))\s*:\s*(.+)$",
                        task_str,
                        re.IGNORECASE | re.DOTALL
                    )
                    if cr_m_colon:
                        target_file = target_file or cr_m_colon.group(1).strip().strip("\"'")
                        content = content if content is not None else cr_m_colon.group(2).strip()
                    else:
                        cr_single = re.match(
                            r"^(?:создай|создать|create)\s+файл\s+(.+)$",
                            task_str,
                            re.IGNORECASE
                        )
                        if cr_single:
                            target_file = target_file or cr_single.group(1).strip().strip("\"'")

            # 6. Чтение: прочитай [файл] <path>
            elif re.search(r"^(?:прочитай|прочитать|чтение|read|покажи\s+содержимое|содержимое)\b", task_str, re.IGNORECASE):
                action = "read"
                rd_m = re.match(
                    r"^(?:прочитай|прочитать|чтение|read|покажи\s+содержимое|содержимое)\s+(?:файла\s+|файл\s+)?(.+)$",
                    task_str,
                    re.IGNORECASE
                )
                if rd_m:
                    target_file = target_file or rd_m.group(1).strip().strip("\"'")

            # 7. Поиск: найди [файл] <query> / поиск <query>
            elif re.search(r"^(?:найди|найти|поиск|search|find)\b", task_str, re.IGNORECASE):
                action = "search"
                if re.search(r"\b(?:текст|в\s+файлах|строку|код)\b", task_str, re.IGNORECASE):
                    search_content = True
                sr_m = re.match(
                    r"^(?:найди|найти|поиск|search|find)\s+(?:мне\s+)?(?:в\s+проекте\s+)?(?:файл\s+|файлы\s+|текст\s+)?(.+)$",
                    task_str,
                    re.IGNORECASE
                )
                if sr_m:
                    query = query or sr_m.group(1).strip()

            # 8. Fallback
            else:
                if context_files:
                    target_file = target_file or context_files[0]
                    action = "read"
                else:
                    action = "search"
                    query = query or task_str

        # Подстановка целевого файла из контекста при необходимости
        if not target_file and context_files:
            target_file = context_files[0]

        return {
            "action": action,
            "file": target_file,
            "source": source,
            "destination": destination,
            "content": content if content is not None else "",
            "query": query or task_str,
            "search_content": search_content
        }

    # =========================================================================
    # Операции с файлами
    # =========================================================================

    def search(
        self,
        query: str,
        search_content: bool = False,
        max_results: int = 50
    ) -> AgentResult:
        """
        Выполняет поиск файлов по имени или поиск текста в файлах.
        """
        q = query.strip()
        if not q:
            return AgentResult.fail(
                error="Поисковый запрос пуст.",
                message="Поисковый запрос не может быть пустым."
            )

        matches: List[Dict[str, Any]] = []
        artifacts: List[Artifact] = []

        if search_content:
            # Поиск текста внутри файлов проекта
            res = search_files(q)
            if not res.get("success"):
                return AgentResult.fail(
                    error=res.get("error", "Ошибка поиска текста."),
                    message=f"Ошибка поиска: {res.get('error')}"
                )
            all_matches = res.get("matches", [])[:max_results]
            for m in all_matches:
                matches.append(m)
            msg = f"Поиск текста '{q}': найдено {len(matches)} совпадений."
        else:
            # Поиск файлов по имени / маске
            normalized_q = q.replace("\\", "/").strip("/").lower()
            count = 0
            for p in self.project_path.rglob("*"):
                if not p.is_file():
                    continue
                if any(ignored in p.parts for ignored in (".venv", "__pycache__", ".git")):
                    continue
                try:
                    rel = str(p.relative_to(self.project_path)).replace("\\", "/")
                except Exception:
                    continue

                if normalized_q in rel.lower() or normalized_q == p.name.lower():
                    matches.append({
                        "file": rel,
                        "name": p.name,
                        "size_bytes": p.stat().st_size
                    })
                    count += 1
                    if len(artifacts) < 5:
                        artifacts.append(
                            Artifact.from_file(
                                path=str(p),
                                name=p.name,
                                type=ArtifactType.guess_type(p)
                            )
                        )
                    if count >= max_results:
                        break

            msg = f"Поиск файлов по запросу '{q}': найдено {len(matches)} файлов."

        return AgentResult.ok(
            message=msg,
            artifacts=artifacts,
            data={
                "query": q,
                "search_content": search_content,
                "matches": matches,
                "count": len(matches)
            }
        )

    def read(self, filename: str) -> AgentResult:
        """
        Безопасно читает содержимое файла и возвращает Artifact.
        """
        if not filename or not str(filename).strip():
            return AgentResult.fail(
                error="Имя файла не может быть пустым.",
                message="Имя файла не задано."
            )

        fpath, err = self.resolve_path(filename)
        if err:
            return AgentResult.fail(
                error=err.get("error", f"Ошибка пути: {filename}"),
                message=f"Не удалось прочитать файл: {err.get('error')}"
            )

        if not fpath.exists():
            return AgentResult.fail(
                error=f"Файл не найден: {filename}",
                message=f"Файл не найден: {filename}"
            )

        if not fpath.is_file():
            return AgentResult.fail(
                error=f"Указанный путь не является файлом: {filename}",
                message=f"Указанный путь не является файлом: {filename}"
            )

        try:
            content = fpath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = fpath.read_text(encoding="utf-8-sig")
            except Exception:
                return AgentResult.fail(
                    error=f"Файл '{filename}' содержит бинарные данные и не может быть прочитан как текст UTF-8.",
                    message=f"Файл '{filename}' содержит бинарные данные."
                )
        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка чтения файла '{filename}': {ex}",
                message=f"Ошибка чтения файла: {ex}"
            )

        art = Artifact.from_file(
            path=str(fpath),
            name=fpath.name,
            type=ArtifactType.guess_type(fpath),
            content=content
        )

        lines = content.splitlines()
        msg = f"Файл '{filename}' успешно прочитан ({len(content)} симв., {len(lines)} строк)."

        return AgentResult.ok(
            message=msg,
            artifacts=[art],
            data={
                "filename": filename,
                "path": str(fpath),
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "lines_count": len(lines)
            }
        )

    def create(self, filename: str, content: str = "") -> AgentResult:
        """
        Безопасно создаёт или перезаписывает файл в рабочей директории.
        """
        if not filename or not str(filename).strip():
            return AgentResult.fail(
                error="Имя файла не может быть пустым.",
                message="Имя файла не задано."
            )

        fpath, err = self.resolve_path(filename)
        if err:
            return AgentResult.fail(
                error=err.get("error", f"Ошибка пути: {filename}"),
                message=f"Не удалось создать файл: {err.get('error')}"
            )

        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")
        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка записи файла '{filename}': {ex}",
                message=f"Ошибка записи файла: {ex}"
            )

        art = Artifact.from_file(
            path=str(fpath),
            name=fpath.name,
            type=ArtifactType.guess_type(fpath),
            content=content
        )

        rel_path = (
            str(fpath.relative_to(self.project_path))
            if fpath.is_relative_to(self.project_path)
            else str(fpath)
        )

        return AgentResult.ok(
            message=f"Файл '{filename}' успешно создан.",
            created_files=[str(fpath)],
            artifacts=[art],
            data={
                "filename": filename,
                "path": str(fpath),
                "relative_path": rel_path,
                "size_bytes": len(content.encode("utf-8"))
            }
        )

    def copy(self, source: str, destination: str) -> AgentResult:
        """
        Безопасно копирует файл в пределах рабочей директории.
        """
        if not source or not str(source).strip():
            return AgentResult.fail(
                error="Путь к исходному файлу не задан.",
                message="Путь к исходному файлу пуст."
            )
        if not destination or not str(destination).strip():
            return AgentResult.fail(
                error="Путь назначения не задан.",
                message="Путь назначения пуст."
            )

        src_path, src_err = self.resolve_path(source)
        if src_err:
            return AgentResult.fail(
                error=src_err.get("error", f"Ошибка пути источника: {source}"),
                message=f"Не удалось скопировать файл: {src_err.get('error')}"
            )

        dst_path, dst_err = self.resolve_path(destination)
        if dst_err:
            return AgentResult.fail(
                error=dst_err.get("error", f"Ошибка пути назначения: {destination}"),
                message=f"Не удалось скопировать файл: {dst_err.get('error')}"
            )

        if not src_path.exists():
            return AgentResult.fail(
                error=f"Исходный файл не найден: {source}",
                message=f"Исходный файл не найден: {source}"
            )

        if not src_path.is_file():
            return AgentResult.fail(
                error=f"Исходный путь не является файлом: {source}",
                message=f"Исходный путь не является файлом: {source}"
            )

        try:
            if dst_path.exists() and dst_path.is_dir():
                target_file = dst_path / src_path.name
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                target_file = dst_path

            shutil.copy2(str(src_path), str(target_file))
        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка копирования '{source}' -> '{destination}': {ex}",
                message=f"Ошибка копирования: {ex}"
            )

        art = Artifact.from_file(
            path=str(target_file),
            name=target_file.name,
            type=ArtifactType.guess_type(target_file)
        )

        return AgentResult.ok(
            message=f"Файл '{source}' успешно скопирован в '{destination}'.",
            created_files=[str(target_file)],
            artifacts=[art],
            data={
                "source": str(src_path),
                "destination": str(target_file),
                "size_bytes": target_file.stat().st_size
            }
        )

    def move(self, source: str, destination: str) -> AgentResult:
        """
        Безопасно перемещает или переименовывает файл в пределах рабочей директории.
        """
        if not source or not str(source).strip():
            return AgentResult.fail(
                error="Путь к исходному файлу не задан.",
                message="Путь к исходному файлу пуст."
            )
        if not destination or not str(destination).strip():
            return AgentResult.fail(
                error="Путь назначения не задан.",
                message="Путь назначения пуст."
            )

        src_path, src_err = self.resolve_path(source)
        if src_err:
            return AgentResult.fail(
                error=src_err.get("error", f"Ошибка пути источника: {source}"),
                message=f"Не удалось переместить файл: {src_err.get('error')}"
            )

        dst_path, dst_err = self.resolve_path(destination)
        if dst_err:
            return AgentResult.fail(
                error=dst_err.get("error", f"Ошибка пути назначения: {destination}"),
                message=f"Не удалось переместить файл: {dst_err.get('error')}"
            )

        if not src_path.exists():
            return AgentResult.fail(
                error=f"Исходный файл не найден: {source}",
                message=f"Исходный файл не найден: {source}"
            )

        try:
            if dst_path.exists() and dst_path.is_dir():
                target_file = dst_path / src_path.name
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                target_file = dst_path

            shutil.move(str(src_path), str(target_file))
        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка перемещения '{source}' -> '{destination}': {ex}",
                message=f"Ошибка перемещения: {ex}"
            )

        art = Artifact.from_file(
            path=str(target_file),
            name=target_file.name,
            type=ArtifactType.guess_type(target_file)
        )

        return AgentResult.ok(
            message=f"Файл '{source}' успешно перемещён в '{destination}'.",
            created_files=[str(target_file)],
            artifacts=[art],
            data={
                "source": str(src_path),
                "destination": str(target_file),
                "size_bytes": target_file.stat().st_size
            }
        )

    def get_metadata(self, filename: str) -> AgentResult:
        """
        Возвращает структурированные метаданные файла и Artifact.
        """
        if not filename or not str(filename).strip():
            return AgentResult.fail(
                error="Имя файла не может быть пустым.",
                message="Имя файла не задано."
            )

        fpath, err = self.resolve_path(filename)
        if err:
            return AgentResult.fail(
                error=err.get("error", f"Ошибка пути: {filename}"),
                message=f"Не удалось получить метаданные: {err.get('error')}"
            )

        if not fpath.exists():
            return AgentResult.fail(
                error=f"Файл не найден: {filename}",
                message=f"Файл не найден: {filename}"
            )

        try:
            st = fpath.stat()
            mime_type, _ = mimetypes.guess_type(str(fpath))
            is_file = fpath.is_file()
            is_dir = fpath.is_dir()
            rel_path = (
                str(fpath.relative_to(self.project_path))
                if fpath.is_relative_to(self.project_path)
                else str(fpath)
            )

            meta: Dict[str, Any] = {
                "name": fpath.name,
                "filename": filename,
                "path": str(fpath),
                "relative_path": rel_path,
                "exists": True,
                "is_file": is_file,
                "is_dir": is_dir,
                "size_bytes": st.st_size,
                "extension": fpath.suffix.lower(),
                "mime_type": mime_type or "application/octet-stream",
                "created_at": datetime.fromtimestamp(st.st_ctime).isoformat(),
                "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
            }

            artifacts: List[Artifact] = []
            if is_file:
                clean_meta = {k: v for k, v in meta.items() if k not in ("path", "name", "type")}
                art = Artifact.from_file(
                    path=str(fpath),
                    name=fpath.name,
                    type=ArtifactType.guess_type(fpath),
                    **clean_meta
                )
                artifacts.append(art)

            return AgentResult.ok(
                message=f"Метаданные файла '{filename}' получены ({meta['size_bytes']} байт).",
                artifacts=artifacts,
                data=meta
            )
        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка получения метаданных '{filename}': {ex}",
                message=f"Ошибка получения метаданных: {ex}"
            )

    # =========================================================================
    # Главный метод исполнения SubAgent API
    # =========================================================================

    def run(self, context: AgentContext) -> AgentResult:
        """
        Исполняет файловую задачу в соответствии с контрактом AgentContext.
        """
        if not self.enabled:
            return AgentResult.fail(
                error=f"Субагент '{self.name}' отключён.",
                message="FileAgent отключён в конфигурации."
            )

        task_str = (context.instruction or context.task or "").strip()
        metadata = dict(context.metadata or {})
        if "metadata" in metadata and isinstance(metadata["metadata"], dict):
            metadata = {**metadata["metadata"], **metadata}
        context_files = list(context.files or [])

        # Парсим задачу и аргументы
        parsed = self.parse_task(
            task=task_str,
            metadata=metadata,
            context_files=context_files
        )
        action = parsed.get("action")

        # 1. Запрет на удаление файлов
        if action == "delete":
            return AgentResult.fail(
                error="Удаление файлов запрещено политикой безопасности FileAgent.",
                message="Удаление файлов запрещено."
            )

        # 2. Поиск файлов или текста
        if action == "search":
            query = parsed.get("query") or task_str
            search_content = parsed.get("search_content", False)
            return self.search(query=query, search_content=search_content)

        # 3. Чтение файла
        if action == "read":
            target_file = parsed.get("file")
            if not target_file:
                return AgentResult.fail(
                    error="Не указан файл для чтения.",
                    message="Целевой файл для чтения не определён."
                )
            return self.read(filename=target_file)

        # 4. Создание файла
        if action == "create":
            target_file = parsed.get("file")
            content = parsed.get("content", "")
            if not target_file:
                return AgentResult.fail(
                    error="Не указано имя создаваемого файла.",
                    message="Целевой файл для создания не определён."
                )
            return self.create(filename=target_file, content=content)

        # 5. Копирование файла
        if action == "copy":
            source = parsed.get("source")
            destination = parsed.get("destination")
            if not source or not destination:
                return AgentResult.fail(
                    error="Для копирования необходимо указать source и destination.",
                    message="Недостаточно параметров для копирования файла."
                )
            return self.copy(source=source, destination=destination)

        # 6. Перемещение / переименование файла
        if action == "move":
            source = parsed.get("source")
            destination = parsed.get("destination")
            if not source or not destination:
                return AgentResult.fail(
                    error="Для перемещения необходимо указать source и destination.",
                    message="Недостаточно параметров для перемещения файла."
                )
            return self.move(source=source, destination=destination)

        # 7. Получение метаданных
        if action == "metadata":
            target_file = parsed.get("file")
            if not target_file:
                return AgentResult.fail(
                    error="Не указан файл для получения метаданных.",
                    message="Целевой файл для метаданных не определён."
                )
            return self.get_metadata(filename=target_file)

        return AgentResult.fail(
            error=f"Неизвестное действие FileAgent: '{action}'.",
            message=f"Неизвестное действие '{action}'."
        )
