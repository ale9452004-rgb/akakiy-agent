# Архитектура проекта «Акакий»

Документ описывает фактическую архитектуру, модули, слои и потоки данных локального персонального ассистента **«Акакий»**.

---

## 1. Обзор системы

**«Акакий»** — локальный автономный персональный ассистент, работающий без передачи данных во внешние облачные сервисы.

### Ключевые характеристики
* **Среда выполнения**: Python 3.13, Windows PowerShell, виртуальное окружение `.venv`.
* **LLM-бэкенд**: Локальный сервер Ollama (`http://localhost:11434/api/chat`), модель `qwen3:8b`.
* **Взаимодействие**:
  * **Консольный терминал (CLI)**: интерактивный REPL (`main.py`).
  * **Графический интерфейс (GUI 2.0)**: полноэкранный Desktop Hub 1920x1280 на Tkinter (`gui.py`) с процедурной 3D-визуализацией Neural Core (`ui/neural_core.py`).
  * **Голосовой режим (Voice UX)**: локальное распознавание речи Vosk (`voice/stt.py`) + синтез речи pyttsx3/SAPI5 (`voice/tts.py`) под управлением `voice/service.py`.
* **Хранение данных**: Локальные изолированные JSON-хранилища в папке `data/` (`memory.json`, `household.json`), исключённые из Git-репозитория.

---

## 2. Архитектурные слои

Система разделена на пять взаимосвязанных слоёв:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      1. СЛОЙ ПРЕДСТАВЛЕНИЯ (UI / UX)                    │
│  CLI (main.py)  │  Desktop Hub (gui.py)  │  Neural Core  │ VoiceService │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                    2. СЛОЙ ОРКЕСТРАЦИИ И МОЗГА (CORE)                    │
│   Agent (tools/agent.py) ◄─────────┼─────────► ContextManager           │
│   ├─ choose_tool (fast-path <1ms)  │           (tools/context.py)       │
│   ├─ SkillRegistry (skills/)       │           ├─ Sliding Window        │
│   ├─ SubAgents (tools/agents/)     │           ├─ Prompt Injection      │
│   ├─ Planner & PlanExecutor        │           └─ Contextual Memories   │
│   └─ Teamwork (tools/teamwork.py)  │                                    │
└──────────────────┬─────────────────┴──────────────────┬─────────────────┘
                   │                                    │
┌──────────────────▼──────────────────┐ ┌───────────────▼─────────────────┐
│       3. СЛОЙ ДАННЫХ И ПАМЯТИ       │ │ 4. СЕТЕВОЙ LLM-КЛИЕНТ (OLLAMA)  │
│  MemoryManager (tools/memory.py)    │ │  OllamaClient (ollama_client.py)│
│  └─ data/memory.json                │ │  └─ POST /api/chat              │
│  HouseholdManager (tools/household) │ │     Native Tool Calling         │
│  └─ data/household.json             │ │     (tools parameter schema)    │
└──────────────────┬──────────────────┘ └─────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────────────────┐
│                    5. ИНСТРУМЕНТАЛЬНЫЙ СЛОЙ (TOOLS)                     │
│  Registry (tools/registry.py — 23 инструмента)                          │
│  Dispatcher (tools/dispatcher.py с подтверждением confirmation_callback)│
│  Files │ Git │ Terminal │ Analysis │ Validation │ Memory │ Household    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Детальное описание модулей

