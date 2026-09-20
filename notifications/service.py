"""
Сервис управления уведомлениями (NotificationService) для Акакия.
Централизованно управляет жизненным циклом и стеком окон уведомлений.
"""

from datetime import datetime
import threading
import tkinter as tk
from typing import Callable, Dict, List, Optional
import uuid

from notifications.models import NotificationAction, NotificationItem
from notifications.window import NotificationWindow


class NotificationService:
    """
    Сервис уведомлений.
    Обеспечивает создание, закрытие и аккуратную компоновку всплывающих окон
    в правом нижнем углу экрана.
    """

    DEFAULT_WIDTH = 340
    DEFAULT_HEIGHT = 135
    MARGIN_X = 24
    MARGIN_Y = 56
    STACK_GAP = 12
    MAX_VISIBLE = 4

    def __init__(self, master: tk.Widget):
        self.master = master
        self._active_windows: Dict[str, NotificationWindow] = {}
        self._order: List[str] = []
        self._lock = threading.RLock()

    def notify(self, item: NotificationItem) -> str:
        """
        Создаёт и отображает окно уведомления.
        Потокобезопасен: при вызове из фонового потока перенаправляет в UI-поток.
        """
        if threading.current_thread() is not threading.main_thread():
            self.master.after(0, lambda: self.notify(item))
            return item.id

        with self._lock:
            # Если уведомление с таким ID уже отображается, закрываем старое
            if item.id in self._active_windows:
                self._close_internal(item.id)

            # Если достигнут лимит видимых, закрываем самое старое (вверху стека)
            if len(self._order) >= self.MAX_VISIBLE:
                oldest_id = self._order[-1]
                self._close_internal(oldest_id)

            # Создаём новое окно
            win = NotificationWindow(
                master=self.master,
                item=item,
                on_dismiss=self._on_window_dismissed,
                width=self.DEFAULT_WIDTH,
                height=self.DEFAULT_HEIGHT
            )

            # Добавляем в начало стека (самое нижнее/свежее)
            self._order.insert(0, item.id)
            self._active_windows[item.id] = win

            self._restack()
            return item.id

    def show_reminder(
        self,
        title: str,
        text: str,
        timestamp_str: str = "",
        on_complete: Optional[Callable[[], None]] = None,
        on_snooze: Optional[Callable[[], None]] = None,
        reminder_id: Optional[str] = None
    ) -> str:
        """
        Удобный фасад для напоминания со стандартными действиями:
        '✓ Выполнено' и '⏰ Отложить'.
        """
        notif_id = reminder_id or f"rem_{uuid.uuid4().hex[:8]}"

        actions = []
        if on_complete:
            actions.append(
                NotificationAction(
                    label="✓ Выполнено",
                    callback=on_complete,
                    style="success"
                )
            )
        if on_snooze:
            actions.append(
                NotificationAction(
                    label="⏰ Отложить",
                    callback=on_snooze,
                    style="secondary"
                )
            )

        item = NotificationItem(
            id=notif_id,
            title=title or "Напоминание",
            text=text,
            notification_type="reminder",
            timestamp_str=timestamp_str,
            actions=actions
        )
        return self.notify(item)

    def show_info(self, title: str, text: str) -> str:
        """Фасад для информационного уведомления."""
        notif_id = f"info_{uuid.uuid4().hex[:8]}"
        item = NotificationItem(
            id=notif_id,
            title=title,
            text=text,
            notification_type="info"
        )
        return self.notify(item)

    def close(self, notification_id: str) -> None:
        """Закрытие конкретного уведомления по ID."""
        if threading.current_thread() is not threading.main_thread():
            self.master.after(0, lambda: self.close(notification_id))
            return

        with self._lock:
            self._close_internal(notification_id)

    def close_all(self) -> None:
        """Закрытие всех активных уведомлений."""
        if threading.current_thread() is not threading.main_thread():
            self.master.after(0, self.close_all)
            return

        with self._lock:
            ids = list(self._order)
            for nid in ids:
                self._close_internal(nid)

    def get_active_count(self) -> int:
        """Количество активных окон уведомлений."""
        with self._lock:
            return len(self._order)

    def get_active_ids(self) -> List[str]:
        """Список идентификаторов активных уведомлений."""
        with self._lock:
            return list(self._order)

    def _close_internal(self, notification_id: str) -> None:
        """Внутреннее закрытие окна и перекомпоновка стека."""
        if notification_id in self._active_windows:
            win = self._active_windows.pop(notification_id)
            win.on_dismiss = None
            try:
                win.close()
            except Exception:
                pass

        if notification_id in self._order:
            self._order.remove(notification_id)

        self._restack()

    def _on_window_dismissed(self, notification_id: str) -> None:
        """Обратный вызов от окна при закрытии пользователем через крестик."""
        with self._lock:
            if notification_id in self._active_windows:
                del self._active_windows[notification_id]
            if notification_id in self._order:
                self._order.remove(notification_id)
            self._restack()

    def _restack(self) -> None:
        """
        Пересчитывает экранные координаты для всех активных окон
        и выстраивает их в аккуратный вертикальный стек.
        """
        try:
            screen_w = self.master.winfo_screenwidth()
            screen_h = self.master.winfo_screenheight()
        except Exception:
            screen_w = 1920
            screen_h = 1080

        base_x = max(0, screen_w - self.DEFAULT_WIDTH - self.MARGIN_X)
        base_y = max(0, screen_h - self.DEFAULT_HEIGHT - self.MARGIN_Y)

        for i, nid in enumerate(self._order):
            win = self._active_windows.get(nid)
            if win and win.winfo_exists():
                pos_y = max(10, base_y - i * (self.DEFAULT_HEIGHT + self.STACK_GAP))
                win.set_position(base_x, pos_y)
