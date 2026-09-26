# Статус проекта и задачи (Tasks & Roadmap)

Документ отражает текущее состояние проекта **«Акакий»**, историю завершённых этапов и перечень ближайших задач.

---

## 1. Текущий статус проекта

* **Текущая версия**: Акакий 2.0 (Desktop Hub + Voice UX + Household Assistant + Memory + Core Dev Tools + Notifications + Fast CLI REPL + Global Push-to-Talk + Backup & Restore + UI Filter & Pagination + Recurring Reminders & Tasks + Daily Briefing + Audio Notifications & Settings + Sub-Agent Foundation + ImageAgent v1 + VRAM Manager v1 + Image Request Routing + ImageAgent v2 Generation Parameters + Agent Router Robust Routing + AgentContext v2 Foundation Contract + AgentResult v2 & Artifacts Foundation + PresentationAgent v1 Foundation).
* **Состояние кодовой базы**: Стабильное, все тесты пройдены (429 тестов в `tests/`: 427 unit-тестов успешны, 2 интеграционных пропущены по умолчанию; 0 синтаксических ошибок в 1026 Python-файлах).
* **Последний этап**: Этап №7 — PresentationAgent v1: первый специализированный Sub-Agent создания презентаций (.pptx) на базе чистой стандартной библиотеки Python (модель OpenXML, авторазбор задач, интеграция с Artifacts, регистрация в AgentRegistry, роутинг).
* **Ветка**: `master`, синхронизирована с `origin/master`.

---

## 2. Реализованный функционал (Done)

