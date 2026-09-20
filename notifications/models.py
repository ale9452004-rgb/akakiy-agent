"""
Модели данных для модульной системы уведомлений Акакия.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


@dataclass
class NotificationAction:
    """Действие (кнопка) внутри окна уведомления."""
    label: str
    callback: Callable[[], None]
    style: str = "primary"  # "primary", "secondary", "success", "danger"


@dataclass
class NotificationItem:
    """Модель данных уведомления."""
    id: str
    title: str
    text: str
    notification_type: str = "reminder"  # "reminder", "info", "warning", "success", "error"
    created_at: datetime = field(default_factory=datetime.now)
    timestamp_str: str = ""
    actions: List[NotificationAction] = field(default_factory=list)
    on_close: Optional[Callable[[], None]] = None
    data: Dict[str, Any] = field(default_factory=dict)
