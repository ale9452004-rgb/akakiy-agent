"""
Модуль унифицированного результата выполнения Sub-Agent'а (AgentResult) и модели Artifacts.

Обеспечивает:
- модель Artifact (имя, тип, путь, содержимое, метаданные);
- классификатор типов артефактов ArtifactType с автоопределением по расширению;
- поддержку нескольких артефактов в одном результате AgentResult;
- методы выборки (по типу, свойство images, по имени/индексу);
- двустороннюю синхронизацию created_files <-> artifacts;
- удобную сериализацию в dict / JSON;
- 100% обратную совместимость с существующими SubAgent, ImageAgent, EchoAgent и тестами.
"""

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ArtifactType:
    """
    Стандартные типы артефактов для multi-agent конвейера и GUI 2.0.
    """
    IMAGE = "image"
    PRESENTATION = "presentation"
    DOCUMENT = "document"
    FILE = "file"
    TEXT = "text"
    CODE = "code"
    AUDIO = "audio"
    DATA = "data"

    _EXT_MAP: Dict[str, str] = {
        # Изображения
        ".png": IMAGE,
        ".jpg": IMAGE,
        ".jpeg": IMAGE,
        ".webp": IMAGE,
        ".bmp": IMAGE,
        ".gif": IMAGE,
        ".svg": IMAGE,
        ".tiff": IMAGE,
        # Презентации
        ".pptx": PRESENTATION,
        ".ppt": PRESENTATION,
        ".odp": PRESENTATION,
        ".key": PRESENTATION,
        # Документы и таблицы
        ".pdf": DOCUMENT,
        ".docx": DOCUMENT,
        ".doc": DOCUMENT,
        ".xlsx": DOCUMENT,
        ".xls": DOCUMENT,
        ".csv": DOCUMENT,
        ".epub": DOCUMENT,
        # Текст
        ".txt": TEXT,
        ".md": TEXT,
        ".rtf": TEXT,
        ".log": TEXT,
        # Код и структурированные схемы
        ".py": CODE,
        ".json": CODE,
        ".js": CODE,
        ".ts": CODE,
        ".html": CODE,
        ".css": CODE,
        ".sh": CODE,
        ".ps1": CODE,
        ".yaml": CODE,
        ".yml": CODE,
        ".xml": CODE,
        ".sql": CODE,
        ".c": CODE,
        ".cpp": CODE,
        ".h": CODE,
        ".rs": CODE,
        ".go": CODE,
        # Аудио
        ".wav": AUDIO,
        ".mp3": AUDIO,
        ".ogg": AUDIO,
        ".flac": AUDIO,
        ".m4a": AUDIO,
    }

    @classmethod
    def guess_type(cls, path_or_name: str) -> str:
        """
        Определяет тип артефакта по расширению файла.
        """
        if not path_or_name:
            return cls.FILE
        ext = Path(str(path_or_name)).suffix.lower()
        return cls._EXT_MAP.get(ext, cls.FILE)


