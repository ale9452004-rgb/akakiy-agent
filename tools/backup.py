"""
Модуль резервного копирования и восстановления данных Акакия (Backup & Restore).

Обеспечивает:
1. Экспорт бытового слоя (Household) и долговременной памяти (Memory) в единый JSON-файл.
2. Валидацию структуры и версий backup-файлов до внесения изменений.
3. Транзакционный импорт с созданием снимков текущих данных и автоматическим откатом при ошибках.
4. Защиту от сохранения бэкапов внутри каталога data/.
5. Обновление in-memory состояния менеджеров без необходимости перезапуска приложения.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from config import PROJECT_PATH
from tools.household import get_household_manager, HouseholdManager
from tools.memory import get_memory_manager, MemoryManager

logger = logging.getLogger(__name__)

CURRENT_BACKUP_VERSION = 1
APP_VERSION = "2.0"


def validate_backup(data_or_path: Union[str, Path, Dict[str, Any]]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Проверяет валидность структуры, версий и типов backup-файла или словаря.

    Возвращает:
        (is_valid, error_or_ok_message, parsed_dict_or_None)
    """
    data: Dict[str, Any]

    if isinstance(data_or_path, (str, Path)):
        file_path = Path(data_or_path)
        if not file_path.exists():
            return False, f"Файл бэкапа не найден: {file_path}", None
        if not file_path.is_file():
            return False, f"Указанный путь не является файлом: {file_path}", None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            return False, f"Файл не является корректным JSON: {err}", None
        except Exception as err:
            return False, f"Ошибка чтения файла: {err}", None
    elif isinstance(data_or_path, dict):
        data = data_or_path
    else:
        return False, "Данные бэкапа должны быть файлом или словарём.", None

    if not isinstance(data, dict):
        return False, "Корневой элемент бэкапа должен быть JSON-объектом.", None

    # 1. Проверка версии формата
    if "akakiy_backup_version" not in data:
        return False, "Отсутствует обязательное поле 'akakiy_backup_version'.", None

    version = data.get("akakiy_backup_version")
    if not isinstance(version, int):
        return False, "Поле 'akakiy_backup_version' должно быть целым числом.", None

    if version > CURRENT_BACKUP_VERSION:
        return False, (
            f"Неподдерживаемая версия бэкапа ({version}). "
            f"Данная версия Акакия поддерживает формат версии <= {CURRENT_BACKUP_VERSION}."
        ), None

    if version < 1:
        return False, f"Некорректный номер версии бэкапа ({version}).", None

    # 2. Проверка структуры данных
    if "data" not in data or not isinstance(data["data"], dict):
        return False, "Отсутствует или некорректен обязательный раздел 'data'.", None

    inner_data = data["data"]

    # 3. Проверка раздела Household
    if "household" not in inner_data or not isinstance(inner_data["household"], dict):
        return False, "Отсутствует обязательный раздел данных 'data.household'.", None

    h_data = inner_data["household"]
    if not isinstance(h_data.get("tasks", []), list):
        return False, "Поле 'tasks' в household должно быть списком.", None
    if not isinstance(h_data.get("reminders", []), list):
        return False, "Поле 'reminders' в household должно быть списком.", None
    if not isinstance(h_data.get("notes", []), list):
        return False, "Поле 'notes' в household должно быть списком.", None
    if not isinstance(h_data.get("lists", {}), dict):
        return False, "Поле 'lists' в household должно быть словарём.", None

    # 4. Проверка раздела Memory
    if "memory" not in inner_data or not isinstance(inner_data["memory"], dict):
        return False, "Отсутствует обязательный раздел данных 'data.memory'.", None

    m_data = inner_data["memory"]
    if not isinstance(m_data.get("memories", []), list):
        return False, "Поле 'memories' в memory должно быть списком.", None

    return True, "OK", data


def export_data(
    output_path: Optional[Union[str, Path]] = None,
    household: Optional[HouseholdManager] = None,
    memory: Optional[MemoryManager] = None,
) -> Dict[str, Any]:
    """
    Экспортирует бытовой слой и долговременную память в единый JSON-файл.

    Параметры:
        output_path: Путь для сохранения. Если None, сохраняется в backups/ с меткой времени.
        household: Экземпляр HouseholdManager (если None, берётся дефолтный).
        memory: Экземпляр MemoryManager (если None, берётся дефолтный).

    Возвращает:
        Словарь с результатом операции {'success': bool, ...}.
    """
    h_mgr = household or get_household_manager()
    m_mgr = memory or get_memory_manager()

    data_dir = (PROJECT_PATH / "data").resolve()

    if output_path:
        target_path = Path(output_path).resolve()
    else:
        backup_dir = (PROJECT_PATH / "backups").resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = (backup_dir / f"akakiy_backup_{timestamp}.json").resolve()

    # Защита от сохранения бэкапа внутри data/
    try:
        if target_path.is_relative_to(data_dir):
            return {
                "success": False,
                "error": "Запрещено сохранять backup-файлы внутри каталога data/."
            }
    except Exception:
        pass

    tasks = list(getattr(h_mgr, "tasks", []))
    reminders = list(getattr(h_mgr, "reminders", []))
    notes = list(getattr(h_mgr, "notes", []))
    lists = dict(getattr(h_mgr, "lists", {}))
    counters = dict(getattr(h_mgr, "counters", {"task": 0, "reminder": 0, "note": 0}))

    memories = list(getattr(m_mgr, "memories", []))

    stats = {
        "tasks_count": len(tasks),
        "reminders_count": len(reminders),
        "notes_count": len(notes),
        "lists_count": len(lists),
        "memories_count": len(memories),
    }

    payload = {
        "akakiy_backup_version": CURRENT_BACKUP_VERSION,
        "app_version": APP_VERSION,
        "created_at": datetime.now().isoformat(),
        "stats": stats,
        "data": {
            "household": {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "counters": counters,
                "tasks": tasks,
                "reminders": reminders,
                "notes": notes,
                "lists": lists,
            },
            "memory": {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "memories": memories,
            },
        },
    }

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        if target_path.exists():
            os.replace(tmp_path, target_path)
        else:
            tmp_path.rename(target_path)

        logger.info(f"Бэкап успешно создан: {target_path}")
        return {
            "success": True,
            "path": str(target_path),
            "filename": target_path.name,
            "stats": stats,
            "message": f"Данные успешно экспортированы в {target_path.name}"
        }
    except Exception as err:
        logger.error(f"Ошибка при записи бэкапа {target_path}: {err}", exc_info=True)
        return {
            "success": False,
            "error": f"Не удалось сохранить файл экспорта: {err}"
        }


