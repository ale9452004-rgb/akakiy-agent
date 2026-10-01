"""
Тесты интеграции Desktop Hub (GUI 2.0) с жизненным циклом Domain Agent:
1. Обработка событий action_observed: before_agent, agent_progress, after_agent в AkakiyGUI._poll_queue.
2. Обновление состояния ядра и статусов HomeView (Hero/Neural Core status badge & description).
3. Отображение компактных бейджей доменных агентов в ChatView и записей AGENT / STEP в системном логе.
4. Формирование record_work_result с domain_badge и предотвращение подмены Teamwork на единичный агент.
5. Возврат в равновесное состояние (idle / success) после завершения выполнения.
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from gui import AkakiyGUI
from tools.household import HouseholdManager
from tools.agents.result import AgentResult


class TestDesktopHubDomainAgentEvents(unittest.TestCase):
    """Тестирование реакции Desktop Hub на события жизненного цикла доменных агентов."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_domain_hub_events.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.mock_agent = MagicMock()

        self.gui = AkakiyGUI(
            root=self.root,
            agent=self.mock_agent,
            household=self.household,
            voice=MagicMock()
        )

    def tearDown(self):
        try:
            self.gui.destroy()
        except Exception:
            try:
                self.root.destroy()
            except Exception:
                pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_before_agent_updates_state_and_hero(self):
        """Проверяет, что before_agent переводит UI в working, обновляет Hero статус и добавляет AGENT лог."""
        self.gui.queue.put(("action_observed", ("before_agent", {
            "agent": "household",
            "display_name": "Домашние дела",
            "task": "создай задачу Купить чай",
        })))
        self.gui._poll_queue()

        # UI переведён в working
        self.assertEqual(self.gui.current_state, "working")
        self.assertEqual(self.gui._active_agent_name, "🏠 Домашние дела")
        self.assertEqual(self.gui._active_agent_step, "Маршрутизация…")

        # HomeView badge и описание обновлены
        if self.gui.home_view and self.gui.home_view.lbl_status_badge:
            badge_text = self.gui.home_view.lbl_status_badge.cget("text")
            self.assertIn("ДОМАШНИЕ ДЕЛА", badge_text)
            desc_text = self.gui.home_view.lbl_status_desc.cget("text")
            self.assertEqual(desc_text, "Маршрутизация…")

        # Проверка добавления в системный лог
        last_log = self.gui.log_messages[-1]
        self.assertEqual(last_log[0], "AGENT")
        self.assertIn("Домашние дела", last_log[1])

    def test_agent_progress_updates_step_and_log(self):
        """Проверяет последовательное обновление шагов через agent_progress."""
        # 1. Запуск
        self.gui.queue.put(("action_observed", ("before_agent", {
            "agent": "research",
            "display_name": "Исследования",
            "task": "исследуй тему",
        })))
        self.gui._poll_queue()

        # 2. Первый шаг
        self.gui.queue.put(("action_observed", ("agent_progress", {
            "agent": "research",
            "display_name": "Исследования",
            "step": "Исследую запрос…",
        })))
        self.gui._poll_queue()

        self.assertEqual(self.gui._active_agent_step, "Исследую запрос…")
        if self.gui.home_view and self.gui.home_view.lbl_status_desc:
            self.assertEqual(self.gui.home_view.lbl_status_desc.cget("text"), "Исследую запрос…")
        self.assertEqual(self.gui.log_messages[-1][0], "STEP")
        self.assertIn("Исследую запрос…", self.gui.log_messages[-1][1])

        # 3. Второй шаг
        self.gui.queue.put(("action_observed", ("agent_progress", {
            "agent": "research",
            "display_name": "Исследования",
            "step": "Анализирую результаты…",
        })))
        self.gui._poll_queue()
        self.assertEqual(self.gui._active_agent_step, "Анализирую результаты…")

        # 4. Третий шаг
        self.gui.queue.put(("action_observed", ("agent_progress", {
            "agent": "research",
            "display_name": "Исследования",
            "step": "Формирую отчёт…",
        })))
        self.gui._poll_queue()
        self.assertEqual(self.gui._active_agent_step, "Формирую отчёт…")

    def test_after_agent_logs_completion(self):
        """Проверяет логирование завершения агента при after_agent."""
        self.gui.queue.put(("action_observed", ("before_agent", {
            "agent": "household",
            "display_name": "Домашние дела",
            "task": "купить чай",
        })))
        self.gui.queue.put(("action_observed", ("after_agent", {
            "agent": "household",
            "display_name": "Домашние дела",
            "success": True,
        })))
        self.gui._poll_queue()

        last_log = self.gui.log_messages[-1]
        self.assertEqual(last_log[0], "DONE")
        self.assertIn("Домашние дела завершил работу", last_log[1])

    def test_process_result_displays_domain_badge_in_chat(self):
        """Проверяет отображение бейджа домена в чате при получении process_result."""
        # Симулируем предварительное событие before_agent
        self.gui.queue.put(("action_observed", ("before_agent", {
            "agent": "household",
            "display_name": "Домашние дела",
            "task": "создай задачу Купить чай",
        })))
        self.gui._poll_queue()

        # Приходит результат
        res = AgentResult.ok(message="Задача 'Купить чай' успешно добавлена.")
        self.gui.queue.put(("process_result", {
            "type": "household",
            "display_name": "Домашние дела",
            "answer": "Задача 'Купить чай' успешно добавлена.",
            "success": True,
            "result": res,
        }))
        self.gui._poll_queue()

        # Проверяем историю сообщений чата: кортеж (author, message, time_str, artifacts, domain_badge)
        last_chat = self.gui.chat_messages[-1]
        self.assertEqual(last_chat[0], "Акакий")
        self.assertIn("Задача 'Купить чай' успешно добавлена.", last_chat[1])
        self.assertEqual(last_chat[4], "🏠 Домашние дела")

        # Проверяем, что состояние сброшено в success и активный агент сброшен
        self.assertEqual(self.gui.current_state, "success")
        self.assertIsNone(self.gui._active_agent_name)
        self.assertIsNone(self.gui._active_agent_step)

    def test_record_work_result_maps_domain_badges(self):
        """Проверяет маппинг типов и domain_badge в record_work_result."""
        # Household
        entry_h = self.gui.record_work_result({
            "type": "household",
            "message": "Задача создана",
            "success": True,
        })
        self.assertEqual(entry_h["domain_badge"], "🏠 Домашние дела")
        self.assertEqual(entry_h["title"], "Домашние дела")

        # Research
        entry_r = self.gui.record_work_result({
            "type": "research",
            "message": "Отчет готов",
            "success": True,
        })
        self.assertEqual(entry_r["domain_badge"], "🔍 Исследования")
        self.assertEqual(entry_r["title"], "Аналитическое исследование")

        # Teamwork/Plan - не должен подменяться одиночным доменным агентом!
        entry_p = self.gui.record_work_result({
            "type": "plan_execution",
            "message": "План выполнен",
            "success": True,
        })
        self.assertIsNone(entry_p["domain_badge"])
        self.assertEqual(entry_p["title"], "Исполнение плана")

    def test_home_view_recent_activity_shows_domain_badge(self):
        """Проверяет, что карточки недавней активности на HomeView показывают бейдж домена."""
        self.gui.record_work_result({
            "type": "household",
            "message": "Задача добавлена в список",
            "success": True,
        })
        self.gui.switch_view("home")
        self.gui.home_view.refresh()

        # Проверяем список recent_work_results
        self.assertTrue(len(self.gui.recent_work_results) > 0)
        latest = self.gui.recent_work_results[-1]
        self.assertEqual(latest["domain_badge"], "🏠 Домашние дела")


if __name__ == "__main__":
    unittest.main()
