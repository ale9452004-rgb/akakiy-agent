"""
Независимый фоновый монитор напоминаний (ReminderMonitor).
Обнаруживает наступившие напоминания через HouseholdManager API и уведомляет подписчика.
Не содержит кода Tkinter.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ReminderMonitor:
    """
    Фоновый сервис периодической проверки наступивших напоминаний.
    Использует существующий HouseholdManager.check_due_reminders().
    Гарантирует однократное срабатывание каждого напоминания.
    """

    def __init__(
        self,
        household: Any,
        on_reminder: Callable[[Dict[str, Any]], None],
        interval_sec: float = 5.0
    ):
        self.household = household
        self.on_reminder = on_reminder
        self.interval_sec = max(0.5, float(interval_sec))

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._notified_ids: Set[Any] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Запуск фонового потока проверки."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="ReminderMonitorThread",
                daemon=True
            )
            self._thread.start()
            logger.info("ReminderMonitor запущен.")

    def stop(self, timeout: float = 2.0) -> None:
        """Безопасная остановка фонового потока."""
        with self._lock:
            if not self._thread:
                return
            self._stop_event.set()

        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ReminderMonitor остановлен.")

    def is_running(self) -> bool:
        """Проверка активности потока монитора."""
        return bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())

    def check_now(self, current_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Синхронная проверка наступивших напоминаний.
        Возвращает список напоминаний, которые наступили и для которых был вызван callback.
        """
        if not self.household or not hasattr(self.household, "check_due_reminders"):
            return []

        try:
            res = self.household.check_due_reminders(current_time=current_time)
        except Exception as e:
            logger.error(f"Ошибка вызова check_due_reminders в ReminderMonitor: {e}")
            return []

        if not isinstance(res, dict) or not res.get("success"):
            return []

        due_reminders = res.get("reminders", [])
        dispatched = []

        with self._lock:
            for rem in due_reminders:
                rem_id = rem.get("id")
                if rem_id is None:
                    continue

                if rem.get("repeat"):
                    dedup_key = (rem_id, rem.get("triggered_at") or rem.get("remind_at"))
                else:
                    dedup_key = rem_id

                if dedup_key not in self._notified_ids:
                    self._notified_ids.add(dedup_key)
                    dispatched.append(rem)
                    try:
                        self.on_reminder(rem)
                    except Exception as e:
                        logger.error(f"Ошибка в обработчике on_reminder для напоминания #{rem_id}: {e}")

        return dispatched

    def reset_notified_ids(self) -> None:
        """Сброс множества уже уведомлённых ID (для тестирования или очистки)."""
        with self._lock:
            self._notified_ids.clear()

    def _run_loop(self) -> None:
        """Основной цикл фоновой проверки."""
        while not self._stop_event.is_set():
            try:
                self.check_now()
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в цикле ReminderMonitor: {e}")

            # Ожидание интервала или сигнала завершения
            if self._stop_event.wait(self.interval_sec):
                break