### 3.1. Слой представления (Presentation Layer)
* [main.py](file:///c:/Akakiy%20agent/main.py): Консольная точка входа. Запускает цикл REPL (`while True`), передаёт запросы пользователя в `Agent.process()`, форматирует результаты через `cli_formatters.py`.
* [cli_formatters.py](file:///c:/Akakiy%20agent/cli_formatters.py): Цветовое и табличное форматирование ответов агента, планов и шагов выполнения в консоли.
* [gui.py](file:///c:/Akakiy%20agent/gui.py): Полноэкранный Desktop Hub (1920x1280). Включает:
  * **Topbar (80px)**: статус системы, голосовой чип, часы и дата, индикаторы моделей.
  * **Sidebar (280px)**: постоянная навигация рабочего пространства (Главная, Чат, Задачи, Напоминания, Заметки, Списки, Память, Настройки).
  * **Main Workspace**: реактивные экраны для просмотра, CRUD-операций и отображения рабочих результатов.
  * **Command Bar (96px)**: нижняя панель ввода команд (пользователь остаётся на текущем экране без принудительного перехода в Чат), микрофон «🎙 Голос / ⏹ Стоп», регистрация структурированных рабочих результатов (`record_work_result`) и реактивное обновление `refresh_current_view()`.
  * **Асинхронная очередь (`queue.Queue`)**: потокобезопасная передача результатов агента, субагентов, состояний голоса и модальных окон подтверждений (`request_confirmation`).
* [ui/neural_core.py](file:///c:/Akakiy%20agent/ui/neural_core.py): UI-компонент Neural Core. Процедурная 3D-проекция пульсирующей нейросферы на `tk.Canvas`. Отражает состояния (`idle`, `thinking`, `working`, `listening`, `speaking`, `error`) и реагирует на реальную громкость речи (RMS аудио).
* [ui/views/](file:///c:/Akakiy%20agent/ui/views/): Пакет модульных экранов рабочего пространства (Main Workspace):
  * [ui/views/base.py](file:///c:/Akakiy%20agent/ui/views/base.py): Базовый класс `BaseView(tk.Frame)` с единым контрактом `render()` / `refresh()`, темой оформления и доступом к сервисам через Shell.
  * [ui/views/home.py](file:///c:/Akakiy%20agent/ui/views/home.py): Модульный экран дашборда (`HomeView`: состояние дня и сводка «Сегодня» с кнопкой «⚡ Сводка дня», 3D Neural Core, быстрые карточки задач, ближайших событий и напоминаний, списков дел, блок недавней активности и рабочих результатов Акакия со статусами субагентов и артефактами, блок последних заметок).
  * [ui/views/chat.py](file:///c:/Akakiy%20agent/ui/views/chat.py): Модульный рабочий экран диалога (`ChatView`: выделенный экран общения и логов, двухколоночный чат с форматированным выделением артефактов и логом инструментов и процессов).
  * [ui/views/tasks.py](file:///c:/Akakiy%20agent/ui/views/tasks.py): Модульный экран задач (`TasksView`, фильтрация поиска, пагинация, создание, выполнение, удаление).
  * [ui/views/reminders.py](file:///c:/Akakiy%20agent/ui/views/reminders.py): Модульный экран напоминаний (`RemindersView`, создание разовых и повторяющихся правил, бейджи регулярности, отметка выполнения, удаление).
  * [ui/views/lists.py](file:///c:/Akakiy%20agent/ui/views/lists.py): Модульный экран списков (`ListsView`, фильтрация поиска по названию и #ID, пагинация списков, создание, чекбоксы пунктов, удаление).
  * [ui/views/memory.py](file:///c:/Akakiy%20agent/ui/views/memory.py): Модульный экран памяти (`MemoryView`, фильтрация поиска по тексту и #ID, пагинация, ручное добавление, удаление фактов).
  * [ui/views/settings.py](file:///c:/Akakiy%20agent/ui/views/settings.py): Модульный экран настроек, валидации и резервного копирования (`SettingsView`, тумблеры звука уведомлений и TTS, запуск валидации, экспорт и импорт пользовательских данных).
* [ui/pagination.py](file:///c:/Akakiy%20agent/ui/pagination.py): Переиспользуемый UI-механизм фильтрации и пагинации (`PaginationModel`, `PaginationBar`, `PagedListController`), подключенный к экранам `TasksView`, `NotesView`, `MemoryView` и `ListsView`.
* [commands.py](file:///c:/Akakiy%20agent/commands.py): Вспомогательные быстрые команды и диспетчер CLI REPL (`show_status`, `show_files`, `read_file`, `handle_cli_command`, алиасы `:status`, `:files`, `:read`, `:export`, `:import`, `:brief`, `:today`, `:help`, `:exit`).

### 3.2. Голосовой слой (Voice UX)
* [voice/pipeline.py](file:///c:/Akakiy%20agent/voice/pipeline.py): Полноценный конвейер голосового взаимодействия (Voice Pipeline: `STT -> Agent -> TTS`). Класс `VoicePipeline` координирует распознавание, передачу команд в ядро `Agent` (`CommandRouter` / `SubAgents` / `Tools` / `Ollama`), извлечение озвучиваемого текста (`extract_speech_text`) из различных типов ответов (строка, `AgentResult`, `Artifact`, словари субагентов и инструментов) и воспроизведение через `TTS`. Модель `VoicePipelineResult` фиксирует статус, распознанный текст, очищенную команду, результат агента, озвученный текст, длительность и ошибку.
* [voice/service.py](file:///c:/Akakiy%20agent/voice/service.py): Координатор голосового сеанса (`VoiceService`). Запускает конвейер `listening -> thinking -> speaking -> listening`. Обеспечивает непрерывный Voice UX, реакцию на команды выхода («стоп», «отключись») и передачу событий в GUI. Делегирует шаг обработки голосового цикла в `VoicePipeline.run_step()`.
* [voice/stt.py](file:///c:/Akakiy%20agent/voice/stt.py): Локальное распознавание речи (Vosk, модель `vosk-model-small-ru-0.22`).
  * **Адаптивный endpointing**: калибровка порога шума микрофона (`speech_threshold = max(0.042, min(0.08, avg_noise * 1.55))`), отсечение пауз за `1.1 с`.
  * **Обработка Wake Word**: исправление искажений имени («а какие», «а как и» $\to$ «акакий») с сохранением имени для UI и выделением чистой команды через `strip_wake_word`.
* [voice/tts.py](file:///c:/Akakiy%20agent/voice/tts.py): Локальный синтез речи через `pyttsx3` (Windows SAPI5, русский голос). Работает в выделенном фоновом рабочем потоке с очередью фраз и поддержкой мгновенного прерывания.
* [voice/cleaner.py](file:///c:/Akakiy%20agent/voice/cleaner.py): Очистка текста от Markdown, символов разметки, JSON и путей перед передачей в TTS.
* [voice/normalizer.py](file:///c:/Akakiy%20agent/voice/normalizer.py): Числовая и вербальная нормализация русских сокращений, чисел и технических терминов.
* [voice/hotkey.py](file:///c:/Akakiy%20agent/voice/hotkey.py): Менеджер глобального хоткея Windows (`GlobalHotKeyManager`). Нативный перехват комбинации `Ctrl+Shift+Space` через Win32 API `RegisterHotKey`/`GetMessageW` без внешних зависимостей. Поддерживает двойной режим: Toggle (вкл/выкл по нажатию) и Push-to-Talk (удержание и досрочное завершение фразы при отпускании).

### 3.3. Мозговой центр и контекст (Core & Brain)
* [tools/router.py](file:///c:/Akakiy%20agent/tools/router.py): Класс `CommandRouter`.
  * **Детерминированная маршрутизация (Fast-Path, < 1 мс)**: распознавание типовых команд без обращения к LLM.
  * **Нормализация обращений и вежливости**: централизованная функция `strip_call_prefixes()` отсекает вводные слова («Акакий, ...», «Пожалуйста, ...», «Плиз, ...») во всех методах маршрутизатора (`choose_tool`, `match_memory`, `match_plan`, `match_image`, `route`).
  * **Естественные местоимения**: поддержка косвенного местоимения «мне» в бытовых сущностях (`создай мне задачу ...`, `создай мне заметку ...`, `напомни мне ...`, `создай мне список ...`) и планах (`создай мне план ...`).
  * **Исключение ложных срабатываний (False Positive Guard)**: фильтр `NON_IMAGE_TARGET_PATTERN` исключает перехват запросов создания файлов, скриптов, папок, кода, тестов, документов и таблиц генератором картинок.
  * **Единые правила роутинга**: файлы проекта (`find_file`, `list_files`, `search_files`), бытовые сущности (`create_task`, `list_tasks`, `complete_task`, `delete_task`, заметки, напоминания, списки).
  * **Устранение дублирования памяти**: единые шаблоны команд памяти (`remember`, `recall`, `forget`, `search`, `clear`) как для `choose_tool()`, так и для оркестратора `route()`.
  * **Управление планами**: распознавание директив планирования (`create`, `execute`, `get`, `clear`).
  * **Генерация изображений**: распознавание пользовательских интентов генерации изображений («создай изображение...», «нарисуй...», «сгенерируй картинку...») с извлечением чистого текстового промпта, пресетов соотношения сторон (квадрат, landscape, portrait, 16:9, 9:16), явного безопасного разрешения WxH и количества (1..4) с быстрой маршрутизацией в `type: "image"` (< 1 мс).
  * **Явная маршрутизация субагентов**: метод `match_subagent()` для прямого вызова зарегистрированных агентов (`субагент <name>: <task>`, `запусти субагента <name>: <task>`).
* [tools/agent.py](file:///c:/Akakiy%20agent/tools/agent.py): Класс `Agent`.
  * **Оркестрация конвейера**: прозрачная цепочка `CommandRouter (memory/plan/media fast-path)` $\to$ `TeamworkCoordinator` $\to$ `Project Tools` $\to$ `MultiAgentBridge (HouseholdAgent, ResearchAgent, Domain Agents)` $\to$ `Legacy Fast-Path Fallback` $\to$ `SkillRegistry` $\to$ `Native Tool Calling (Ollama)`.
  * **Интеграция с MultiAgentBridge**: бесшовное перенаправление бытовых и исследовательских запросов в новую multi-agent подсистему с сохранением совместимого типа (`CompatibleType`), полей `result`, `artifacts`, `tool`, фиксацией в `ContextManager` и сохранением `_last_result`.
  * **Маршрутизация к Sub-Agent'ам**: прямое исполнение `route_type == "image"` и `route_type == "subagent"` через `run_subagent(name, task=...)` с изоляцией VRAM, фиксацией хода диалога в `ContextManager` и возвратом структурированного результата.
  * **Интеграция навыков**: выбор активного навыка через `SkillRegistry` для контекстной фильтрации инструментов.
  * **Multi-turn loop**: до 5 раундов вызова инструментов Ollama Native Tool Calling за один ход.
  * **Self-healing**: однократная попытка исправления синтаксиса через `edit_file` при возникновении ошибок валидации.
* [tools/context.py](file:///c:/Akakiy%20agent/tools/context.py): Класс `ContextManager` — единый источник истины о диалоге.
  * Скользящее окно краткосрочной памяти (`max_turns=10`).
  * Защита от prompt injection (пользовательские данные передаются как справочный блок, а не часть системного промпта).
  * Контекстное извлечение релевантных фактов из долговременной памяти по ключевым словам.
  * Потокобезопасность (`threading.RLock`).
* [skills/registry.py](file:///c:/Akakiy%20agent/skills/registry.py): Реестр навыков (`SkillRegistry`). Управляет навыками `ProjectSkill`, `MemorySkill`, `HouseholdSkill`.
* [tools/planner.py](file:///c:/Akakiy%20agent/tools/planner.py): Модуль планирования задач (Task Planner v2):
  * `PlanStep`: структурированный шаг плана (`id`, `action`, `description`, `details`, `depends_on`, `subagent`, `target`, `command`, `query`, `task`, `files`, `metadata`), dict-like доступ для обратной совместимости (`__getitem__`), метод `to_pipeline_step()` для трансляции в `PipelineStep`.
  * `TaskPlan`: модель структурированного плана (`goal`, `steps`, `expected_result`, `verification`, `metadata`, `status`). Включает строгую валидацию структуры, проверку зависимостей (запрет самозависимости, проверка существования ID, детекция циклов алгоритмом Кана), топологическую сортировку `get_execution_order()`, мост в multi-agent конвейеры через `to_pipeline_steps()` и `to_pipeline()`.
  * `Planner`: эволюция планировщика до v2. Предоставляет программную фабрику `create_structured_plan()`, валидацию планов `validate_plan()`, интеграцию с Teamwork (`to_pipeline()`) и сохраняет 100% обратную совместимость с LLM-планированием (`create_plan`, `_validate_plan`).
* [tools/plan_executor.py](file:///c:/Akakiy%20agent/tools/plan_executor.py): Модуль исполнения планов (Task Executor v2 + Self-Healing):
  * Класс `PlanExecutor` — полноценное пошаговое исполнение планов с поддержкой `TaskPlan` и legacy-структур (словари и списки).
  * Интеграция Self-Healing: при сбое шага формируется `ErrorContext`, выполняется детерминированная классификация через `ErrorClassifier`, попытка фиксируется в `AgentContext.recovery_history` и для recoverable-ошибок выполняется безопасный retry в пределах установленных лимитов.
  * Защита от циклов: пошаговый счетчик `attempt <= max_attempts` и глобальный лимит `max_total_recoveries` гарантируют завершение.
  * Предварительная валидация графа плана (`validate()`) перед запуском с предотвращением циклов и невалидных шагов.
  * Топологическое упорядочивание шагов (`get_execution_order()`) с гарантией разрешения зависимостей до запуска зависимых действий.
  * Делегирование Sub-Agent шагов в `TeamworkPipeline` с контекстной изоляцией (`create_child_context`), семантическим трансфером данных и генерацией артефактов.
  * Сквозное накопление истории, созданных файлов и артефактов в `AgentContext` и возврат стандартизированного итогового объекта `AgentResult` (свойства `recovery_history` и `was_recovered`).
  * Управление ошибками и прерыванием через параметр `stop_on_error` с валидацией проекта при мутациях.
  * 100% обратная совместимость со словарным интерфейсом (`__getitem__`, `__setitem__`, `get`), `format_task_summary` и классическими инструментами (`search`, `analyze`, `read`, `edit`, `command`, `validate`, `git`).
* [tools/self_healing.py](file:///c:/Akakiy%20agent/tools/self_healing.py): Модуль контролируемого самовосстановления и классификации ошибок (Self-Healing):
  * `ErrorCategory`: классификация категорий ошибок (`transient`, `resource_busy`, `file_locked`, `validation_syntax`, `fatal`, `user_cancelled`, `security_violation`, `unsupported`, `exhausted`, `unknown`).
  * `ErrorContext`: структурированный контейнер контекста ошибки (`step_id`, `action`, `error`, `message`, `subagent`, `target`, `attempt`, `max_attempts`, `is_recoverable`, `category`, `strategy`, `timestamp`).
  * `ErrorClassifier`: детерминированное разделение ошибок на recoverable и non-recoverable по паттернам сообщений, типам исключений и явным флагам метаданных.
  * `SelfHealingManager`: координация попыток восстановления, управление лимитами retry на уровне шага (`step.metadata["max_retries"]` или default) и глобальным лимитом плана (`max_total_recoveries`), предотвращение бесконечных циклов.
* [tools/teamwork.py](file:///c:/Akakiy%20agent/tools/teamwork.py): Teamwork Preview — координация виртуальных ролей (Researcher, Architect, Implementer, Reviewer) для сложных задач.
* [tools/edit_preparer.py](file:///c:/Akakiy%20agent/tools/edit_preparer.py): Класс `EditPreparer` — подготовка точечных диффов и хирургических замен в коде на базе AST.
* [tools/summary.py](file:///c:/Akakiy%20agent/tools/summary.py): Форматирование агрегированных итоговых сводок выполнения плана.
* [tools/agents/](file:///c:/Akakiy%20agent/tools/agents): Архитектура специализированных Sub-Agent'ов (Sub-Agents Foundation).
  * `SubAgent` (`tools/agents/base.py`): Базовый абстрактный контракт независимого агента с методом `run(context: AgentContext) -> AgentResult` и валидацией контекста.
  * `AgentContext` (`tools/agents/context.py`): Унифицированный контракт контекста задач multi-agent системы (`task`, `instruction`, `task_id`, `root_task_id`, `task_type`, `status`, `files`, `file_metadata`, `previous_results`, `metadata`, `parent_agent`, `parent_context`). Поддерживает доступ по словарному протоколу (`ctx["key"]`), управление метаданными файлов, структурированное индексирование результатов субагентов, иерархию parent/child (`create_child_context`) с изоляцией состояния и цикл-безопасную JSON-сериализацию.
  * `AgentResult` и `Artifact` (`tools/agents/result.py`): Унифицированный результат выполнения (`success`, `message`, `created_files`, `data`, `error`, `artifacts`). Включает отдельную модель `Artifact` (имя, путь, содержимое, метаданные) и классификатор `ArtifactType` (image, document, file, text, code, audio, data) с автоопределением. Поддерживает двустороннюю синхронизацию с `created_files`, фильтрацию по типу (`images`), фабрики `ok`/`fail` и 100% обратную совместимость через dict-like интерфейс.
  * `AgentRegistry` (`tools/agents/registry.py`): Потокобезопасный реестр с поиском, динамическим включением/отключением и синглтоном `get_agent_registry()`.
  * `EchoAgent` (`tools/agents/echo.py`): Эталонный тестовый Sub-Agent для отладки передачи контекста, генерации файлов и симуляции сбоев.
  * `ImageAgent` (`tools/agents/image.py`): Специализированный Sub-Agent генерации изображений через изолированный HTTP Worker на базе ComfyUI (`127.0.0.1:8188`, SDXL-Lightning 4-step). Предоставляет `ComfyUIClient` на стандартной библиотеке Python с получением бинарных данных PNG через `/view`, безопасным сохранением в `data/generated/images/` и освобождением VRAM через `/free`.
  * `PresentationAgent` (`tools/agents/presentation.py`): Специализированный Sub-Agent создания презентаций (.pptx) на базе чистой стандартной библиотеки Python (Office OpenXML / zipfile). Поддерживает титульный слайд, слайды содержания, текстовые блоки (bullet points), авторазбор темы из задачи/метаданных, сохранение в `data/generated/presentations/` и возврат `AgentResult` с `Artifact` типа `presentation`/`document`.
  * `DocumentAgent` (`tools/agents/document.py`): Специализированный Sub-Agent создания текстовых документов (.docx) на базе чистой стандартной библиотеки Python (WordProcessingML / zipfile). Поддерживает титульный заголовок, подзаголовок, нумерованные разделы, абзацы текста, маркированные списки (bullet points), авторазбор структуры из задачи/метаданных, сохранение в `data/generated/documents/` и возврат `AgentResult` с `Artifact` типа `document`.
  * `ResearchAgent` (`tools/agents/research.py`): Специализированный Sub-Agent сбора и анализа информации на базе стандартной библиотеки Python. Обеспечивает структурированный разбор темы и вопросов, локальный анализ источников (документация проекта, код, файлы), синтез ключевых выводов, генерацию аналитического отчёта (Markdown), сохранение в `data/generated/research/` и возврат `AgentResult` с `Artifact` типа `text`/`document`.
  * `CodingAgent` (`tools/agents/coding.py`): Специализированный Sub-Agent анализа и безопасного точечного изменения кода. Поддерживает разбор задач, статический анализ файлов, выявление синтаксических ошибок, строгое ограничение изменений рамками белого списка `allowed_files`, применение точечных замен через `edit_file`, проведение targeted verification (проверка синтаксиса `py_compile`, выполнение проверочных тестов через PowerShell) и возврат `AgentResult` с `Artifact` типа `code`.
  * `FileAgent` (`tools/agents/file.py`): Специализированный Sub-Agent безопасных файловых операций. Поддерживает поиск файлов по имени и текста в файлах, чтение файлов с формированием `Artifact`, создание файлов, безопасное копирование и перемещение файлов, получение структурированных метаданных (размер, даты модификации/создания, mime-тип) со строгой изоляцией рабочей директорией, защитой от path traversal и категорическим запретом операций удаления.
  * `TeamworkPipeline` (`tools/teamwork.py`): Механизм последовательного взаимодействия нескольких Sub-Agent'ов через существующие `AgentContext`, `AgentResult` и `AgentRegistry`. Поддерживает конвейеры из 2–3+ агентов, передачу контекста и результатов между шагами (`create_child_context`, автотрансфер `topic`/`title`/`findings` $\to$ `sections`/`slides`), аккумуляцию `Artifact` и созданных файлов каждого шага, безопасную досрочную остановку при сбоях (`stop_on_error`) с сохранением промежуточных артефактов, динамические шаблоны задач и хуки трансформации `input_transform`. Публичный API: `PipelineStep`, `TeamworkPipeline`, `run_agent_pipeline` и `TeamworkCoordinator.run_pipeline()`.
* [agents/](file:///c:/Akakiy%20agent/agents): Фундамент новой multi-agent архитектуры (Multi-Agent Architecture Core).
  * `BaseAgent` (`agents/base.py`): Унифицированный базовый контракт специализированного агента (`name`, `display_name`, `description`, `capabilities`, `tools`, `enabled`) с методом `execute(task: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> AgentResult`.
  * `AgentRegistry` (`agents/registry.py`): Потокобезопасный реестр агентов без неявной глобальной магии. Поддерживает регистрацию, поиск по имени (`get`), поиск по возможностям (`find_by_capability`), по инструментам (`find_by_tool`), переключение активности (`enable`/`disable`), изоляцию в тестах (`clear`, `reset_agent_registry`) и безопасное выполнение задач (`execute`).
  * `HouseholdAgent` (`agents/household.py`): Доменный агент бытовых задач, списков, заметок и напоминаний. Делегирует исполнение существующему `HouseholdManager` без дублирования бизнес-логики и отправляет прогресс («Создаю задачу…»).
  * `ResearchAgent` (`agents/research.py`): Доменный агент поиска и сбора информации. Делегирует исполнение существующему SubAgent worker (`tools/agents/research.py`) через `AgentContext` и отправляет прогресс («Исследую запрос…», «Анализирую результаты…», «Формирую отчёт…»).
  * `CodingAgent` (`agents/coding.py`): Доменный агент разработки и модификации кода. Делегирует исполнение существующему SubAgent worker (`tools/agents/coding.py`) через `AgentContext`, транслируя реальные этапы («Анализирую код…», «Применяю изменения…», «Проверяю результат…»), и возвращает `AgentResult` с артефактами `ArtifactType.CODE`.
  * `AgentRouter` (`agents/router.py`): Детерминированный маршрутизатор доменных агентов. Определяет целевой агент через `AgentRegistry` по семантическим правилам capabilities без жестких зависимостей.
  * `AgentExecutor` (`agents/executor.py`): Единый исполнительный слой multi-agent архитектуры (`RouteResult / BaseAgent -> execute -> AgentResult`). Обеспечивает валидацию маршрута, отказоустойчивость, сохранение артефактов, открытость по OCP и генерацию событий жизненного цикла (`before_agent`, `agent_progress`, `after_agent`) через существующий `action_observer`.
  * `AgentService` (`agents/service.py`): Высокоуровневый фасад и единая точка входа multi-agent системы (`task -> route -> execute -> AgentResult`). Поддерживает инспекцию (`route`, `preview_route`), внедрение зависимостей (Dependency Injection) и проектные синглтоны (`get_agent_service`).
  * `MultiAgentBridge` (`agents/bridge.py`): Безопасный переходный слой интеграции монолитного `Agent.process()` с multi-agent конвейером (`can_handle`, `try_process`, `adapt_result`). Отсекает защищенные legacy-маршруты за O(1) без вызова роутера агентов, безопасно исполняет задачи через `AgentService` и адаптирует `AgentResult` в канонический словарь ответа.
  * **Визуализация Domain Agents в Desktop Hub (`gui.py`, `ui/views/home.py`, `ui/views/chat.py`)**: реактивное отображение статуса и текущего шага в Hero / Neural Core (`lbl_status_badge`, `lbl_status_desc`), бейджи доменов в Recent Work Results (`[🏠 ДОМАШНИЕ ДЕЛА]`, `[🔍 ИССЛЕДОВАНИЯ]`, `[💻 РАЗРАБОТКА]`), метки в ответах ЧАТА (`● АКАКИЙ [🏠 Домашние дела]`, `● АКАКИЙ [💻 Разработка]`) и подсветка событий `[AGENT]` / `[STEP]` в системном логе.

### 3.4. Слой данных и памяти (Data Layer)
* [tools/persistent_memory.py](file:///c:/Akakiy%20agent/tools/persistent_memory.py): Выделенный слой постоянной долговременной памяти (`PersistentMemory`):
  * Структурированная модель `MemoryEntry(dict)` (`id`, `content`/`text`, `type`/`category`, `source`, `tags`, `metadata`, `created_at`, `updated_at`).
  * Типы и источники: `MemoryType` (fact, preference, result, note, general, artifact), `MemorySource` (user, agent, subagent, cli, gui, system).
  * Изоляция долговременных фактов от диалогового runtime history (`short_term`) и контекста исполнения задач (`AgentContext`).
  * Безопасные CRUD-операции (`create`, `get`, `get_all`, `update`, `delete`, `clear`).
  * Многокритериальный поиск и фильтрация (`search` по тексту, типу, тегам, источнику).
  * Атомарная запись через `.tmp` и `os.replace`, автомиграция схемы v1 $\to$ v2 и устойчивость к повреждённым файлам.
  * Метод `remember_result()` для контролируемой явной фиксации итогов задач.
* [tools/memory.py](file:///c:/Akakiy%20agent/tools/memory.py): Фасад памяти и скользящее окно диалога (`MemoryManager`):
  * Делегирует долговременное хранение в `PersistentMemory` с сохранением 100% обратной совместимости.
  * Ведет изолированное скользящее окно краткосрочных ходов диалога (`short_term`, `add_turn`, `get_recent_history`).
  * Экспортируемые инструменты: `remember`, `recall_memory`, `forget_memory`, `update_memory`.
* [tools/household.py](file:///c:/Akakiy%20agent/tools/household.py): Бытовой менеджер (`HouseholdManager`).
  * Хранилище: `data/household.json`.
  * Атомарная запись и потокобезопасность.
  * Сущности: Задачи (Tasks), Напоминания (Reminders), Заметки (Notes), Списки (Lists).
  * Поддержка пакетного и относительного удаления (`_resolve_delete_targets`).
  * Повторяющиеся напоминания: автоматический пересчет времени в `check_due_reminders()` и безопасное завершение через `complete_reminder()`.
* [tools/datetime_utils.py](file:///c:/Akakiy%20agent/tools/datetime_utils.py): Утилиты разбора и нормализации дат и времени.
  * Чистая функция `parse_reminder_time` (разбор ISO-дат, относительных смещений «через N минут/часов/дней», конструкций «завтра в HH:MM», времени суток «HH:MM» и регулярных выражений повторения).
  * Чистые функции повторения: `parse_repeat_rule` (разбор `daily`, `weekdays`, `weekly`, `every_N_hours`), `compute_next_reminder_time` (расчет следующей даты с учетом выходных и пропущенных интервалов), `format_repeat_rule` (человекочитаемый бейдж).
* [tools/backup.py](file:///c:/Akakiy%20agent/tools/backup.py): Модуль резервного копирования и восстановления данных (Backup & Restore).
  * `export_data`: Экспорт бытовых сущностей (`household.json`) и памяти (`memory.json`) в единый версионированный JSON-файл (`akakiy_backup_version = 1`) с метаданными и статистикой.
  * `import_data`: Транзакционный импорт с предварительными байтовыми снимками файлов в памяти, атомарной перезаписью, автоматическим откатом при сбоях и вызовом `reload()` у менеджеров.
  * `validate_backup`: Проверка схемы, совместимости версий и типов данных до модификации локальных файлов.
  * Защита от утечки и перезаписи: блокировка сохранения бэкапов внутри рабочего каталога `data/`.
* [tools/daily_briefing.py](file:///c:/Akakiy%20agent/tools/daily_briefing.py): Модуль дневного брифинга («Что у меня сегодня?»).
  * Строго read-only агрегатор данных: активные задачи (с выделением просроченных), напоминания на сегодня, регулярные напоминания (daily, weekdays, weekly, interval hours) и активные списки с количеством незавершённых пунктов.
  * Детерминированная сборка сводки без обращения к LLM с правильными грамматическими склонениями числительных (`pluralize_ru`).
* [tools/settings.py](file:///c:/Akakiy%20agent/tools/settings.py): Менеджер настроек приложения (`AppSettings`).
  * Хранилище: `data/settings.json`.
  * Потокобезопасная атомарная запись через `.tmp` и `os.replace`.
  * Хранит флаги звуковых уведомлений (`notification_sound`), озвучивания напоминаний (`speak_reminders`) и произвольные параметры приложения.

### 3.5. Инструментальный слой и безопасность (Tools & Safety Layer)
* [tools/permissions.py](file:///c:/Akakiy%20agent/tools/permissions.py): Централизованный слой разрешений и безопасности (Permissions & Safety Layer):
  * Перечисление уровней риска `RiskLevel` (`SAFE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) и политик `SecurityPolicy` (`NORMAL`, `STRICT`, `PERMISSIVE`, `READ_ONLY`).
  * Централизованная оценка действий (`PermissionAssessment`) ДО их фактического выполнения.
  * Контекстный анализ риска (детекция перезаписи существующих файлов, анализ опасных команд PowerShell, git-мутаций и удалений).
  * Интеграция с `Dispatcher`, `TeamworkPipeline`, `PlanExecutor`, `Agent.run_subagent` и модальными окнами подтверждения GUI `request_confirmation`.
* [tools/registry.py](file:///c:/Akakiy%20agent/tools/registry.py): Центральный реестр `TOOLS` (24 зарегистрированных инструмента) с описаниями, схемами параметров и хелпером `get_tool_risk_level`.
* [tools/dispatcher.py](file:///c:/Akakiy%20agent/tools/dispatcher.py): Функция `dispatch()` — вызов инструментов по имени с обязательным централизованным перехватом разрешений через `PermissionManager`.
* [tools/daily_briefing.py](file:///c:/Akakiy%20agent/tools/daily_briefing.py): `daily_briefing` — сводка дня.
* [tools/files.py](file:///c:/Akakiy%20agent/tools/files.py): `list_files`, `find_file`, `read_file`, `write_file`, `edit_file`, `search_files`.
* [tools/terminal.py](file:///c:/Akakiy%20agent/tools/terminal.py): Безопасное исполнение команд PowerShell `run_command`.
* [tools/git.py](file:///c:/Akakiy%20agent/tools/git.py): `git_status`, `git_diff`, `git_commit`, `git_log`, `git_push`.
* [tools/analysis.py](file:///c:/Akakiy%20agent/tools/analysis.py): Статический анализ Python-файлов через AST `analyze_file`.
* [tools/validation.py](file:///c:/Akakiy%20agent/tools/validation.py): Проверка синтаксиса проекта через `py_compile` (`validate_project`).

### 3.6. Слой уведомлений (Notifications Layer)
* [notifications/monitor.py](file:///c:/Akakiy%20agent/notifications/monitor.py): Фоновый монитор напоминаний (`ReminderMonitor`).
  * Работает в выделенном потоке-демоне, периодически проверяет наступившие напоминания через `HouseholdManager.check_due_reminders()`.
  * Не содержит зависимостей от Tkinter.
  * Обеспечивает строгую дедупликацию (одно напоминание срабатывает ровно один раз).
  * Безопасный жизненный цикл `start()` / `stop()`.
* [notifications/sound.py](file:///c:/Akakiy%20agent/notifications/sound.py): Модуль системных звуковых оповещений (`play_notification_sound`, `play_system_sound`).
  * Воспроизведение через стандартный модуль `winsound` Windows (`SND_ALIAS | SND_ASYNC`, fallback на `MessageBeep`).
  * Неблокирующий асинхронный запуск, полная изоляция аппаратных ошибок аудиоустройств.
* [notifications/service.py](file:///c:/Akakiy%20agent/notifications/service.py): Централизованный сервис уведомлений (`NotificationService`).
  * Управляет жизненным циклом и вертикальным стеком всплывающих окон в правом нижнем углу экрана.
  * Потокобезопасен (при вызове из фонового потока перенаправляет в UI-поток через `master.after()`).
  * Воспроизводит системный звук при отображении каждого нового всплывающего окна (при активной настройке `notification_sound`).
  * Автоматически выполняет перекомпоновку (репозиционирование) оставшихся окон при закрытии любого уведомления.
  * Предоставляет чистый фасад: `notify()`, `show_reminder()`, `show_info()`, `close()`, `close_all()`.
* [notifications/window.py](file:///c:/Akakiy%20agent/notifications/window.py): Модульное окно уведомления (`NotificationWindow`).
  * Наследуется от `tk.Toplevel`, отображается поверх окон (`overrideredirect(True)`, `attributes("-topmost", True)`).
  * Выполнено в фирменном тёмном стиле Акакия (карточка `#161b22`, рамка `#30363d`, кнопка закрытия `×`).
  * Поддерживает типовые бейджи (Reminder, Info, Warning, Success, Error) и кнопки действий (`✓ Выполнено`, `⏰ Отложить`).
* [notifications/models.py](file:///c:/Akakiy%20agent/notifications/models.py): Модели данных `NotificationItem` и `NotificationAction`.

### 3.7. Управление VRAM и изолированные воркеры (GPU & External Workers)
* **VRAMManager** (`tools/vram.py`):
  * Централизованный инфраструктурный менеджер координации видеопамяти GPU (RTX 4070 Laptop GPU 8 GB VRAM).
  * Безопасная выгрузка Ollama (`qwen3:8b`) через API `/api/generate` с параметром `keep_alive: 0` (высвобождает ~5.5 GB VRAM перед запуском генерации).
  * Освобождение видеопамяти ComfyUI через POST `/free` (`unload_models: true, free_memory: true`).
  * Сбор статистики VRAM через стандартный `nvidia-smi` без внешних библиотек.
  * Гарантированное освобождение видеопамяти в блоке `finally` даже при сбоях инференса.
  * Контекстный менеджер `image_generation_session()` для безопасных изолированных сессий.
  * Штатная отложенная перезагрузка Ollama при следующем обращении пользователя.
* **ComfyUI Image Worker** (`workers/comfyui/`):
  * Автономный локальный HTTP-сервис генерации изображений (`127.0.0.1:8188`).
  * Полностью изолирован: собственное виртуальное окружение и зависимости PyTorch CUDA, не влияющие на основной `.venv` Акакия.
  * Каталог `workers/` и результаты генерации `data/generated/` исключены из Git (`.gitignore`).
  * Использует чекпоинт `sdxl_lightning_4step.safetensors` для быстрого синтеза изображений (1024x1024, 4 шага, ~9.1-13.7 с на RTX 4070 Laptop GPU 8 GB VRAM).

### 3.8. Инфраструктурный слой и жизненный цикл LLM (Infrastructure Layer)
* [infrastructure/ollama_manager.py](file:///c:/Akakiy%20agent/infrastructure/ollama_manager.py): Менеджер жизненного цикла локальной среды LLM (`OllamaManager`, `get_ollama_manager`):
  * Проверка доступности API локального сервера Ollama (`http://localhost:11434/api/tags`).
  * Автоматический запуск процесса `ollama serve` в фоновом режиме на Windows (`CREATE_NO_WINDOW`), если сервер не запущен.
  * Проверка наличия целевой модели `qwen3:8b` без автоскачивания (с выводом чёткой инструкции пользователю при отсутствии).
  * Строгое отслеживание владельца (`started_by_akakiy`): чужой, ранее запущенный процесс Ollama никогда не останавливается.
  * Корректная остановка только собственного процесса (`terminate` -> `wait` -> `kill`) при выходе из GUI или CLI (`finally: cleanup()`).
  * Регистрация аварийной очистки в `atexit` и полная изоляция внутренних исключений.

---

## 4. Потоки данных (Data Flows)

### Поток 1: Обработка пользовательского запроса (CLI / GUI)
```
Пользователь (Текст)
   │
   ▼
Agent.process(user_input)
   │
   ├─► 1. CommandRouter.route(user_input) (Детерминированный fast-path, латентность < 1 мс)
   │       ├─ Память: remember, recall, forget, search, clear ──► MemoryManager
   │       ├─ Планы: create, execute, get, clear ──► Planner / PlanExecutor
   │       ├─ Инструменты: find_file, list_files, search_files, бытовой CRUD ──► Agent.execute_tool()
   │       │     ▼
   │       │   ContextManager.record_interaction()
   │       │     ▼
   │       └─► Ответ клиенту (CLI / GUI)
   │
   ├─► 2. TeamworkCoordinator.is_complex_task(user_input) ──► Teamwork Preview
   │
   └─► 3. Не совпало (Свободный естественный язык / сложный запрос)
           │
           ├─► SkillRegistry.find_matching_skill(user_input)
           │     └─ Выбор активного навыка (Project, Memory или Household)
           │
           ├─► ContextManager.build_messages_for_llm(user_input)
           │     ├─ Чистый системный промпт (+ промпт навыка)
           │     ├─ Релевантные факты из долговременной памяти (справочный блок)
           │     └─ Скользящее окно предыдущих ходов
           │
           ├─► OllamaClient.send_chat(messages, tools=scoped_tools)
           │     │
           │     ├─ Ответ без инструментов ──► Ответ в чат
           │     │
           │     └─ Модель вызвала инструмент (Tool Call)
           │           ▼
           │         Agent.execute_tool() -> dispatch()
           │           ├─ requires_confirmation? ──► Запрос у пользователя
           │           └─ Выполнение функции инструмента
           │           ▼
           │         Повторная передача результата в Ollama (до 5 раундов)
           │
           ├─► ContextManager.commit_turn_messages()
           └─► Ответ клиенту (CLI / GUI)
```

### Поток 2: Голосовой конвейер (Voice UX)
```
Микрофон (sounddevice)
   │
   ▼
SpeechToTextEngine.listen_phrase()
   ├─ Адаптивная калибровка шума: speech_threshold = max(0.042, avg_noise * 1.55)
   ├─ Буферизация чанков аудио и передача в KaldiRecognizer (Vosk)
   ├─ Детекция тишины > 1.1 с ──► Завершение фразы
   │
   ▼
correct_recognized_text()
   ├─ Исправление искажений («а какие» -> «акакий»)
   └─ Сохранение полного текста для UI
   │
   ├─► emit("voice_recognized", {"text": text})  [Отображение в GUI]
   │
   ▼
strip_wake_word(text)  [Отделение обращения]
   │
   ├─ Только имя «Акакий» ──► Ответ: «Да, я здесь! Чем могу помочь?»
   │
   └─ Текст команды ─────────► Agent.process(command)
                                 │
                                 ▼
                               emit("voice_agent_result")
                                 │
                                 ▼
                               _extract_speech_text()
                                 ├─ success=False / error ──► «Ошибка: ...»
                                 └─ Успех ──────────────────► Текст ответа / сообщения
                                 │
                                 ▼
                               clean_for_speech() -> TextToSpeechEngine.speak()
                                 └─ Озвучка pyttsx3/SAPI5 в фоновом потоке
```

### Поток 3: Фоновый мониторинг и стек уведомлений (Notifications)
```
HouseholdManager (data/household.json)
   │
   ▼
ReminderMonitor.check_now()  [Фоновый поток-демон]
   ├─ HouseholdManager.check_due_reminders()
   ├─ Дедупликация: _notified_ids
   │
   ▼
AkakiyGUI._on_reminder_due()  [Потокобезопасный Callback]
   │
   ▼
AkakiyGUI.queue.put(("reminder_due", reminder))
   │
   ▼
AkakiyGUI._poll_queue() -> _handle_reminder_due()  [Главный UI-поток Tkinter]
   │
   ▼
NotificationService.show_reminder()
   ├─ Формирование NotificationItem (действия «✓ Выполнено», «⏰ Отложить»)
   ├─ Создание NotificationWindow (Toplevel, overrideredirect, topmost)
   ├─ Добавление в стек и расчет координат (правый нижний угол)
   └─ _restack()
        │
         ├─► Пользователь нажал «✓ Выполнено» ──► HouseholdManager.complete_reminder() -> refresh view
         ├─► Пользователь нажал «⏰ Отложить»   ──► HouseholdManager.create_reminder("... через 10 минут") -> refresh view
         └─► Пользователь нажал «×» (Закрыть)   ──► Закрытие окна -> _restack() оставшихся
```

### Поток 4: Генерация изображений через Sub-Agent и VRAM Manager (ImageAgent v2)
```
Пользователь / Агент
   │
   ▼
Agent.run_subagent("image", task="промпт", aspect_ratio="landscape", count=2, ...)
   │
   ├─► ImageAgent.run(AgentContext)
   │      │
   │      ├─► Валидация параметров:
   │      │      ├─ aspect_ratio пресеты (square, landscape, portrait, 16:9, 9:16)
   │      │      ├─ safe_validate_resolution (лимит ~1.35 MP, кратно 64)
   │      │      └─ safe_validate_count (1..4)
   │      │
   │      ├─► VRAMManager.prepare_for_image_generation() [Выполняется ровно 1 раз на сессию]
   │      │      ├─ Замер начальной VRAM (nvidia-smi)
   │      │      ├─ POST http://localhost:11434/api/generate {"keep_alive": 0} (выгрузка Ollama)
   │      │      └─ Замер VRAM после выгрузки (~1.3 GB used, ~6.5 GB free)
   │      │
   │      ├─► Последовательный цикл генерации: for i in range(count) [Пик VRAM <= 7.4 GB]:
   │      │      ├─ ComfyUIClient.queue_prompt(workflow_i) ──► HTTP POST /prompt (127.0.0.1:8188)
   │      │      ├─ Опрос статуса и истории ──────────────► HTTP GET /history/{prompt_id}
   │      │      ├─ Загрузка байтов изображения ──────────► HTTP GET /view (бинарный PNG)
   │      │      └─ Сохранение в data/generated/images/img_<timestamp>_<uuid>.png
   │      │
   │      └─► finally: VRAMManager.restore_after_image_generation() [Выполняется ровно 1 раз]
   │             ├─ POST http://127.0.0.1:8188/free {"unload_models": true, "free_memory": true}
   │             └─ Замер финальной VRAM после очистки
   │
   ▼
AgentResult(success=True, created_files=[...], data={count, width, height, saved_to, seed, seeds, ...})
```

### Поток 5: Сквозной конвейер ядра Акакий 2.0 (Akakiy 2.0 Core Pipeline)
```
Пользователь / CLI / GUI (Desktop Hub) / VoicePipeline
    │
    ▼
Agent.process(user_input)
    ├─► CommandRouter (детерминированная маршрутизация и fast-paths):
    │      ├─ Долговременная память ──────► PersistentMemory (remember, recall, search, forget, clear, remember_result)
    │      ├─ Планирование (Planner v2) ──► TaskPlan v2 (валидация графа, depends_on) -> PlanExecutor
    │      ├─ Sub-Agents (8 агентов)   ──► run_subagent() -> AgentContext -> AgentResult / Artifacts
    │      ├─ Teamwork Preview          ──► TeamworkCoordinator.run(user_request, initial_context)
    │      ├─ Быстрые инструменты       ──► execute_tool() -> Dispatcher
    │      └─ Чат / Свободный диалог    ──► SkillRegistry -> Ollama Native Tool Calling
    │
    ├─► Единый слой безопасности (PermissionManager):
    │      ├─ Оценка риска (RiskLevel: SAFE, LOW, MEDIUM, HIGH, CRITICAL) строго ДО выполнения действия;
    │      ├─ Защита критических файлов (.git, .env, ключи) и блокировка деструктивных команд ОС;
    │      └─ Запрос подтверждения (GUI request_confirmation / CLI input) при модификациях.
    │
    ├─► Исполнение задач и планов (PlanExecutor v2 + Self-Healing):
    │      ├─ Топологический порядок выполнения шагов;
    │      ├─ Непрерывность и наследование AgentContext (parent_agent, previous_results, files);
    │      ├─ Субагенты выполняются через TeamworkPipeline;
    │      ├─ SelfHealingManager: классификация recoverable/non-recoverable ошибок и безопасный retry;
    │      └─ Аккумуляция артефактов и созданных файлов в итоговом AgentResult.
    │
    ├─► Сохранение результатов и память:
    │      ├─ Фиксация self._last_result для быстрого доступа;
    │      ├─ Сохранение хода диалога в ContextManager (краткосрочная память);
    │      └─ Явная фиксация важных результатов через remember_result в PersistentMemory (переживает перезапуск).
    │
    └─► Стандартизированный выходной контракт:
           ├─ VoicePipeline: extract_speech_text() -> очистка текста -> TTS (фоновая озвучка);
           ├─ Desktop Hub GUI: record_work_result() -> реактивное обновление HomeView/ChatView/StatusBar;
           └─ CLI REPL: форматированный вывод summary, статусов и путей к созданным артефактам.
```

---

## 5. Политика изоляции и безопасность

1. **Изоляция пользовательских данных**: Все пользовательские заметки, задачи, списки и факты долговременной памяти хранятся строго в `data/*.json`, которые добавлены в `.gitignore` и никогда не попадают в систему контроля версий.
2. **Защита от перезаписи и потери данных**: Все операции модификации JSON используют атомарную запись: сериализация во временный файл (`.tmp`) с последующей заменой целевого файла через `os.replace`.
3. **Единый слой разрешений и безопасности (Permissions & Safety Layer)**: Все потенциально опасные инструменты и действия Sub-Agent'ов (`delete_*`, `write_file`, `edit_file`, `git_commit`, `git_push`, `run_command`, модифицирующие действия `FileAgent` и `CodingAgent`) проходят предварительную оценку риска (`RiskLevel: SAFE, LOW, MEDIUM, HIGH, CRITICAL`) через `PermissionManager`. Проверка и запрос подтверждения (`request_confirmation`) происходят строго **ДО** фактического выполнения действия, блокируя исполнение при отказе пользователя или нарушении политики безопасности.
4. **Защита от prompt injection**: Пользовательские данные памяти передаются в LLM строго в отдельной секции справочной информации (с маркировкой доверия), не модифицируя неизменяемый системный промпт ассистента.
