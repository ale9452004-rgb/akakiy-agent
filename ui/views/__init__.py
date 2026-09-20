"""
Пакет модульных экранов (Views) для Desktop Hub Акакия 2.0.
"""

from ui.views.base import BaseView, _bind_hover, bind_hover
from ui.views.tasks import TasksView
from ui.views.reminders import RemindersView
from ui.views.notes import NotesView
from ui.views.lists import ListsView
from ui.views.memory import MemoryView
from ui.views.settings import SettingsView

__all__ = [
    "BaseView",
    "_bind_hover",
    "bind_hover",
    "TasksView",
    "RemindersView",
    "NotesView",
    "ListsView",
    "MemoryView",
    "SettingsView",
]
