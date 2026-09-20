"""
Пакет модульных экранов (Views) для Desktop Hub Акакия 2.0.
"""

from ui.views.base import BaseView, _bind_hover, bind_hover
from ui.views.tasks import TasksView
from ui.views.reminders import RemindersView
from ui.views.notes import NotesView
from ui.views.lists import ListsView

__all__ = [
    "BaseView",
    "_bind_hover",
    "bind_hover",
    "TasksView",
    "RemindersView",
    "NotesView",
    "ListsView",
]
