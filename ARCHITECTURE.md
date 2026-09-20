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
│   ├─ Planner & PlanExecutor        │           ├─ Prompt Injection      │
│   └─ Teamwork (tools/teamwork.py)  │           └─ Contextual Memories   │
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
  * **Topbar (80px)**: статус системы, голосовой чип, переключатель режима, кнопка валидации синтаксиса.
  * **Sidebar (280px)**: переключение разделов (Главная, Чат, Задачи, Напоминания, Заметки, Списки, Память, Настройки).
  * **Main Workspace**: реактивные экраны для просмотра и CRUD-операций со списками, заметками, задачами и памятью.
  * **Command Bar (96px)**: нижняя панель ввода текстовых команд, кнопка отправки и кнопка управления микрофоном «🎙 Голос / ⏹ Стоп».
  * **Асинхронная очередь (`queue.Queue`)**: потокобезопасная передача результатов агента, состояний голоса и модальных окон подтверждений (`request_confirmation`).
* [ui/neural_core.py](file:///c:/Akakiy%20agent/ui/neural_core.py): UI-компонент Neural Core. Процедурная 3D-проекция пульсирующей нейросферы на `tk.Canvas`. Отражает состояния (`idle`, `thinking`, `working`, `listening`, `speaking`, `error`) и реагирует на реальную громкость речи (RMS аудио).
* [commands.py](file:///c:/Akakiy%20agent/commands.py): Вспомогательные быстрые команды (`show_status`, `show_files`, `read_file`).

### 3.2. Голосовой слой (Voice UX)
* [voice/service.py](file:///c:/Akakiy%20agent/voice/service.py): Координатор голосового сеанса (`VoiceService`). Запускает конвейер `listening -> thinking -> speaking -> listening`. Обеспечивает непрерывный Voice UX, реакцию на команды выхода («стоп», «отключись») и передачу событий в GUI.
* [voice/stt.py](file:///c:/Akakiy%20agent/voice/stt.py): Локальное распознавание речи (Vosk, модель `vosk-model-small-ru-0.22`).
  * **Адаптивный endpointing**: калибровка порога шума микрофона (`speech_threshold = max(0.042, min(0.08, avg_noise * 1.55))`), отсечение пауз за `1.1 с`.
  * **Обработка Wake Word**: исправление искажений имени («а какие», «а как и» $\to$ «акакий») с сохранением имени для UI и выделением чистой команды через `strip_wake_word`.
* [voice/tts.py](file:///c:/Akakiy%20agent/voice/tts.py): Локальный синтез речи через `pyttsx3` (Windows SAPI5, русский голос). Работает в выделенном фоновом рабочем потоке с очередью фраз и поддержкой мгновенного прерывания.
* [voice/cleaner.py](file:///c:/Akakiy%20agent/voice/cleaner.py): Очистка текста от Markdown, символов разметки, JSON и путей перед передачей в TTS.
* [voice/normalizer.py](file:///c:/Akakiy%20agent/voice/normalizer.py): Числовая и вербальная нормализация русских сокращений, чисел и технических терминов.

### 3.3. Мозговой центр и контекст (Core & Brain)
* [tools/agent.py](file:///c:/Akakiy%20agent/tools/agent.py): Класс `Agent`.
  * **Двухуровневая маршрутизация**: быстрый детерминированный путь в `choose_tool()` (< 1 мс) для типовых команд; передача естественного языка в Native Tool Calling.
  * **Интеграция навыков**: выбор активного навыка через `SkillRegistry` для контекстной фильтрации инструментов.
  * **Multi-turn loop**: до 5 раундов вызова инструментов Ollama Native Tool Calling за один ход.
  * **Self-healing**: однократная попытка исправления синтаксиса через `edit_file` при возникновении ошибок валидации.
* [tools/context.py](file:///c:/Akakiy%20agent/tools/context.py): Класс `ContextManager` — единый источник истины о диалоге.
  * Скользящее окно краткосрочной памяти (`max_turns=10`).
  * Защита от prompt injection (пользовательские данные передаются как справочный блок, а не часть системного промпта).
  * Контекстное извлечение релевантных фактов из долговременной памяти по ключевым словам.
  * Потокобезопасность (`threading.RLock`).
* [skills/registry.py](file:///c:/Akakiy%20agent/skills/registry.py): Реестр навыков (`SkillRegistry`). Управляет навыками `ProjectSkill`, `MemorySkill`, `HouseholdSkill`.
* [tools/planner.py](file:///c:/Akakiy%20agent/tools/planner.py): Класс `Planner` — разложение многошаговых задач в структурированный JSON-план.
* [tools/plan_executor.py](file:///c:/Akakiy%20agent/tools/plan_executor.py): Класс `PlanExecutor` — пошаговое исполнение действий с валидацией синтаксиса после каждого шага.
* [tools/teamwork.py](file:///c:/Akakiy%20agent/tools/teamwork.py): Teamwork Preview — координация виртуальных ролей (Researcher, Architect, Implementer, Reviewer) для сложных задач.
* [tools/edit_preparer.py](file:///c:/Akakiy%20agent/tools/edit_preparer.py): Класс `EditPreparer` — подготовка точечных диффов и хирургических замен в коде на базе AST.
* [tools/summary.py](file:///c:/Akakiy%20agent/tools/summary.py): Форматирование агрегированных итоговых сводок выполнения плана.

### 3.4. Слой данных и памяти (Data Layer)
* [tools/memory.py](file:///c:/Akakiy%20agent/tools/memory.py): Долговременная память (`MemoryManager`).
  * Хранилище: `data/memory.json`.
  * Атомарная запись через `.tmp` и `os.replace`.
  * Фильтрация системного мусора и дампов ошибок (`is_valid_memory_text`).
  * Дедупликация фактов по нормализованному тексту.
  * Экспортируемые инструменты: `remember`, `recall_memory`, `forget_memory`.
* [tools/household.py](file:///c:/Akakiy%20agent/tools/household.py): Бытовой менеджер (`HouseholdManager`).
  * Хранилище: `data/household.json`.
  * Атомарная запись и потокобезопасность.
  * Сущности: Задачи (Tasks), Напоминания (Reminders), Заметки (Notes), Списки (Lists).
  * Поддержка пакетного и относительного удаления (`_resolve_delete_targets`).
  * Парсер времени напоминаний (`parse_reminder_time`).

### 3.5. Инструментальный слой (Tools Layer)
* [tools/registry.py](file:///c:/Akakiy%20agent/tools/registry.py): Центральный реестр `TOOLS` (23 зарегистрированных инструмента) с описаниями, схемами параметров и флагами подтверждения `requires_confirmation`.
* [tools/dispatcher.py](file:///c:/Akakiy%20agent/tools/dispatcher.py): Функция `dispatch()` — вызов инструментов по имени с перехватом подтверждений через коллбэк.
* [tools/files.py](file:///c:/Akakiy%20agent/tools/files.py): `list_files`, `find_file`, `read_file`, `write_file`, `edit_file`, `search_files`.
* [tools/terminal.py](file:///c:/Akakiy%20agent/tools/terminal.py): Безопасное исполнение команд PowerShell `run_command`.
* [tools/git.py](file:///c:/Akakiy%20agent/tools/git.py): `git_status`, `git_diff`, `git_commit`, `git_log`, `git_push`.
* [tools/analysis.py](file:///c:/Akakiy%20agent/tools/analysis.py): Статический анализ Python-файлов через AST `analyze_file`.
* [tools/validation.py](file:///c:/Akakiy%20agent/tools/validation.py): Проверка синтаксиса проекта через `py_compile` (`validate_project`).

---

## 4. Потоки данных (Data Flows)

### Поток 1: Обработка пользовательского запроса (CLI / GUI)
```
Пользователь (Текст)
   │
   ▼
Agent.process(user_input)
   │
   ├─► 1. Проверка choose_tool() (Детерминированный fast-path)
   │       ├─ Найдено совпадение (задачи, заметки, списки, память, файлы)
   │       │     ▼
   │       │   Agent.execute_tool(tool_name, args)  [Латентность < 1 мс]
   │       │     ▼
   │       │   ContextManager.record_interaction()
   │       │     ▼
   │       └─► Ответ клиенту (CLI / GUI)
   │
   └─► 2. Не совпало (Свободный естественный язык / сложный запрос)
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

---

## 5. Политика изоляции и безопасность

1. **Изоляция пользовательских данных**: Все пользовательские заметки, задачи, списки и факты долговременной памяти хранятся строго в `data/*.json`, которые добавлены в `.gitignore` и никогда не попадают в систему контроля версий.
2. **Защита от перезаписи и потери данных**: Все операции модификации JSON используют атомарную запись: сериализация во временный файл (`.tmp`) с последующей заменой целевого файла через `os.replace`.
3. **Подтверждение опасных действий**: Инструменты с потенциально деструктивным эффектом (`delete_*`, `write_file`, `edit_file`, `git_commit`, `git_push`, `run_command`) имеют флаг `requires_confirmation = True` и блокируют выполнение до получения явного согласия пользователя.
4. **Защита от prompt injection**: Пользовательские данные памяти передаются в LLM строго в отдельной секции справочной информации (с маркировкой доверия), не модифицируя неизменяемый системный промпт ассистента.