class Artifact:
    """
    Модель артефакта, созданного субагентом или инструментом.
    """

    def __init__(
        self,
        name: str,
        type: str = ArtifactType.FILE,
        path: Optional[str] = None,
        content: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.name = str(name) if name else "artifact"
        self.type = str(type).lower() if type else ArtifactType.FILE
        self.path = str(path) if path is not None else None
        self.content = content
        self.metadata = dict(metadata) if metadata is not None else {}

    @property
    def is_image(self) -> bool:
        """Является ли артефакт изображением."""
        return self.type == ArtifactType.IMAGE

    @property
    def is_presentation(self) -> bool:
        """Является ли артефакт презентацией."""
        return self.type == ArtifactType.PRESENTATION

    @property
    def is_document(self) -> bool:
        """Является ли артефакт документом."""
        return self.type in (ArtifactType.DOCUMENT, ArtifactType.PRESENTATION)

    @property
    def is_research(self) -> bool:
        """Является ли артефакт исследовательским отчётом."""
        return bool(self.metadata.get("topic") or "research" in self.name.lower())

    @property
    def is_code(self) -> bool:
        """Является ли артефакт исходным кодом."""
        return self.type == ArtifactType.CODE

    @property
    def is_file(self) -> bool:
        """Имеет ли артефакт привязку к физическому файлу на диске."""
        return self.path is not None

    def exists(self) -> bool:
        """Проверяет существование файла артефакта на диске."""
        if not self.path:
            return False
        try:
            return os.path.exists(self.path)
        except Exception:
            return False

    @property
    def size_bytes(self) -> Optional[int]:
        """Возвращает размер артефакта в байтах (из метаданных или с диска)."""
        if "size_bytes" in self.metadata and isinstance(self.metadata["size_bytes"], (int, float)):
            return int(self.metadata["size_bytes"])
        if self.exists():
            try:
                return os.path.getsize(self.path)  # type: ignore[arg-type]
            except Exception:
                pass
        if isinstance(self.content, (str, bytes)):
            return len(self.content)
        return None

    @property
    def mime_type(self) -> Optional[str]:
        """MIME-тип артефакта."""
        if "mime_type" in self.metadata and self.metadata["mime_type"]:
            return str(self.metadata["mime_type"])
        lookup_target = self.path or self.name
        if lookup_target:
            guessed, _ = mimetypes.guess_type(lookup_target)
            if guessed:
                return guessed
        return None

    @classmethod
    def from_file(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        type: Optional[str] = None,
        content: Optional[str] = None,
        **metadata
    ) -> "Artifact":
        """
        Создаёт экземпляр Artifact из локального файла.
        """
        p = Path(path)
        file_name = name or p.name
        art_type = type or ArtifactType.guess_type(file_name)

        meta = dict(metadata)
        # Автоматическое наполнение метаданных при наличии файла на диске
        try:
            if p.exists() and p.is_file():
                if "size_bytes" not in meta:
                    meta["size_bytes"] = p.stat().st_size
        except Exception:
            pass

        if "mime_type" not in meta:
            guessed_mime, _ = mimetypes.guess_type(str(p))
            if guessed_mime:
                meta["mime_type"] = guessed_mime

        return cls(
            name=file_name,
            type=art_type,
            path=str(path),
            content=content,
            metadata=meta
        )

    @classmethod
    def from_presentation(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        title: Optional[str] = None,
        slides_count: Optional[int] = None,
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания артефакта презентации.
        """
        meta = dict(metadata)
        if title is not None:
           meta["title"] = title
        if slides_count is not None:
           meta["slides_count"] = slides_count
        return cls.from_file(path, name=name, type=ArtifactType.PRESENTATION, **meta)

    @classmethod
    def from_document(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        title: Optional[str] = None,
        sections_count: Optional[int] = None,
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания артефакта документа.
        """
        meta = dict(metadata)
        if title is not None:
            meta["title"] = title
        if sections_count is not None:
            meta["sections_count"] = sections_count
        return cls.from_file(path, name=name, type=ArtifactType.DOCUMENT, **meta)

    @classmethod
    def from_research(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        topic: Optional[str] = None,
        questions_count: Optional[int] = None,
        sources_count: Optional[int] = None,
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания артефакта исследовательского отчёта.
        """
        meta = dict(metadata)
        if topic is not None:
            meta["topic"] = topic
        if questions_count is not None:
            meta["questions_count"] = questions_count
        if sources_count is not None:
            meta["sources_count"] = sources_count
        return cls.from_file(path, name=name, type=ArtifactType.TEXT, **meta)

    @classmethod
    def from_code(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        language: str = "python",
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания артефакта исходного кода.
        """
        meta = dict(metadata)
        if language is not None:
            meta["language"] = language
        return cls.from_file(path, name=name, type=ArtifactType.CODE, **meta)

    @classmethod
    def from_image(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания артефакта изображения.
        """
        meta = dict(metadata)
        if width is not None:
            meta["width"] = width
        if height is not None:
            meta["height"] = height
        return cls.from_file(path, name=name, type=ArtifactType.IMAGE, **meta)

    @classmethod
    def from_text(
        cls,
        content: str,
        name: str = "output.txt",
        type: str = ArtifactType.TEXT,
        path: Optional[str] = None,
        **metadata
    ) -> "Artifact":
        """
        Фабричный метод для создания текстового артефакта.
        """
        return cls(
            name=name,
            type=type,
            path=path,
            content=str(content),
            metadata=metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует артефакт в словарь."""
        res: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "path": self.path,
            "metadata": dict(self.metadata)
        }
        if self.content is not None:
            # Текстовое или базовое сериализуемое содержимое сохраняем напрямую
            if isinstance(self.content, (str, int, float, bool, dict, list)):
                res["content"] = self.content
            else:
                res["content"] = str(self.content)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Artifact":
        """Восстанавливает артефакт из словаря."""
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")

        return cls(
            name=data.get("name", "artifact"),
            type=data.get("type", ArtifactType.FILE),
            path=data.get("path"),
            content=data.get("content"),
            metadata=data.get("metadata", {})
        )

    def to_json(self, indent: Optional[int] = None) -> str:
        """Сериализует артефакт в JSON-строку."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "Artifact":
        """Создаёт экземпляр Artifact из JSON-строки."""
        if not isinstance(json_str, str):
            raise TypeError(f"Ожидается str, получен {type(json_str)}")
        return cls.from_dict(json.loads(json_str))

    # Dict-like доступ для удобства
    def __getitem__(self, key: str) -> Any:
        if key in ("name", "type", "path", "content", "metadata"):
            return getattr(self, key)
        if key in self.metadata:
            return self.metadata[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        return key in ("name", "type", "path", "content", "metadata") or key in self.metadata

    def __repr__(self) -> str:
        path_str = f" path='{self.path}'" if self.path else ""
        return f"<Artifact [{self.type}] name='{self.name}'{path_str}>"


class AgentResult:
    """
    Стандартизированный результат работы SubAgent v2.
    Поддерживает:
    - обратную совместимость с v1 (success, message, created_files, data, error);
    - модель Artifact и коллекцию artifacts;
    - методы фильтрации по типу и быстрого доступа к изображениям;
    - удобную сериализацию to_dict/from_dict/to_json/from_json.
    """

    def __init__(
        self,
        success: bool,
        message: str = "",
        created_files: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        artifacts: Optional[List[Union[Artifact, Dict[str, Any]]]] = None
    ):
        self.success = bool(success)
        self.message = str(message)
        self.created_files = [str(f) for f in created_files] if created_files else []
        self.data = dict(data) if data is not None else {}
        self.error = str(error) if error is not None else (None if self.success else self.message)
        self.artifacts: List[Artifact] = []

        # 1. Если явно переданы artifacts, регистрируем их
        if artifacts:
            for item in artifacts:
                if isinstance(item, Artifact):
                    art = item
                elif isinstance(item, dict):
                    art = Artifact.from_dict(item)
                else:
                    art = Artifact.from_file(str(item))
                self.artifacts.append(art)
                if art.path and art.path not in self.created_files:
                    self.created_files.append(art.path)

        # 2. Синхронизация created_files -> artifacts для всех файлов, которых еще нет в artifacts
        existing_paths = {a.path for a in self.artifacts if a.path}
        for fpath in self.created_files:
            if fpath not in existing_paths:
                # Если в data есть метаданные изображения (width/height/seed), связываем их
                meta: Dict[str, Any] = {}
                is_img = ArtifactType.guess_type(fpath) == ArtifactType.IMAGE
                if is_img:
                    for k in ("width", "height", "seed", "steps", "cfg", "prompt"):
                        if k in self.data:
                            meta[k] = self.data[k]
                art = Artifact.from_file(fpath, **meta)
                self.artifacts.append(art)
                existing_paths.add(fpath)

    @classmethod
    def ok(
        cls,
        message: str = "",
        created_files: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        artifacts: Optional[List[Union[Artifact, Dict[str, Any]]]] = None
    ) -> "AgentResult":
        """
        Фабричный метод для создания успешного результата.
        """
        return cls(
            success=True,
            message=message,
            created_files=created_files,
            data=data,
            error=None,
            artifacts=artifacts
        )

    @classmethod
    def fail(
        cls,
        error: str,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        artifacts: Optional[List[Union[Artifact, Dict[str, Any]]]] = None,
        created_files: Optional[List[str]] = None
    ) -> "AgentResult":
        """
        Фабричный метод для создания неуспешного результата.
        """
        msg = message if message else error
        return cls(
            success=False,
            message=msg,
            created_files=created_files,
            data=data,
            error=error,
            artifacts=artifacts
        )

    # =========================================================================
    # Работа с артефактами
    # =========================================================================

    def add_artifact(
        self,
        artifact: Union[Artifact, Dict[str, Any], str, Path],
        **kwargs
    ) -> Artifact:
        """
        Добавляет артефакт в результат с гарантией синхронизации created_files.
        """
        if isinstance(artifact, Artifact):
            art = artifact
            if kwargs:
                art.metadata.update(kwargs)
        elif isinstance(artifact, dict):
            data = dict(artifact)
            data.update(kwargs)
            art = Artifact.from_dict(data)
        elif isinstance(artifact, (str, Path)):
            art = Artifact.from_file(artifact, **kwargs)
        else:
            raise TypeError(f"Неподдерживаемый тип артефакта: {type(artifact)}")

        self.artifacts.append(art)
        if art.path and art.path not in self.created_files:
            self.created_files.append(art.path)
        return art

    def add_file(
        self,
        path: Union[str, Path],
        artifact_type: Optional[str] = None,
        **metadata
    ) -> Artifact:
        """
        Удобный метод добавления созданного файла как артефакта.
        """
        return self.add_artifact(Artifact.from_file(path, type=artifact_type, **metadata))

    def get_artifacts_by_type(self, artifact_type: str) -> List[Artifact]:
        """
        Возвращает список артефактов указанного типа.
        """
        target_type = str(artifact_type).lower().strip()
        return [a for a in self.artifacts if a.type.lower() == target_type]

    def get_artifact(self, name_or_index: Union[str, int]) -> Optional[Artifact]:
        """
        Возвращает артефакт по индексу (int) или имени/пути (str).
        """
        if isinstance(name_or_index, int):
            if 0 <= name_or_index < len(self.artifacts):
                return self.artifacts[name_or_index]
            return None

        target = str(name_or_index).lower().strip()
        for a in self.artifacts:
            if a.name.lower() == target:
                return a
            if a.path and (a.path.lower() == target or Path(a.path).name.lower() == target):
                return a
        return None

    @property
    def images(self) -> List[Artifact]:
        """Список всех артефактов изображений."""
        return self.get_artifacts_by_type(ArtifactType.IMAGE)

    @property
    def presentations(self) -> List[Artifact]:
        """Список всех артефактов презентаций."""
        return self.get_artifacts_by_type(ArtifactType.PRESENTATION)

    @property
    def documents(self) -> List[Artifact]:
        """Список всех артефактов документов."""
        return self.get_artifacts_by_type(ArtifactType.DOCUMENT)

    @property
    def research_reports(self) -> List[Artifact]:
        """Список всех артефактов исследовательских отчётов."""
        return [
            a for a in self.artifacts
            if a.is_research
        ]

    @property
    def code_artifacts(self) -> List[Artifact]:
        """Список всех артефактов кода."""
        return self.get_artifacts_by_type(ArtifactType.CODE)

    @property
    def file_artifacts(self) -> List[Artifact]:
        """Список всех артефактов файлов."""
        return self.get_artifacts_by_type(ArtifactType.FILE)

    @property
    def has_artifacts(self) -> bool:
        """Проверяет, содержит ли результат хотя бы один артефакт."""
        return bool(self.artifacts)

    @property
    def primary_artifact(self) -> Optional[Artifact]:
        """Первый артефакт в результате (если есть)."""
        return self.artifacts[0] if self.artifacts else None

    # =========================================================================
    # Сериализация и десериализация
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует результат в стандартный словарь.
        """
        res: Dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "created_files": list(self.created_files),
            "data": dict(self.data),
            "artifacts": [a.to_dict() for a in self.artifacts]
        }
        if self.error is not None:
            res["error"] = self.error
        for k, v in self.data.items():
            if k not in res:
                res[k] = v
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentResult":
        """
        Создаёт экземпляр AgentResult из словаря (100% совместим с форматами v1 и v2).
        """
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")

        artifacts_data = data.get("artifacts")
        parsed_artifacts: Optional[List[Artifact]] = None
        if artifacts_data is not None and isinstance(artifacts_data, list):
            parsed_artifacts = [
                Artifact.from_dict(a) if isinstance(a, dict) else a
                for a in artifacts_data
            ]

        # Извлекаем дополнительные ключи, не входящие в стандартные поля
        extra_data = {}
        if isinstance(data.get("data"), dict):
            extra_data.update(data["data"])
        for k, v in data.items():
            if k not in ("success", "message", "created_files", "data", "error", "artifacts"):
                extra_data[k] = v

        return cls(
            success=data.get("success", False),
            message=data.get("message", ""),
            created_files=data.get("created_files"),
            data=extra_data if extra_data else data.get("data"),
            error=data.get("error"),
            artifacts=parsed_artifacts
        )

    def to_json(self, indent: Optional[int] = None) -> str:
        """Сериализует результат в JSON-строку."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "AgentResult":
        """Создаёт экземпляр AgentResult из JSON-строки."""
        if not isinstance(json_str, str):
            raise TypeError(f"Ожидается str, получен {type(json_str)}")
        return cls.from_dict(json.loads(json_str))

    # =========================================================================
    # Dict-like интерфейс для 100% обратной совместимости
    # =========================================================================

    def __getitem__(self, key: str) -> Any:
        if key in ("success", "message", "created_files", "data", "artifacts", "error"):
            return getattr(self, key)
        if key in self.data:
            return self.data[key]
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in ("success", "message", "created_files", "error", "artifacts"):
            setattr(self, key, value)
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        return (
            key in ("success", "message", "created_files", "data", "artifacts", "error")
            or key in self.data
            or key in self.to_dict()
        )

    def keys(self):
        """Возвращает ключи словаря результата."""
        return self.to_dict().keys()

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        files_info = f", files={len(self.created_files)}" if self.created_files else ""
        art_info = f", artifacts={len(self.artifacts)}" if self.artifacts else ""
        err_info = f", error='{self.error}'" if self.error else ""
        return f"<AgentResult [{status}] msg='{self.message}'{art_info}{files_info}{err_info}>"