def import_data(
    input_path: Union[str, Path],
    household: Optional[HouseholdManager] = None,
    memory: Optional[MemoryManager] = None,
) -> Dict[str, Any]:
    """
    Транзакционно импортирует данные из backup-файла в хранилища household и memory.

    Параметры:
        input_path: Путь к файлу бэкапа.
        household: Экземпляр HouseholdManager (если None, берётся дефолтный).
        memory: Экземпляр MemoryManager (если None, берётся дефолтный).

    Возвращает:
        Словарь с результатом операции {'success': bool, ...}.
    """
    is_valid, err_msg, backup_dict = validate_backup(input_path)
    if not is_valid or not backup_dict:
        return {
            "success": False,
            "error": f"Ошибка валидации бэкапа: {err_msg}"
        }

    h_mgr = household or get_household_manager()
    m_mgr = memory or get_memory_manager()

    h_storage: Path = Path(getattr(h_mgr, "storage_path", PROJECT_PATH / "data" / "household.json"))
    m_storage: Path = Path(getattr(m_mgr, "storage_path", PROJECT_PATH / "data" / "memory.json"))

    # Создание снимка текущих файлов для защиты от сбоев
    h_backup_bytes: Optional[bytes] = None
    m_backup_bytes: Optional[bytes] = None

    if h_storage.exists():
        try:
            h_backup_bytes = h_storage.read_bytes()
        except Exception as e:
            return {"success": False, "error": f"Не удалось прочитать текущие данные household: {e}"}

    if m_storage.exists():
        try:
            m_backup_bytes = m_storage.read_bytes()
        except Exception as e:
            return {"success": False, "error": f"Не удалось прочитать текущие данные memory: {e}"}

    inner_data = backup_dict["data"]
    h_payload = inner_data["household"]
    m_payload = inner_data["memory"]

    # Транзакционная запись новых данных
    try:
        # 1. Запись household.json
        h_storage.parent.mkdir(parents=True, exist_ok=True)
        h_tmp = h_storage.with_suffix(".tmp")
        with open(h_tmp, "w", encoding="utf-8") as f:
            json.dump(h_payload, f, ensure_ascii=False, indent=2)

        # 2. Запись memory.json
        m_storage.parent.mkdir(parents=True, exist_ok=True)
        m_tmp = m_storage.with_suffix(".tmp")
        with open(m_tmp, "w", encoding="utf-8") as f:
            json.dump(m_payload, f, ensure_ascii=False, indent=2)

        # Атомарное перемещение
        if h_storage.exists():
            os.replace(h_tmp, h_storage)
        else:
            h_tmp.rename(h_storage)

        if m_storage.exists():
            os.replace(m_tmp, m_storage)
        else:
            m_tmp.rename(m_storage)

    except Exception as write_err:
        logger.error(f"Ошибка при импорте данных, выполняется откат: {write_err}", exc_info=True)
        # Откат к снимкам
        try:
            if h_backup_bytes is not None:
                h_storage.write_bytes(h_backup_bytes)
            elif h_storage.exists():
                h_storage.unlink()

            if m_backup_bytes is not None:
                m_storage.write_bytes(m_backup_bytes)
            elif m_storage.exists():
                m_storage.unlink()
        except Exception as rollback_err:
            logger.critical(f"Критическая ошибка при откате импорта: {rollback_err}", exc_info=True)

        return {
            "success": False,
            "error": f"Ошибка импорта данных (выполнен откат): {write_err}"
        }

    # 3. Горячее обновление данных в памяти менеджеров
    try:
        if hasattr(h_mgr, "reload") and callable(h_mgr.reload):
            h_mgr.reload()
        if hasattr(m_mgr, "reload") and callable(m_mgr.reload):
            m_mgr.reload()
    except Exception as reload_err:
        logger.warning(f"Данные сохранены на диск, но возникла ошибка при обновлении объектов в памяти: {reload_err}")

    stats = backup_dict.get("stats", {
        "tasks_count": len(h_payload.get("tasks", [])),
        "reminders_count": len(h_payload.get("reminders", [])),
        "notes_count": len(h_payload.get("notes", [])),
        "lists_count": len(h_payload.get("lists", {})),
        "memories_count": len(m_payload.get("memories", [])),
    })

    logger.info(f"Данные успешно импортированы из {input_path}")
    return {
        "success": True,
        "path": str(Path(input_path).resolve()),
        "filename": Path(input_path).name,
        "stats": stats,
        "message": f"Данные успешно восстановлены из {Path(input_path).name}."
    }
