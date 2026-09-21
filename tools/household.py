"""
Модуль бытового ассистента Акакия (HouseholdManager).

Обеспечивает:
1. Задачи (Tasks) — создание, список, отметка выполнения, удаление.
2. Напоминания (Reminders) — создание, список, удаление, проверка наступивших.
3. Заметки (Notes) — создание, список, поиск по тексту, удаление.
4. Списки (Lists) — создание списка, добавление/выполнение/удаление пунктов, удаление списка.
5. Изолированное хранение в data/household.json с атомарной записью.
6. Потокобезопасность (threading.RLock).
"""

from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from config import PROJECT_PATH

logger = logging.getLogger(__name__)

DEFAULT_HOUSEHOLD_FILE = PROJECT_PATH / "data" / "household.json"

from tools.datetime_utils import parse_reminder_time


class HouseholdManager:
    """
    Менеджер бытовых задач, заметок, напоминаний и списков.
    """

    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        self.storage_path = Path(storage_path) if storage_path else DEFAULT_HOUSEHOLD_FILE
        self._lock = threading.RLock()
        self._ensure_storage_dir()

        self.tasks: List[Dict[str, Any]] = []
        self.reminders: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []
        self.lists: Dict[str, List[Dict[str, Any]]] = {}
        self.counters: Dict[str, int] = {"task": 0, "reminder": 0, "note": 0}

        self._load()

    def _ensure_storage_dir(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Не удалось создать директорию {self.storage_path.parent}: {e}")

    def reload(self):
        """Перечитывает данные с диска в память."""
        self._load()

    def _load(self):
        with self._lock:
            if not self.storage_path.exists():
                self.tasks = []
                self.reminders = []
                self.notes = []
                self.lists = {}
                self.counters = {"task": 0, "reminder": 0, "note": 0}
                return
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.tasks = data.get("tasks", [])
                        self.reminders = data.get("reminders", [])
                        self.notes = data.get("notes", [])
                        self.lists = data.get("lists", {})
                        self.counters = data.get("counters", {})
                        if "task" not in self.counters:
                            self.counters["task"] = max([t.get("id", 0) for t in self.tasks], default=0)
                        if "reminder" not in self.counters:
                            self.counters["reminder"] = max([r.get("id", 0) for r in self.reminders], default=0)
                        if "note" not in self.counters:
                            self.counters["note"] = max([n.get("id", 0) for n in self.notes], default=0)
            except Exception as e:
                logger.error(f"Ошибка загрузки {self.storage_path}: {e}")

    def _save(self) -> bool:
        with self._lock:
            self._ensure_storage_dir()
            payload = {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "counters": self.counters,
                "tasks": self.tasks,
                "reminders": self.reminders,
                "notes": self.notes,
                "lists": self.lists,
            }
            try:
                tmp_path = self.storage_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                if self.storage_path.exists():
                    os.replace(tmp_path, self.storage_path)
                else:
                    tmp_path.rename(self.storage_path)
                return True
            except Exception as e:
                logger.error(f"Ошибка сохранения {self.storage_path}: {e}")
                return False

    # =========================================================================
    # 1. Задачи (Tasks)
    # =========================================================================

    def create_task(self, title: str) -> Dict[str, Any]:
        """Создаёт новую бытовую задачу."""
        clean_title = str(title).strip() if title else ""
        if not clean_title:
            return {"success": False, "error": "Название задачи не может быть пустым."}

        with self._lock:
            base_max = max([t.get("id", 0) for t in self.tasks], default=0)
            next_id = max(self.counters.get("task", 0), base_max) + 1
            self.counters["task"] = next_id
            task = {
                "id": next_id,
                "title": clean_title,
                "completed": False,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.tasks.append(task)
            self._save()
            return {
                "success": True,
                "message": f"Задача #{next_id} \"{clean_title}\" создана.",
                "task": task
            }

    def list_tasks(self, status: str = "all") -> Dict[str, Any]:
        """Возвращает список задач с возможностью фильтрации (all/pending/completed)."""
        with self._lock:
            norm_status = str(status).strip().lower()
            if norm_status in ("pending", "active", "open", "новые", "активные"):
                items = [t for t in self.tasks if not t.get("completed")]
            elif norm_status in ("completed", "done", "выполненные"):
                items = [t for t in self.tasks if t.get("completed")]
            else:
                items = list(self.tasks)

            if not items:
                return {
                    "success": True,
                    "tasks": [],
                    "message": "Список задач пуст."
                }

            lines = ["Список задач:"]
            for t in items:
                mark = "[x]" if t.get("completed") else "[ ]"
                lines.append(f"  {mark} #{t['id']}: {t['title']}")

            return {
                "success": True,
                "tasks": items,
                "message": "\n".join(lines)
            }

    def complete_task(self, task_id: Union[int, str]) -> Dict[str, Any]:
        """Отмечает задачу выполненной по ID или названию."""
        with self._lock:
            target = None
            try:
                t_int = int(str(task_id).lstrip("#"))
                target = next((t for t in self.tasks if t.get("id") == t_int), None)
            except ValueError:
                pass

            if target is None:
                norm_query = str(task_id).strip().lower()
                target = next((t for t in self.tasks if norm_query in t.get("title", "").lower()), None)

            if target is None:
                return {"success": False, "error": f"Задача '{task_id}' не найдена."}

            target["completed"] = True
            target["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save()
            return {
                "success": True,
                "message": f"Задача #{target['id']} \"{target['title']}\" выполнена.",
                "task": target
            }

    def _resolve_delete_targets(
        self,
        query: Any,
        collection: List[Dict[str, Any]],
        single_name: str,
        plural_name: str
    ) -> Tuple[List[int], Optional[str]]:
        """
        Разрешает цели для удаления:
        - Относительные указатели: 'последняя', 'последнюю', 'последние N', 'последние три/две/одну'
        - Множественные ID: '1, 2, 3', '#1, #2', '1 2 3'
        - Одиночный ID: 5 или '#5'
        - Подстрока названия/текста: 'купить хлеб'
        Возвращает кортеж (список_индексов, сообщение_об_ошибке_если_нет).
        """
        if not collection:
            return [], f"Нет {plural_name} для удаления."

        q_str = str(query).strip().lower()
        if not q_str:
            return [], f"Не указан идентификатор или описание для удаления {plural_name}."

        rus_nums = {
            "одну": 1, "один": 1, "одна": 1,
            "две": 2, "два": 2,
            "три": 3, "трех": 3, "трёх": 3,
            "четыре": 4, "четырех": 4, "четырёх": 4,
            "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
        }

        # 1. Проверка относительного удаления: 'последнюю', 'последняя', 'последний', 'последнее'
        if re.match(r"^(?:удали(?:ть)?\s+)?последн(?:юю|яя|ий|ее)(?:\s+(?:заметк[уа-я]*|задач[уа-я]*|напоминан[иеа-я]*))?$", q_str):
            return [len(collection) - 1], None

        # 'последние N', 'последние три'
        rel_match = re.match(
            r"^(?:удали(?:ть)?\s+)?(?:все\s+)?последн(?:ие|их)\s+(\d+|[а-яё]+)(?:\s+(?:заметк[иа-я]*|задач[иа-я]*|напоминан[иа-я]*))?$",
            q_str
        )
        if rel_match:
            num_raw = rel_match.group(1).lower()
            if num_raw.isdigit():
                count = int(num_raw)
            else:
                count = rus_nums.get(num_raw, 0)
            if count > 0:
                actual_count = min(count, len(collection))
                return list(range(len(collection) - actual_count, len(collection))), None

        # 2. Проверка множественных ID: '1, 2, 3', '#1, #2', '1 2 3', '1,2,3'
        id_tokens = re.findall(r"#?(\d+)\b", q_str)
        non_id_chars = re.sub(r"[#\d\s,и]+", "", q_str)
        if id_tokens and not non_id_chars:
            target_ids = [int(tok) for tok in id_tokens]
            matched_indices = []
            found_ids = set()
            for idx, item in enumerate(collection):
                if item.get("id") in target_ids:
                    matched_indices.append(idx)
                    found_ids.add(item.get("id"))
            if not matched_indices:
                return [], f"{single_name.capitalize()} с номерами ({', '.join(str(i) for i in target_ids)}) не найдены."
            return matched_indices, None

        # 3. Одиночный ID
        try:
            exact_id = int(q_str.lstrip("#"))
            for idx, item in enumerate(collection):
                if item.get("id") == exact_id:
                    return [idx], None
        except ValueError:
            pass

        # 4. Поиск по заголовку или тексту
        for idx, item in enumerate(collection):
            item_text = str(item.get("title", "") or item.get("text", "")).lower()
            if q_str in item_text:
                return [idx], None

        return [], f"{single_name.capitalize()} '{query}' не найдена."

    def delete_task(self, task_id: Union[int, str]) -> Dict[str, Any]:
        """Удаляет одну или несколько задач по ID, относительному положению или названию."""
        with self._lock:
            indices, err = self._resolve_delete_targets(task_id, self.tasks, "задача", "задач")
            if err or not indices:
                return {"success": False, "error": err or f"Задача '{task_id}' не найдена."}

            indices.sort(reverse=True)
            deleted = [self.tasks.pop(idx) for idx in indices]
            deleted.reverse()
            self._save()

            if len(deleted) == 1:
                msg = f"Задача #{deleted[0]['id']} \"{deleted[0]['title']}\" удалена."
            else:
                ids_str = ", ".join(f"#{t['id']}" for t in deleted)
                msg = f"Удалены {len(deleted)} задач: {ids_str}."

            return {
                "success": True,
                "message": msg,
                "deleted": deleted if len(deleted) > 1 else deleted[0],
                "count": len(deleted)
            }

    # =========================================================================
    # 2. Напоминания (Reminders)
    # =========================================================================

    def create_reminder(self, text: str, remind_at: str) -> Dict[str, Any]:
        """Создаёт напоминание."""
        clean_text = str(text).strip() if text else ""
        if not clean_text:
            return {"success": False, "error": "Текст напоминания не может быть пустым."}

        ok, formatted_time, _ = parse_reminder_time(str(remind_at))
        if not ok:
            return {"success": False, "error": formatted_time}

        with self._lock:
            base_max = max([r.get("id", 0) for r in self.reminders], default=0)
            next_id = max(self.counters.get("reminder", 0), base_max) + 1
            self.counters["reminder"] = next_id
            reminder = {
                "id": next_id,
                "text": clean_text,
                "remind_at": formatted_time,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "triggered": False
            }
            self.reminders.append(reminder)
            self._save()
            return {
                "success": True,
                "message": f"Напоминание #{next_id} \"{clean_text}\" установлено на {formatted_time}.",
                "reminder": reminder
            }

    def list_reminders(self, include_triggered: bool = False) -> Dict[str, Any]:
        """Возвращает список напоминаний."""
        with self._lock:
            if include_triggered:
                items = list(self.reminders)
            else:
                items = [r for r in self.reminders if not r.get("triggered")]

            if not items:
                return {
                    "success": True,
                    "reminders": [],
                    "message": "Нет активных напоминаний."
                }

            lines = ["Список напоминаний:"]
            for r in items:
                status = " (сработало)" if r.get("triggered") else ""
                lines.append(f"  • #{r['id']} [{r['remind_at']}]: {r['text']}{status}")

            return {
                "success": True,
                "reminders": items,
                "message": "\n".join(lines)
            }

    def delete_reminder(self, reminder_id: Union[int, str]) -> Dict[str, Any]:
        """Удаляет одно или несколько напоминаний по ID, относительному положению или тексту."""
        with self._lock:
            indices, err = self._resolve_delete_targets(reminder_id, self.reminders, "напоминание", "напоминаний")
            if err or not indices:
                return {"success": False, "error": err or f"Напоминание '{reminder_id}' не найдено."}

            indices.sort(reverse=True)
            deleted = [self.reminders.pop(idx) for idx in indices]
            deleted.reverse()
            self._save()

            if len(deleted) == 1:
                msg = f"Напоминание #{deleted[0]['id']} \"{deleted[0]['text']}\" удалено."
            else:
                ids_str = ", ".join(f"#{r['id']}" for r in deleted)
                msg = f"Удалены {len(deleted)} напоминаний: {ids_str}."

            return {
                "success": True,
                "message": msg,
                "deleted": deleted if len(deleted) > 1 else deleted[0],
                "count": len(deleted)
            }

    def check_due_reminders(self, current_time: Optional[str] = None) -> Dict[str, Any]:
        """
        Проверяет, какие напоминания наступили относительно current_time (по умолчанию сейчас),
        помечает их сработавшими (triggered = True) и возвращает их.
        """
        with self._lock:
            if current_time:
                try:
                    now_str = current_time.strip()
                except Exception:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            due = []
            for r in self.reminders:
                if not r.get("triggered") and r.get("remind_at", "") <= now_str:
                    r["triggered"] = True
                    r["triggered_at"] = now_str
                    due.append(r)

            if due:
                self._save()
                lines = [f"Наступили напоминания ({len(due)}):"]
                for r in due:
                    lines.append(f"  🔔 #{r['id']}: {r['text']} (время: {r['remind_at']})")
                return {
                    "success": True,
                    "due_count": len(due),
                    "reminders": due,
                    "message": "\n".join(lines)
                }

            return {
                "success": True,
                "due_count": 0,
                "reminders": [],
                "message": "Наступивших напоминаний нет."
            }

    # =========================================================================
    # 3. Заметки (Notes)
    # =========================================================================

    def create_note(self, title: str, content: str = "") -> Dict[str, Any]:
        """Создаёт новую заметку."""
        clean_title = str(title).strip() if title else ""
        clean_content = str(content).strip() if content else ""
        if not clean_title and not clean_content:
            return {"success": False, "error": "Заметка не может быть пустой."}

        with self._lock:
            base_max = max([n.get("id", 0) for n in self.notes], default=0)
            next_id = max(self.counters.get("note", 0), base_max) + 1
            self.counters["note"] = next_id
            note = {
                "id": next_id,
                "title": clean_title or f"Заметка #{next_id}",
                "content": clean_content,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.notes.append(note)
            self._save()
            return {
                "success": True,
                "message": f"Заметка #{next_id} \"{note['title']}\" сохранена.",
                "note": note
            }

    def list_notes(self) -> Dict[str, Any]:
        """Возвращает список всех заметок."""
        with self._lock:
            if not self.notes:
                return {"success": True, "notes": [], "message": "Заметок нет."}

            lines = ["Список заметок:"]
            for n in self.notes:
                preview = n.get("content", "")
                if len(preview) > 60:
                    preview = preview[:57] + "..."
                lines.append(f"  • #{n['id']} \"{n['title']}\": {preview}")

            return {
                "success": True,
                "notes": self.notes,
                "message": "\n".join(lines)
            }

    def search_notes(self, query: str) -> Dict[str, Any]:
        """Ищет заметки по ключевым словам в заголовке или тексте."""
        clean_query = str(query).strip().lower() if query else ""
        if not clean_query:
            return self.list_notes()

        with self._lock:
            matches = []
            for n in self.notes:
                t = n.get("title", "").lower()
                c = n.get("content", "").lower()
                if clean_query in t or clean_query in c:
                    matches.append(n)

            if not matches:
                return {
                    "success": True,
                    "notes": [],
                    "message": f"По запросу \"{query}\" заметки не найдены."
                }

            lines = [f"Найденные заметки по запросу \"{query}\":"]
            for n in matches:
                lines.append(f"  • #{n['id']} \"{n['title']}\": {n['content']}")

            return {
                "success": True,
                "notes": matches,
                "message": "\n".join(lines)
            }

    def delete_note(self, note_id: Union[int, str]) -> Dict[str, Any]:
        """Удаляет одну или несколько заметок по ID, относительному положению или заголовку."""
        with self._lock:
            indices, err = self._resolve_delete_targets(note_id, self.notes, "заметка", "заметок")
            if err or not indices:
                return {"success": False, "error": err or f"Заметка '{note_id}' не найдена."}

            indices.sort(reverse=True)
            deleted = [self.notes.pop(idx) for idx in indices]
            deleted.reverse()
            self._save()

            if len(deleted) == 1:
                msg = f"Заметка #{deleted[0]['id']} \"{deleted[0]['title']}\" удалена."
            else:
                ids_str = ", ".join(f"#{n['id']}" for n in deleted)
                msg = f"Удалены {len(deleted)} заметок: {ids_str}."

            return {
                "success": True,
                "message": msg,
                "deleted": deleted if len(deleted) > 1 else deleted[0],
                "count": len(deleted)
            }

    # =========================================================================
    # 4. Списки (Lists)
    # =========================================================================

    def create_list(self, name: str) -> Dict[str, Any]:
        """Создаёт новый именованный список."""
        clean_name = str(name).strip().lower() if name else ""
        if not clean_name:
            return {"success": False, "error": "Имя списка не может быть пустым."}

        with self._lock:
            if clean_name in self.lists:
                return {
                    "success": False,
                    "error": f"Список \"{clean_name}\" уже существует."
                }

            self.lists[clean_name] = []
            self._save()
            return {
                "success": True,
                "message": f"Список \"{clean_name}\" создан.",
                "list_name": clean_name
            }

    def show_list(self, name: str = "") -> Dict[str, Any]:
        """
        Показывает содержимое конкретного списка или перечень всех списков, если имя не указано.
        """
        clean_name = str(name).strip().lower() if name else ""

        with self._lock:
            if not clean_name:
                if not self.lists:
                    return {"success": True, "lists": [], "message": "Списков пока нет."}
                lines = ["Доступные списки:"]
                for l_name, items in self.lists.items():
                    pending = sum(1 for i in items if not i.get("completed"))
                    lines.append(f"  • {l_name} ({len(items)} пунктов, {pending} активных)")
                return {
                    "success": True,
                    "lists": list(self.lists.keys()),
                    "message": "\n".join(lines)
                }

            if clean_name not in self.lists:
                return {"success": False, "error": f"Список \"{clean_name}\" не найден."}

            items = self.lists[clean_name]
            if not items:
                return {
                    "success": True,
                    "list_name": clean_name,
                    "items": [],
                    "message": f"Список \"{clean_name}\" пуст."
                }

            lines = [f"Список \"{clean_name}\":"]
            for it in items:
                mark = "[x]" if it.get("completed") else "[ ]"
                lines.append(f"  {mark} #{it['id']}: {it['text']}")

            return {
                "success": True,
                "list_name": clean_name,
                "items": items,
                "message": "\n".join(lines)
            }

    def add_list_item(self, list_name: str, text: str) -> Dict[str, Any]:
        """Добавляет элемент в список (создаёт список, если он не существовал)."""
        clean_name = str(list_name).strip().lower() if list_name else ""
        clean_text = str(text).strip() if text else ""
        if not clean_name or not clean_text:
            return {"success": False, "error": "Имя списка и текст пункта не могут быть пустыми."}

        with self._lock:
            if clean_name not in self.lists:
                self.lists[clean_name] = []

            items = self.lists[clean_name]
            next_id = max([it.get("id", 0) for it in items], default=0) + 1
            item = {
                "id": next_id,
                "text": clean_text,
                "completed": False,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            items.append(item)
            self._save()
            return {
                "success": True,
                "message": f"В список \"{clean_name}\" добавлен пункт #{next_id}: \"{clean_text}\".",
                "item": item
            }

    def complete_list_item(self, list_name: str, item_id: Union[int, str]) -> Dict[str, Any]:
        """Отмечает пункт списка выполненным."""
        clean_name = str(list_name).strip().lower() if list_name else ""
        if clean_name not in self.lists:
            return {"success": False, "error": f"Список \"{clean_name}\" не найден."}

        with self._lock:
            items = self.lists[clean_name]
            target = None
            try:
                i_int = int(str(item_id).lstrip("#"))
                target = next((it for it in items if it.get("id") == i_int), None)
            except ValueError:
                pass

            if target is None:
                norm_query = str(item_id).strip().lower()
                target = next((it for it in items if norm_query in it.get("text", "").lower()), None)

            if target is None:
                return {"success": False, "error": f"Пункт '{item_id}' в списке \"{clean_name}\" не найден."}

            target["completed"] = True
            self._save()
            return {
                "success": True,
                "message": f"Пункт #{target['id']} \"{target['text']}\" в списке \"{clean_name}\" выполнен.",
                "item": target
            }

    def delete_list_item(self, list_name: str, item_id: Union[int, str]) -> Dict[str, Any]:
        """Удаляет пункт из списка."""
        clean_name = str(list_name).strip().lower() if list_name else ""
        if clean_name not in self.lists:
            return {"success": False, "error": f"Список \"{clean_name}\" не найден."}

        with self._lock:
            items = self.lists[clean_name]
            target_idx = None
            try:
                i_int = int(str(item_id).lstrip("#"))
                for idx, it in enumerate(items):
                    if it.get("id") == i_int:
                        target_idx = idx
                        break
            except ValueError:
                pass

            if target_idx is None:
                norm_query = str(item_id).strip().lower()
                for idx, it in enumerate(items):
                    if norm_query in it.get("text", "").lower():
                        target_idx = idx
                        break

            if target_idx is None:
                return {"success": False, "error": f"Пункт '{item_id}' в списке \"{clean_name}\" не найден."}

            deleted = items.pop(target_idx)
            self._save()
            return {
                "success": True,
                "message": f"Пункт #{deleted['id']} \"{deleted['text']}\" удалён из списка \"{clean_name}\".",
                "deleted": deleted
            }

    def delete_list(self, name: str) -> Dict[str, Any]:
        """Удаляет список целиком."""
        clean_name = str(name).strip().lower() if name else ""
        with self._lock:
            if clean_name not in self.lists:
                return {"success": False, "error": f"Список \"{clean_name}\" не найден."}

            deleted_items = self.lists.pop(clean_name)
            self._save()
            return {
                "success": True,
                "message": f"Список \"{clean_name}\" (содержал {len(deleted_items)} элементов) удалён.",
                "deleted_name": clean_name
            }


# =============================================================================
# Синглтон и экспортируемые функции инструментов
# =============================================================================

_global_household_manager: Optional[HouseholdManager] = None
_global_household_lock = threading.Lock()


def get_household_manager(storage_path: Optional[Union[str, Path]] = None) -> HouseholdManager:
    """Возвращает глобальный синглтон HouseholdManager."""
    global _global_household_manager
    with _global_household_lock:
        if _global_household_manager is None:
            _global_household_manager = HouseholdManager(storage_path=storage_path)
        return _global_household_manager


def reset_household_manager() -> None:
    """Сбрасывает синглтон (для изолированных тестов)."""
    global _global_household_manager
    with _global_household_lock:
        _global_household_manager = None


# Обертки инструментов для tools.registry:
def create_task(title: str) -> Dict[str, Any]:
    return get_household_manager().create_task(title=title)

def list_tasks(status: str = "all") -> Dict[str, Any]:
    return get_household_manager().list_tasks(status=status)

def complete_task(task_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().complete_task(task_id=task_id)

def delete_task(task_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().delete_task(task_id=task_id)

def create_reminder(text: str, remind_at: str) -> Dict[str, Any]:
    return get_household_manager().create_reminder(text=text, remind_at=remind_at)

def list_reminders(include_triggered: bool = False) -> Dict[str, Any]:
    return get_household_manager().list_reminders(include_triggered=include_triggered)

def delete_reminder(reminder_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().delete_reminder(reminder_id=reminder_id)

def check_due_reminders(current_time: Optional[str] = None) -> Dict[str, Any]:
    return get_household_manager().check_due_reminders(current_time=current_time)

def create_note(title: str, content: str = "") -> Dict[str, Any]:
    return get_household_manager().create_note(title=title, content=content)

def list_notes() -> Dict[str, Any]:
    return get_household_manager().list_notes()

def search_notes(query: str) -> Dict[str, Any]:
    return get_household_manager().search_notes(query=query)

def delete_note(note_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().delete_note(note_id=note_id)

def create_list(name: str) -> Dict[str, Any]:
    return get_household_manager().create_list(name=name)

def show_list(name: str = "") -> Dict[str, Any]:
    return get_household_manager().show_list(name=name)

def add_list_item(list_name: str, text: str) -> Dict[str, Any]:
    return get_household_manager().add_list_item(list_name=list_name, text=text)

def complete_list_item(list_name: str, item_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().complete_list_item(list_name=list_name, item_id=item_id)

def delete_list_item(list_name: str, item_id: Union[int, str]) -> Dict[str, Any]:
    return get_household_manager().delete_list_item(list_name=list_name, item_id=item_id)

def delete_list(name: str) -> Dict[str, Any]:
    return get_household_manager().delete_list(name=name)