### 2.0. Архитектурный аудит, документация и инфраструктура тестов
- [x] **Вынос утилиты времени в `tools/datetime_utils.py` (Этап R4)**: Чистая функция `parse_reminder_time` вынесена из монолита `tools/household.py` в специализированный модуль `tools/datetime_utils.py`. В `tools/household.py` сохранён прозрачный реэкспорт для 100% обратной совместимости. Разработан специализированный тестовый набор `tests/test_datetime_utils.py` (9 тестов, 100% pass, всего 166 тестов в `tests/`).
- [x] **Вынос экранов Главная и Чат из `gui.py`, завершение этапа R3 (Этап R3.5)**: Из `gui.py` вынесены последние два экрана в отдельные классы `BaseView`: `ui/views/home.py` (`HomeView` с 3D Neural Core и сводными карточками) и `ui/views/chat.py` (`ChatView` с двухколоночным интерфейсом диалога и системного лога). `gui.py` трансформирован в чистый Shell (Topbar, Sidebar, Command Bar, Polling очереди, Voice integration, управление состояниями). Сохранены все фасадные свойства и методы (`chat_text`, `log_text`, `_append_chat`, `_append_log`, `_clear_chat`, `_quick_complete_task`). Реактивное обновление `refresh_current_view()` дополнено вызовами `home_view.refresh()` и `chat_view.refresh()`. Создан тестовый набор `tests/test_home_chat_views.py` (6 тестов, 100% pass, всего 157 тестов в `tests/`).
- [x] **Вынос экранов памяти и настроек из `gui.py` (Этап R3.4)**: Из монолита `gui.py` вынесены экраны `MemoryView` (`ui/views/memory.py`) и `SettingsView` (`ui/views/settings.py`). Сохранены все фасадные методы и прокси-атрибуты (`entry_mem`, `mem_list_frame`, `lbl_val_res`, `_ui_remember`, `_ui_forget`, `_ui_run_validation`). Реактивное обновление `refresh_current_view()` дополнено вызовами `memory_view.refresh()` и `settings_view.refresh()`. Создан тестовый набор `tests/test_memory_settings_views.py` (5 тестов, 100% pass, всего 151 тест в `tests/`).
- [x] **Вынос бытовых экранов из `gui.py` (Этап R3.3)**: Из монолита `gui.py` вынесены 4 бытовых экрана в независимые классы `BaseView`: `ui/views/tasks.py` (`TasksView`), `ui/views/reminders.py` (`RemindersView`), `ui/views/notes.py` (`NotesView`), `ui/views/lists.py` (`ListsView`). В `gui.py` сохранены чистые делегирующие фасады и свойства (`entry_task`, `entry_rem_*`, `entry_note_*`, `entry_new_list`, `entry_item_text`, `tasks_list_frame`, etc.) для 100% обратной совместимости. Обновлён `refresh_current_view()` для обновления через экземпляры Views. Создан тестовый набор `tests/test_household_views.py` (4 теста, 100% pass, всего 146 тестов в `tests/`).
- [x] **Базовая инфраструктура экранов `ui/views/` (Этап R3.2)**: Создан пакет `ui/views/` с базовым классом `BaseView(tk.Frame)` (`ui/views/base.py`) и единым контрактом (`render()`, `refresh()`, доступ к `shell` и сервисам `agent`, `household`, `memory`, `voice` без дублирования, темовые константы). Общая утилита `_bind_hover` вынесена в `ui/views/base.py`. Создан набор тестов `tests/test_base_view.py` (5 тестов, 100% pass, всего 142 теста).
- [x] **Исследование и подготовка разделения GUI (Этап R3.1)**: Проведён детальный аудит всех 51 методов `gui.py`, составлена классификация по 8 экранам и Shell, выявлены и задокументированы все cross-screen зависимости.
- [x] **Стабилизация и регрессионная проверка `CommandRouter` (Этап R2.5)**: Проведена полная регрессионная проверка реальных вызовов через `Agent.process()` по всем 5 направлениям (Household CRUD задач и заметок; память remember/recall/search/forget/clear; проектные команды find/list/search; планирование create/get/clear с поддержкой естественных фраз «создай план ...»; свободные запросы к LLM). Тестовое покрытие расширено до 22 тестов в `test_command_router.py` (всего 137 тестов в `tests/`, 100% pass).
- [x] **Выделение `CommandRouter` (Этап R2)**: Создан модуль [tools/router.py](file:///c:/Akakiy%20agent/tools/router.py) с классом `CommandRouter`. Вся детерминированная маршрутизация CLI-команд проекта, бытовых сущностей (Tasks, Notes, Reminders, Lists), команд памяти и управления планами вынесена из `tools/agent.py`. `Agent.process()` трансформирован в чистый оркестратор. `Agent.choose_tool()` сохранён как фасад. Создан тестовый набор [tests/test_command_router.py](file:///c:/Akakiy%20agent/tests/test_command_router.py).
- [x] **Организация каталога тестов `tests/` (Этап R1)**: Все 9 стабильных наборов тестов перенесены из `scratch/` в официальный пакет `tests/` с `__init__.py`. Запуск через `python -m unittest discover -s tests` (115 тестов, 100% pass). Вспомогательные диагностические утилиты сохранены в `scratch/`.
- [x] **Архитектурный аудит (Task 024)**: Исследование связности `Agent → Router → Skills → Tools`, модулей `gui.py`, `tools/agent.py`, `tools/household.py`, `voice/service.py`, формирование матрицы рефакторинга («что делать / что не трогать») с оценкой рисков.
- [x] **Актуализация проектной документации**: Созданы [ARCHITECTURE.md](file:///c:/Akakiy%20agent/ARCHITECTURE.md), [DECISIONS.md](file:///c:/Akakiy%20agent/DECISIONS.md), [TASKS.md](file:///c:/Akakiy%20agent/TASKS.md), регламент [GEMINI.md](file:///c:/Akakiy%20agent/GEMINI.md) оптимизирован.

### 2.1. Слой представления и интерфейсы
- [x] **Консольный терминал (CLI REPL)**: Интерактивный цикл в `main.py`, форматирование через `cli_formatters.py`.
- [x] **Десктопный хаб GUI 2.0 (`gui.py`)**: Полноэкранный интерфейс (Topbar, Sidebar, Main Workspace, Command Bar).
  - [x] Разделы: Главная, Чат, Задачи, Напоминания, Заметки, Списки, Память, Настройки.
  - [x] Сохранение состояния чата и поля ввода при переключении между разделами.
  - [x] Реактивное обновление карточек и списков при выполнении операций без перезагрузки интерфейса.
  - [x] Потокобезопасная асинхронная очередь `queue.Queue` для событий агента и голоса.
  - [x] Модальные окна подтверждения опасных операций (`request_confirmation`).
- [x] **Модульная система уведомлений (`notifications/`)**:
  - [x] Независимый фоновый монитор напоминаний `ReminderMonitor` без Tkinter (`notifications/monitor.py`).
  - [x] Централизованный сервис `NotificationService` с управлением стеком окон в правом нижнем углу и автоматическим репозиционированием (`notifications/service.py`).
  - [x] Компактные модульные окна `NotificationWindow` (`tk.Toplevel`, `overrideredirect(True)`) в стиле Акакия с кнопками `✓ Выполнено` и `⏰ Отложить` (`notifications/window.py`).
  - [x] Подключение к `AkakiyGUI` через потокобезопасную очередь событий `queue.Queue`.
  - [x] Набор из 14 тестов (`tests/test_notifications.py`), покрывающий весь жизненный цикл (всего 180 тестов в `tests/`).
- [x] **Neural Core (`ui/neural_core.py`)**: Процедурный математический 3D-компонент (нейросфера на `tk.Canvas`), реагирующий на состояния (`idle`, `thinking`, `working`, `listening`, `speaking`, `error`) и громкость микрофона (RMS).


### 2.2. Голосовой интерфейс (Voice UX)
- [x] **Локальное распознавание речи (STT Vosk)**:
  - [x] Адаптивная калибровка фонового аппаратного шума микрофона.
  - [x] Быстрый endpointing (отсечение тишины за 1.1 с, устранение 10–15с задержки).
  - [x] Сохранение Wake Word «Акакий» в распознанном тексте для отображения в UI и логах.
  - [x] Отделение обращения от команды через `strip_wake_word`.
  - [x] Мгновенный ответ на прямое обращение по имени («Да, я здесь! Чем могу помочь?»).
- [x] **Локальный синтез речи (TTS pyttsx3 / SAPI5)**:
  - [x] Фоновый рабочий поток с неблокирующей очередью фраз.
  - [x] Поддержка мгновенного прерывания речи.
  - [x] Голосовые команды выхода («стоп», «хватит», «отключись»).
  - [x] Очистка текстов от разметки Markdown, путей и спецсимволов перед озвучкой (`voice/cleaner.py`).
  - [x] Защита от ложных успешных ответов: ошибки (`success=False`) строго озвучиваются и логируются как ошибки.

### 2.3. Инструменты и бытовой контекст (Household & Memory)
- [x] **Подсистема долговременной памяти (`tools/memory.py`)**:
  - [x] Многоуровневая эвристическая фильтрация системного мусора (трейсбеки, дампы памяти, HTML/XML).
  - [x] Акустическая нормализация для отсечения дубликатов фактов.
  - [x] Потокобезопасное атомарное сохранение в `data/memory.json`.
- [x] **Бытовой ассистент (`tools/household.py`)**:
  - [x] Задачи (Tasks): статус, создание, нумерация, выполнение.
  - [x] Заметки (Notes): заголовок, текст, поиск по содержимому.
  - [x] Списки (Lists): именованные списки, добавление, завершение пунктов.
  - [x] Напоминания (Reminders): даты/время, естественные форматы, статус срабатывания.
  - [x] Потокобезопасное хранение в `data/household.json`.

### 2.4. Долговременная память и контекст
- [x] **Долговременная память (`tools/memory.py`)**: Сохранение фактов, поиск, удаление по ID или подстроке, очистка всей памяти.
- [x] **Фильтрация и дедупликация**: Отсечение системного мусора, дампов ошибок, нормализованное сравнение для предотвращения дубликатов.
- [x] **Изоляция данных в `data/`**: Атомарная запись через `.tmp` и `os.replace`, блокировки `threading.RLock`, исключение из git.
- [x] **Единый ContextManager (`tools/context.py`)**:
  - [x] Скользящее окно краткосрочной памяти (`max_turns=10`).
  - [x] Prompt Injection Shield (чистый системный промпт + справочный блок данных).
  - [x] Контекстный поиск релевантных воспоминаний по ключевым словам.

### 2.5. Ядро, маршрутизация и инструменты разработки
- [x] **Детерминированная маршрутизация (`choose_tool`)**:
  - [x] Быстрый путь для типовых бытовых команд, памяти и CLI (< 1.1 мс).
  - [x] Разгрузка локального процессора от холостых LLM-вызовов.
- [x] **Архитектура навыков (`skills/`)**: Навыки `ProjectSkill`, `MemorySkill`, `HouseholdSkill` со скоупингом системных инструкций и схем инструментов.
- [x] **Native Tool Calling (Ollama `qwen3:8b`)**: Поддержка мульти-раундового вызова инструментов (до 5 раундов за ход) и самовосстановления (self-healing).
- [x] **Инструменты разработчика (`tools/`)**:
  - [x] Файлы: чтение, запись, точечное редактирование, поиск текста, поиск файлов, листинг.
  - [x] Git: статус, диффы, коммиты, история, пуш.
  - [x] Безопасный терминал: выполнение команд PowerShell с подтверждением.
  - [x] Статический анализ: AST-анализ структуры кода `analyze_file`.
  - [x] Валидация: проверка синтаксиса проекта через `py_compile`.
- [x] **Многошаговое планирование (`tools/planner.py`, `tools/plan_executor.py`)**: JSON-планы, пошаговое исполнение с валидацией, отчётность.
- [x] **Подтверждение опасных действий**: Защита деструктивных операций через `requires_confirmation = True`.

---

## 3. Ближайшие задачи (Backlog)

### Архитектурный рефакторинг (По результатам аудита Task 024)
* [x] **Этап R1: Организация каталога тестов `tests/`** (Высокий приоритет, Низкий риск):
  * Создать официальный каталог `tests/` с `__init__.py`.
  * Перенести стабильные тестовые наборы из `scratch/` в `tests/` (`test_household_skill.py`, `test_gui_v2.py`, `test_gui_voice_integration.py`, `test_voice_household_023.py`, `test_context_architecture.py`, `test_skills_architecture.py`, `test_memory_system.py`, `test_stt_adaptive.py`, `test_voice_ux_polish.py`).
  * Обеспечить запуск стандартной командой `python -m unittest discover -s tests`.
* [x] **Этап R2: Выделение `CommandRouter` из `tools/agent.py`** (Высокий приоритет, Средний риск):
  * Вынести детерминированный fast-path парсинг (`choose_tool`) и строковые перехваты памяти/планов в отдельный модуль `tools/router.py`.
  * Устранить затенение команд памяти между `choose_tool()` и `process()`.
  * В `Agent.process()` выстроить прозрачный конвейер: `Router (fast-path) -> Planner -> SkillRegistry -> Ollama Native Tool Calling`.
* [x] **Этап R3: Модуляризация представлений `gui.py` в `ui/views/`** (Средний приоритет, Средний риск):
  * [x] **R3.1**: Аудит и классификация всех 51 методов `gui.py`, карта зависимостей экранов и Shell.
  * [x] **R3.2**: Инфраструктура `BaseView(tk.Frame)` и общие UI-хелперы в `ui/views/base.py`.
  * [x] **R3.3**: Вынос бытовых экранов (`TasksView`, `RemindersView`, `NotesView`, `ListsView`) с сохранением фасадов и атрибутов.
  * [x] **R3.4**: Вынос экранов памяти и настроек (`MemoryView`, `SettingsView`).
  * [x] **R3.5**: Вынос экранов Главная и Чат (`HomeView`, `ChatView`), превращение `gui.py` в компактный Shell (Topbar, Sidebar, Command Bar, Polling, Neural Core).
* [x] **Этап R4: Вынос утилит парсинга времени из `tools/household.py`** (Низкий приоритет, Низкий риск):
  * [x] Вынести чистую функцию `parse_reminder_time` из `tools/household.py` в `tools/datetime_utils.py`.

### Функциональное развитие (Product Backlog)
* [x] **Фоновые уведомления о напоминаниях в GUI**:
  * Реализован независимый фоновый монитор `ReminderMonitor` с дедупликацией наступивших событий.
  * Реализован централизованный сервис `NotificationService` с управлением стеком окон в правом нижнем углу и авторепозиционированием.
  * Реализованы всплывающие окна `NotificationWindow` с действиями «✓ Выполнено» и «⏰ Отложить».
* [x] **Подключение быстрых команд `commands.py` к `main.py`**:
  * Реализован диспетчер быстрых команд `handle_cli_command()` в `commands.py` с короткими алиасами (`:status`, `:files`, `:ls`, `:read <файл>`, `:cat <файл>`, `:help`, `:exit`, `:quit`).
  * Исправлен вывод `show_files()` (поддержка словаря `tools.files.list_files()`), добавлена функция `_safe_print` с защитой от `UnicodeEncodeError` и снятием BOM `\ufeff`.
  * В `main.py` подключены быстрые команды без перехвата естественных запросов к `Agent.process()`.
  * Создан набор тестов `tests/test_cli_commands.py` (17 тестов, 100% pass, всего 197 тестов в `tests/`).
* [x] **Глобальный хоткей Push-to-Talk для голоса**:
  * Реализован `GlobalHotKeyManager` в `voice/hotkey.py` через Win32 API `RegisterHotKey`/`GetMessageW` без внешних зависимостей.
  * Системная комбинация `Ctrl+Shift+Space` активирует голосовой режим из любого приложения Windows.
  * Поддержка двух сценариев: Toggle (быстрое нажатие) и Push-to-Talk (удержание и досрочный сброс фразы `finish_listening()` при отпускании).
  * Защита от повторного/параллельного запуска голосовых сессий; корректное освобождение ресурсов при закрытии GUI (`_on_window_close`).
* [x] **Экспорт и резервное копирование пользовательских данных**:
  * Реализован модуль `tools/backup.py` (`export_data`, `import_data`, `validate_backup`).
  * Единый JSON-архив с версионированием (`akakiy_backup_version = 1`), метаданными приложения и статистикой сущностей.
  * Строгая валидация типов, версий и структуры до модификации хранилищ.
  * Транзакционный импорт с байтовыми снимками файлов в памяти, атомарной заменой `.tmp` $\to$ `os.replace` и автоматическим откатом при сбоях.
  * Защита от сохранения бэкапов внутри рабочей директории `data/`, автоматическое игнорирование `backups/` и `*.backup.json` в `.gitignore`.
  * Горячее обновление данных без перезапуска: методы `reload()` у `HouseholdManager` и `MemoryManager`, вызов `shell.refresh_current_view()`.
  * Интеграция: кнопки «⬆ Экспорт данных...» и «⬇ Импорт данных...» в `SettingsView` с диалогами `filedialog` и подтверждением `messagebox.askyesno`; команды `:export [файл]` и `:import <файл>` в CLI REPL.
* [x] **Поддержка фильтрации и пагинации в GUI (Tasks, Notes, Memory, Lists)**:
  * Реализован независимый модуль `ui/pagination.py` с тремя уровнями: `PaginationModel` (чистая логика без GUI), `PaginationBar` (виджет навигации с кнопками «← / →» и счетчиком страниц) и `PagedListController` (универсальный контроллер списков).
  * Подключена динамическая фильтрация и пагинация к `TasksView` (`page_size=8`, поле поиска по названию и #ID задачи) с сохранением CRUD и обратной совместимости.
  * Подключена динамическая фильтрация и пагинация к `NotesView` (`page_size=6`, поле поиска по названию, тексту и #ID заметки).
  * Подключена динамическая фильтрация и пагинация к `MemoryView` (`page_size=8`, поле поиска по тексту и #ID записи, сохранение всех существующих атрибутов и CRUD).
  * Подключена динамическая фильтрация и пагинация к `ListsView` (`page_size=8`, поле поиска по названию, #ID и содержимому пунктов, сохранение просмотра пунктов и чекбоксов).
  * Корректный сброс на 1-ю страницу при изменении поискового запроса; автоматический откат страницы назад при удалении последнего элемента текущей страницы.
  * Тестовый набор `tests/test_pagination.py` расширен до 21 теста (100% pass, всего 299 тестов в `tests/`).
* [x] **Повторяющиеся напоминания и задачи (Recurring Reminders & Tasks)**:
  * В `tools/datetime_utils.py` реализованы чистые функции `parse_repeat_rule`, `compute_next_reminder_time` и `format_repeat_rule`.
  * Поддержка 4 типов правил повторения: каждый день (`daily`), по будням (`weekdays`), каждую неделю (`weekly`), с интервалом в часах (`every_N_hours`).
  * Полная обратная совместимость: старые записи без поля `repeat` трактуются как `repeat=None`.
  * В `HouseholdManager.check_due_reminders()` повторяющиеся напоминания не завершаются навсегда (`triggered=True`), а автоматически переносятся на следующее целевое время с фиксацией снимка срабатывания.
  * Реализован метод `HouseholdManager.complete_reminder()`: безопасное выполнение (досрочное и после срабатывания) без двойного сдвига и без случайного удаления повторяющихся напоминаний.
  * В `ReminderMonitor` обновлена дедупликация: для повторяющихся напоминаний отслеживается уникальный ключ каждого конкретного срабатывания.
  * В `RemindersView` добавлены бейджи регулярности (`🔁 ...`), кнопка «✓ Выполнено» и подсказка форматов в строке ввода.
  * Создан специализированный тестовый набор `tests/test_recurring_reminders.py` (22 теста, 100% pass, всего 260 тестов в `tests/`).
* [x] **Дневной брифинг «Что у меня сегодня?» (Daily Briefing)**:
  * Создан специализированный read-only модуль `tools/daily_briefing.py` (`get_daily_briefing`, `pluralize_ru`, `is_task_overdue`, `does_recurring_apply_to_date`).
  * Детерминированная агрегация без LLM: активные задачи (с выделением просроченных), одноразовые напоминания на сегодня, повторяющиеся напоминания (daily, weekdays, weekly, hourly), активные списки дел с подсчетом оставшихся пунктов.
  * Чёткий эталонный формат вывода с грамматическими склонениями на русском языке («• 3 задачи, из них 1 просрочена.», «• 2 напоминания.», «• В списке "Покупки" осталось 4 пункта.»).
  * В `HouseholdManager.create_task` добавлен опциональный параметр `due_date: Optional[str] = None` с сохранением обратной совместимости.
  * Инструмент `daily_briefing` зарегистрирован в `tools.registry.TOOLS` и `TOOL_PARAMETERS`.
  * Быстрая детерминированная маршрутизация естественных запросов в `CommandRouter` («Что у меня сегодня?», «Что на сегодня?», «План на день», «Акакий, что запланировано на сегодня?», «дневной брифинг»).
  * Кнопка «⚡ Сводка дня» в блоке «Сегодня» дашборда `HomeView` с диалоговым окном `messagebox.showinfo` и безопасным воспроизведением через `VoiceService.speak_phrase()` (если активен голос).
  * Быстрые команды `:brief`, `:today`, `:сводка` в CLI REPL (`commands.py`).
  * Создан полный тестовый набор `tests/test_daily_briefing.py` (14 тестов, 100% pass, всего 274 теста в `tests/`).
* [x] **Звуковые уведомления и настройки Акакия (Audio Notifications & Settings)**:
  * Создан модуль персистентных настроек `tools/settings.py` (`AppSettings`, `get_app_settings`) с атомарным сохранением в `data/settings.json` (`notification_sound: True`, `speak_reminders: True`).
  * Создан модуль звуковых эффектов `notifications/sound.py` (`play_notification_sound`, `play_system_sound`) на базе стандартного Win32-механизма `winsound` с асинхронным воспроизведением (`SND_ASYNC`) и защитой от аппаратных сбоев.
  * Интеграция звука в `NotificationService.notify()`: при отображении каждого нового всплывающего окна воспроизводится системный звук (если включен в настройках).
  * Интеграция голосового оповещения в `AkakiyGUI._handle_reminder_due()`: при наступлении напоминания текст озвучивается через существующий экземпляр `self.voice.tts.speak()` (если `speak_reminders=True`) без создания дублирующего голосового пайплайна.
  * В `SettingsView` добавлена интерактивная секция «УВЕДОМЛЕНИЯ И ЗВУК» с тумблерами «Звук уведомлений» и «Озвучивать напоминания (TTS)», мгновенным сохранением состояния и кнопкой проверки звукового сигнала.
* [x] **Архитектура специализированных Sub-Agent'ов (Этап 1: Foundation)**:
  * Создан независимый пакет `tools/agents/` без внешних зависимостей.
  * Реализован базовый абстрактный контракт `SubAgent` (`tools/agents/base.py`) с валидацией контекста и обязательным методом `run(context: AgentContext) -> AgentResult`.
  * Реализован контейнер `AgentContext` (`tools/agents/context.py`) для изолированной передачи задачи, списка файлов, результатов предыдущих шагов, метаданных и ссылки на родительский агент.
  * Реализован стандартизированный контейнер `AgentResult` (`tools/agents/result.py`) со статусом `success`, сообщением, списком созданных файлов (`created_files`), структурированными данными (`data`), ошибкой (`error`), фабричными методами `ok`/`fail` и dict-like совместимостью.
  * Реализован потокобезопасный `AgentRegistry` (`tools/agents/registry.py`) с регистрацией, поиском, динамическим включением/отключением (`enable`/`disable`) и синглтоном `get_agent_registry()`.
  * Реализован эталонный тестовый Sub-Agent `EchoAgent` (`tools/agents/echo.py`) с эхо-обработкой контекста, mock-генерацией файлов и эмуляцией сбоев.
  * Минимальная обратная интеграция с `Agent` (`tools/agent.py`): регистрация `agent_registry` в `__init__`, фасадный метод `Agent.run_subagent()`. Существующие методы `process`, `execute_tool`, `create_plan` не затронуты.
  * Создан специализированный тестовый набор `tests/test_subagents_architecture.py` (30 тестов, 100% pass, всего 329 тестов в `tests/`).
* [x] **ImageAgent v1 с интеграцией ComfyUI Worker**:
  * Реализован клиент `ComfyUIClient` (`tools/agents/image.py`) на стандартной библиотеке Python (`urllib.request`) без установки сторонних зависимостей в основной `.venv`.
  * Реализован `ImageAgent(SubAgent)` со стандартным SDXL-Lightning workflow (1024x1024, 4 steps, Euler, sgm_uniform, CFG 1.5).
  * Получение бинарных данных PNG через официальный endpoint `/view` с сохранением в `data/generated/images/img_<timestamp>_<uuid>.png`.
  * Автоматический вызов `/free` для своевременного освобождения видеопамяти VRAM.
  * Регистрация в `AgentRegistry` по умолчанию под ключом `"image"`.
  * Создан модульный тестовый набор `tests/test_image_agent.py` (12 unit-тестов с mock HTTP, 100% pass).
  * Создан интеграционный тест `tests/test_image_agent_integration.py` (валидация реальной генерации на RTX 4070 Laptop GPU, 9.17с, валидация PNG через `struct` без внешних зависимостей).
  * Всего 342 теста в `tests/` (341 unit pass + 1 integration skip by default).
* [x] **VRAM Manager v1 (GPU Memory Orchestration)**:
  * Создан инфраструктурный менеджер `VRAMManager` (`tools/vram.py`) для бесконфликтного разделения видеопамяти GPU (8 GB) между Ollama (`qwen3:8b`) и ComfyUI (`sdxl_lightning_4step`).
  * Мониторинг VRAM через `nvidia-smi` (`get_gpu_stats()`) без тяжелых сторонних библиотек.
  * Безопасная выгрузка Ollama через `POST /api/generate` с `keep_alive: 0` (высвобождает ~5.5 GB VRAM перед генерацией).
  * Освобождение памяти ComfyUI через `POST /free` (`unload_models: true, free_memory: true`).
  * Контекстный менеджер `image_generation_session()` с гарантией очистки в `finally`.
  * Интеграция с `ImageAgent`: безопасная предварительная выгрузка Ollama, гарантированный `/free` в блоке `finally` даже при ошибках генерации, защита созданного PNG от потери при сбоях очистки.
  * Создан модульный тестовый набор `tests/test_vram_manager.py` (12 unit-тестов с mock HTTP/GPU, 100% pass).
  * Создан сквозной интеграционный тест `tests/test_image_vram_integration.py` (`RUN_IMAGE_VRAM_INTEGRATION=1`): реальная проверка полного жизненного цикла на RTX 4070 (Ollama load -> unload -> ComfyUI gen -> /free -> Ollama reload).
  * Всего 355 тестов в `tests/` (353 unit pass + 2 integration skip by default).
* [x] **Маршрутизация пользовательских запросов к ImageAgent (Image Request Routing)**:
  * В `CommandRouter` (`tools/router.py`) добавлены шаблоны распознавания естественных запросов на генерацию изображений («создай изображение...», «нарисуй...», «сгенерируй картинку...», «сделай фото...», «изобрази...») с поддержкой вежливых форм («пожалуйста»), обращения («Акакий») и извлечением чистого текстового промпта без служебных префиксов.
  * Детерминированная проверка в `CommandRouter.route()` с возвратом `type: "image"` без вызова LLM (< 1 мс).
  * Исключены ложные срабатывания (вопросы «что такое изображение?», бытовые команды «создай заметку купить картину», создание планов «создай план...»).
  * В `Agent.process()` (`tools/agent.py`) добавлен маршрут `route_type == "image"` с вызовом `self.run_subagent("image", task=prompt)`, фиксацией хода диалога в едином `ContextManager` и возвратом структурированного `resp` (`answer`, `result`, `created_files`, `success`).
  * При недоступности ComfyUI или ошибке генерации возвращается корректный `AgentResult.fail()` без необработанных исключений и падений.
  * В `main.py` добавлено чистое CLI-отображение для `result["type"] == "image"` с выводом пути к сохранённому файлу PNG.
  * Создан модульный тестовый набор `tests/test_image_routing.py` (7 тестов: 13 позитивных паттернов, 10 негативных проверок, latency < 1 мс, flow успеха и ошибки, регистры и пунктуация, 100% pass).
  * Всего 362 теста в `tests/` (360 unit pass + 2 integration skip by default).
* [x] **ImageAgent v2: Базовые параметры генерации изображений (Generation Parameters)**:
  * Поддержка пресетов соотношения сторон: `square` / `квадрат` (1024x1024), `landscape` / `широкое` / `горизонтальное` (1216x832), `portrait` / `вертикальное` / `портретное` (832x1216), `16:9` (1344x768), `9:16` (768x1344).
  * Поддержка явного разрешения WxH (например, `1280x720`, `800х600`, `1920x1080`) с автоматической нормализацией `safe_validate_resolution`: пропорциональное масштабирование при превышении допустимого лимита VRAM (~1.35 MP) и строгое округление до ближайшего кратного 64 (требование VAE SDXL).
  * Поддержка количества изображений (1..4, `safe_validate_count`) цифровыми и словесными числительными («два», «две», «три», «четыре», «пару»).
  * Последовательная генерация нескольких изображений с уникальными seeds (`for i in range(count):`) в рамках одной сессии VRAMManager (Ollama выгружается 1 раз в начале, ComfyUI `/free` вызывается 1 раз в конце). Пиковое потребление VRAM не превышает 7.4 GB независимо от количества сгенерированных файлов.
  * Возврат путей ко всем сохранённым файлам в `AgentResult.created_files`, чистое форматирование вывода в CLI REPL (`main.py`).
  * Добавлено 10 новых unit-тестов (6 в `tests/test_image_routing.py` и 4 в `tests/test_image_agent.py`), 100% pass.
  * Всего 372 теста в `tests/` (370 unit pass + 2 integration skip by default).
* [x] **Agent Router: Robust Routing (Этап 4)**:
  * Централизованная нормализация обращений («Акакий, ...», «Пожалуйста, ...», «Плиз, ...») через `strip_call_prefixes` во всех методах маршрутизатора (`choose_tool`, `match_memory`, `match_plan`, `match_image`, `route`).
  * Поддержка косвенного местоимения «мне» в бытовых командах (`создай мне задачу ...`, `создай мне заметку ...`, `напомни мне ...`, `создай мне список ...`) и планах (`создай мне план ...`).
  * Полное исключение ложных срабатываний ImageAgent на запросах создания файлов, скриптов, папок, кода, тестов, документов и таблиц (`NON_IMAGE_TARGET_PATTERN`).
  * Требование явного визуального объекта (существительное, пресет, разрешение или количество) для универсальных глаголов создания (`создай`, `сгенерируй`, `сделай`).
  * Реализована явная маршрутизация специализированных субагентов (`match_subagent`: `субагент <name>: <task>`, `запусти субагента <name>: <task>`) и диспетчеризация в `Agent.process()`.
  * Сохранение естественного диалога при общих приветствиях и вопросах («Акакий, привет!», «Как дела?»).
  * Создан специализированный тестовый набор `tests/test_router_robustness.py` (12 тестов, latency < 1 мс, 100% pass).
  * Всего 384 теста в `tests/` (382 unit pass + 2 integration skip by default).
* [x] **AgentContext v2: общий контракт multi-agent системы (Этап 5)**:
  * Структурированные атрибуты задачи: `task_id` (уникальный UUID), `root_task_id` (сквозной trace ID), `task_type`, `instruction`, `status` (`pending`, `running`, `completed`, `failed`), методы `mark_completed()`, `mark_failed()`.
  * Работа с файлами и метаданными: упорядоченный список `files`, словарь метаданных `file_metadata`, методы `add_file(path, **meta)`, `get_file_metadata(path)`, `set_file_metadata(path, meta)`, `remove_file(path)`, `has_file(path)`.
  * Передача результатов предыдущих агентов: список `previous_results`, методы `add_result(res, agent_name)`, `get_last_result(agent_name)`, `get_results_from(agent_name)`.
  * Метаданные параметров и протокол сопоставления: методы `get`, `set`, `update_metadata`, `has_metadata`, операторы `__getitem__`, `__setitem__`, `__contains__`.
  * Иерархическая связь parent/child: сохранение `parent_agent`, добавление ссылки `parent_context`, метод `create_child_context(...)` с безопасным глубоким копированием метаданных и изоляцией состояния, метод `copy()`.
  * Сериализация и десериализация: `to_dict()`, `from_dict()`, `to_json()`, `from_json()`, защита от циклических ссылок, 100% обратная совместимость со словарями v1.
  * Создан модульный тестовый набор `tests/test_agent_context_v2.py` (16 тестов, 100% pass).
  * Всего 400 тестов в `tests/` (398 unit pass + 2 integration skip by default).
* [x] **AgentResult v2 / Artifacts: универсальный контракт результатов и модель артефактов (Этап 6)**:
  * Реализована отдельная модель `Artifact` (`tools/agents/result.py`): поля `name`, `type`, `path`, `content`, `metadata`, свойства `is_image`, `is_document`, `is_file`, `exists()`, `size_bytes`, `mime_type`, словарный протокол `art["key"]` и `art.get()`.
  * Реализован классификатор `ArtifactType` (`image`, `document`, `file`, `text`, `code`, `audio`, `data`) с эвристикой автоопределения `guess_type` по расширениям файлов.
  * Фабричные методы `Artifact`: `from_file(path, ...)`, `from_image(path, width, height, ...)`, `from_text(content, ...)`, `from_dict(d)`.
  * Развит `AgentResult` v2: поддержка коллекции `artifacts: List[Artifact]`, двусторонняя синхронизация `created_files` $\leftrightarrow$ `artifacts`, перенос параметров генерации (`width`, `height`, `seed`) из `data` в метаданные артефактов изображений.
  * Методы выборки и фильтрации: `get_artifacts_by_type(type)`, свойство `images`, `get_artifact(name_or_index)`, `has_artifacts`, `primary_artifact`.
  * Фабричные методы добавления: `add_artifact(art, **kwargs)`, `add_file(path, **meta)`.
  * Сериализация в dict/JSON: `to_dict()`, `from_dict()`, `to_json()`, `from_json()` с полной поддержкой старого формата v1 без поля `artifacts`.
  * Экспорт `Artifact` и `ArtifactType` из пакета `tools/agents`.
  * Создан модульный тестовый набор `tests/test_agent_result_v2.py` (15 тестов, 100% pass).
  * Всего 415 тестов в `tests/` (413 unit pass + 2 integration skip by default).
* [x] **PresentationAgent v1: первый специализированный Sub-Agent создания презентаций (.pptx) (Этап 7)**:
  * Разработан легковесный движок генерации валидных презентаций Microsoft PowerPoint (`.pptx`, Office OpenXML) на чистой стандартной библиотеке Python (`zipfile`, `xml.sax.saxutils`, `io.BytesIO`) без сторонних пакетов.
  * Реализован специализированный субагент `PresentationAgent` (`tools/agents/presentation.py`), поддерживающий формат 16:9, титульные и контентные слайды, списки и цветовую палитру Modern Slate.
  * Реализован метод `parse_task(task, metadata)`: автоматическое извлечение темы, разбор многострочных планов и поддержка явного списка слайдов из метаданных.
  * Сохранение презентаций в стандартное хранилище `data/generated/presentations/pres_<timestamp>_<uuid>.pptx`.
  * В `ArtifactType` и `Artifact` добавлена поддержка типа `PRESENTATION = "presentation"` (свойство `is_presentation`, фабрика `from_presentation`, свойство `presentations` в `AgentResult`).
  * `PresentationAgent` зарегистрирован по умолчанию в `AgentRegistry` и экспортирован из `tools/agents`.
  * В `CommandRouter` (`tools/router.py`) добавлен метод `match_presentation(user_input)` для естественных команд и защита в `NON_IMAGE_TARGET_PATTERN`.
  * В `Agent.process()` подключена обработка маршрута `route_type == "presentation"` с запуском субагента и возвратом структурированного ответа.
  * В `main.py` добавлен вывод созданных презентаций в CLI REPL.
  * Создан модульный тестовый набор `tests/test_presentation_agent.py` (14 тестов, 100% pass).
  * Всего 429 тестов в `tests/` (427 unit pass + 2 integration skip by default).
* [x] **DocumentAgent v1: специализированный Sub-Agent создания документов (.docx) (Этап 8)**:
  * Разработан легковесный движок генерации валидных документов Microsoft Word (`.docx`, WordProcessingML / Office OpenXML) на чистой стандартной библиотеке Python (`zipfile`, `xml.sax.saxutils`, `io.BytesIO`) без сторонних пакетов.
  * Реализован специализированный субагент `DocumentAgent` (`tools/agents/document.py`), поддерживающий формат страницы A4, стиль заголовка (Title 26pt), подзаголовок (Subtitle 12pt italic), нумерованные разделы (Heading1 17pt), абзацы текста и маркированные списки (bullet points).
  * Реализован метод `parse_task(task, metadata)`: автоматическое извлечение темы, разбор структурированного многострочного текста задачи и поддержка явного списка разделов из метаданных `metadata["sections"]`.
  * Сохранение документов в стандартное хранилище `data/generated/documents/doc_<timestamp>_<uuid>.docx`.
  * В `Artifact` добавлена фабрика `from_document`, в `AgentResult` добавлено свойство `documents`.
  * `DocumentAgent` зарегистрирован по умолчанию в `AgentRegistry` и экспортирован из `tools/agents`.
  * В `CommandRouter` (`tools/router.py`) добавлен метод `match_document(user_input)` для естественных русскоязычных команд и явных вызовов `субагент document: ...`.
  * В `Agent.process()` подключена обработка маршрута `route_type == "document"` с запуском субагента, возвратом структурированного ответа и фиксацией в контексте диалога.
  * В `main.py` добавлен вывод созданных документов в CLI REPL.
  * Создан модульный тестовый набор `tests/test_document_agent.py` (15 тестов, 100% pass).
  * Всего 444 теста в `tests/` (442 unit pass + 2 integration skip by default).
* [ ] **Интеграционные E2E тесты с виртуальным микрофоном**:
  * Реализовать тестовый сценарий, прогоняющий синтезированные аудиофайлы (WAV) через живой конвейер `VoiceService` с проверкой реакции GUI.
* [ ] **Очистка устаревших бэкап-файлов `*.bak` в корне**:
  * Согласовать с пользователем удаление временных скриптов и резервных копий (`*.bak`) из корня репозитория.

