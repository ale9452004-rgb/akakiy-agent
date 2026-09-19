"""
Модуль подготовки точечных изменений файлов (детерминированная логика и LLM).
"""

import json
import re

from ollama_client import OllamaClient
from tools.dispatcher import dispatch


class EditPreparer:
    """
    Отвечает за подготовку точечных изменений файлов.
    Поддерживает детерминированную замену и fallback на модель Ollama с retry-логикой.
    """

    def __init__(self, ai_client=None):
        self.ai = ai_client or OllamaClient()

    def prepare_edit(self, filename, user_request):
        """
        Подготавливает изменение файла.

        Для простых точечных текстовых изменений
        сначала используется детерминированная
        обработка Python без AI.

        Если запрос нельзя однозначно обработать
        как простую замену, используется AI.

        Само изменение выполняется отдельно
        через edit_file.
        """

        read_result = dispatch(
            "read_file",
            filename=filename
        )

        if not read_result.get("success"):
            return {
                "success": False,
                "message": (
                    "Не удалось прочитать файл "
                    f"{filename}."
                ),
                "result": read_result
            }

        file_result = read_result.get("result")

        if not isinstance(file_result, dict):
            return {
                "success": False,
                "message": (
                    "Инструмент чтения файла "
                    "вернул некорректный результат."
                )
            }

        if not file_result.get("success"):
            return {
                "success": False,
                "message": file_result.get(
                    "message",
                    "Не удалось получить содержимое файла."
                )
            }

        current_content = file_result.get("content")

        if current_content is None:
            return {
                "success": False,
                "message": "Содержимое файла отсутствует."
            }

        # =================================================
        # Детерминированное точечное изменение
        # =================================================

        simple_edit = self._try_prepare_simple_text_edit(
            user_request=user_request,
            current_content=current_content
        )

        if simple_edit["success"]:
            return {
                "success": True,
                "filename": filename,
                "old_text": simple_edit["old_text"],
                "new_text": simple_edit["new_text"],
                "method": "deterministic"
            }

        # =================================================
        # Попытка №1 через AI
        # =================================================

        prepared = self._request_edit(
            filename=filename,
            user_request=user_request,
            current_content=current_content
        )

        validation = self._validate_prepared_edit(
            prepared,
            current_content
        )

        if validation["success"]:
            semantic = self._validate_edit_semantics(
                filename=filename,
                user_request=user_request,
                old_text=prepared["old_text"],
                new_text=prepared["new_text"],
                current_content=current_content
            )

            if semantic["success"]:
                return {
                    "success": True,
                    "filename": filename,
                    "old_text": prepared["old_text"],
                    "new_text": prepared["new_text"],
                    "method": "ai"
                }

            first_error = semantic["message"]

        else:
            first_error = validation["message"]

        # =================================================
        # Попытка №2 через AI
        # =================================================

        prepared = self._request_edit_retry(
            filename=filename,
            user_request=user_request,
            current_content=current_content,
            previous_error=first_error
        )

        validation = self._validate_prepared_edit(
            prepared,
            current_content
        )

        if not validation["success"]:
            return {
                "success": False,
                "message": (
                    "AI не смог подготовить корректное "
                    "точечное изменение файла после "
                    "двух попыток.\n\n"
                    f"Причина: {validation['message']}"
                ),
                "raw_response": prepared
            }

        semantic = self._validate_edit_semantics(
            filename=filename,
            user_request=user_request,
            old_text=prepared["old_text"],
            new_text=prepared["new_text"],
            current_content=current_content
        )

        if not semantic["success"]:
            return {
                "success": False,
                "message": semantic["message"],
                "old_text": prepared["old_text"],
                "new_text": prepared["new_text"]
            }

        return {
            "success": True,
            "filename": filename,
            "old_text": prepared["old_text"],
            "new_text": prepared["new_text"],
            "method": "ai"
        }

    def _try_prepare_simple_text_edit(
        self,
        user_request,
        current_content
    ):
        """
        Пытается определить простое текстовое изменение
        без обращения к AI.
        Поддерживаемый формат:

        Измени строку с сообщением X
        на сообщение Y

        Также поддерживаются варианты:

        Измени текст X на Y
        Замени сообщение X на сообщение Y
        Замени текст X на текст Y

        Если исходный текст встречается несколько раз,
        выбирается наиболее вероятная строка реального
        кода, а не строка внутри prompt/docstring.

        Метод ничего не изменяет в файле.
        Он только возвращает old_text/new_text.
        """

        if not isinstance(user_request, str):
            return {
                "success": False,
                "message": (
                    "Пользовательский запрос "
                    "имеет некорректный тип."
                )
            }

        if not isinstance(current_content, str):
            return {
                "success": False,
                "message": (
                    "Содержимое файла "
                    "имеет некорректный тип."
                )
            }

        request = user_request.strip()

        # -------------------------------------------------
        # Если запрос содержит служебный контекст Planner,
        # используем только формулировку текущего шага.
        # -------------------------------------------------

        step_marker = "Задача текущего шага:"

        if step_marker in request:
            request = request.split(
                step_marker,
                1
            )[1].strip()

            context_marker = "Результаты предыдущих шагов:"

            if context_marker in request:
                request = request.split(
                    context_marker,
                    1
                )[0].strip()

        if not request:
            return {
                "success": False,
                "message": "Запрос пуст."
            }

        # -------------------------------------------------
        # Форматы простых текстовых замен
        # -------------------------------------------------

        patterns = [
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            (?:строку\s+с\s+)?
            сообщением
            \s+
            (?P<old_quote>["'])(?P<old>.*?)(?P=old_quote)
            \s+
            на
            \s+
            (?P<new_quote>["'])(?P<new>.*?)(?P=new_quote)
            (?:\s+.*)?$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            (?:строку\s+с\s+)?
            текстом
            \s+
            (?P<old_quote>["'])(?P<old>.*?)(?P=old_quote)
            \s+
            на
            \s+
            (?P<new_quote>["'])(?P<new>.*?)(?P=new_quote)
            (?:\s+.*)?$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            строку
            \s+
            с
            \s+
            текстом
            \s+
            (?P<old_quote>["'])(?P<old>.*?)(?P=old_quote)
            \s+
            на
            \s+
            (?P<new_quote>["'])(?P<new>.*?)(?P=new_quote)
            (?:\s+.*)?$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            текст
            \s+
            (?P<old_quote>["'])(?P<old>.*?)(?P=old_quote)
            \s+
            на
            \s+
            (?P<new_quote>["'])(?P<new>.*?)(?P=new_quote)
            (?:\s+.*)?$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            (?:строку\s+с\s+)?
            сообщением
            \s+
            (?P<old>.+?)
            \s+
            на
            \s+
            сообщение
            \s+
            (?P<new>.+?)
            \s*$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            (?:строку\s+с\s+)?
            текстом
            \s+
            (?P<old>.+?)
            \s+
            на
            \s+
            текст
            \s+
            (?P<new>.+?)
            \s*$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            строку
            \s+
            с
            \s+
            текстом
            \s+
            (?P<old>.+?)
            \s+
            на
            \s+
            (?P<new>.+?)
            \s*$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            текст
            \s+
            (?P<old>.+?)
            \s+
            на
            \s+
            (?P<new>.+?)
            \s*$
            """,
            r"""
            ^\s*
            (?:измени|изменить|замени|заменить)
            \s+
            (?:строку\s+с\s+)?
            сообщением
            \s+
            (?P<old>.+?)
            \s+
            на
            \s+
            (?P<new>.+?)
            \s*$
            """,
        ]

        match = None

        for pattern in patterns:
            candidate = re.match(
                pattern,
                request,
                flags=re.IGNORECASE | re.VERBOSE
            )

            if candidate:
                match = candidate
                break

        if not match:
            return {
                "success": False,
                "message": (
                    "Запрос не распознан как простая "
                    "текстовая замена."
                )
            }

        old_text = match.group("old").strip()
        new_text = match.group("new").strip()

        # -------------------------------------------------
        # Определяем семантический приоритет.
        # -------------------------------------------------

        preferred_key = None
        normalized_request = request.lower()

        if (
            "строку с сообщением" in normalized_request
            or "сообщением" in normalized_request
        ):
            preferred_key = "message"

        elif (
            "строку с текстом" in normalized_request
            or "текстом" in normalized_request
        ):
            preferred_key = "message"

        # -------------------------------------------------
        # Убираем внешние кавычки.
        # -------------------------------------------------

        old_text = self._strip_matching_quotes(
            old_text
        )

        new_text = self._strip_matching_quotes(
            new_text
        )

        if not old_text or not new_text:
            return {
                "success": False,
                "message": (
                    "Не удалось определить "
                    "старый или новый текст."
                )
            }

        if old_text == new_text:
            return {
                "success": False,
                "message": (
                    "Старый и новый текст совпадают."
                )
            }

        # -------------------------------------------------
        # Ищем строки, содержащие old_text.
        # -------------------------------------------------

        lines = current_content.splitlines(
            keepends=True
        )

        candidates = []

        for index, line in enumerate(lines):
            if old_text not in line:
                continue

            candidates.append({
                "index": index,
                "line": line,
                "score": self._score_text_edit_candidate(
                    line=line,
                    lines=lines,
                    index=index,
                    old_text=old_text,
                    preferred_key=preferred_key
                )
            })

        if not candidates:
            return {
                "success": False,
                "message": (
                    "Исходный текст не найден "
                    "в текущем файле."
                )
            }

        # -------------------------------------------------
        # Если кандидат один — используем его.
        # -------------------------------------------------

        if len(candidates) == 1:
            selected = candidates[0]

        else:
            candidates.sort(
                key=lambda item: item["score"],
                reverse=True
            )

            best = candidates[0]
            second = candidates[1]

            if best["score"] <= second["score"]:
                return {
                    "success": False,
                    "message": (
                        "Исходный текст найден в нескольких "
                        "равнозначных местах файла."
                    )
                }

            selected = best

        line = selected["line"]

        # -------------------------------------------------
        # В точечном режиме old_text становится всей
        # строкой кода.
        # -------------------------------------------------

        line_without_newline = line.rstrip("\r\n")

        new_line = line_without_newline.replace(
            old_text,
            new_text,
            1
        )

        if new_line == line_without_newline:
            return {
                "success": False,
                "message": (
                    "Не удалось сформировать "
                    "новую строку."
                )
            }

        return {
            "success": True,
            "old_text": line_without_newline,
            "new_text": new_line,
            "message": (
                "Простое текстовое изменение "
                "подготовлено без AI."
            )
        }

    def _score_text_edit_candidate(
        self,
        line,
        lines,
        index,
        old_text,
        preferred_key=None
    ):
        """
        Оценивает вероятность того, что строка является
        реальным Python-кодом, а не текстом prompt/docstring.
        """

        score = 0
        stripped = line.strip()

        if ":" in stripped:
            score += 2

        if "=" in stripped:
            score += 2

        if stripped.startswith((
            '"',
            "'",
            "return ",
            "print(",
            "raise ",
            "self.",
        )):
            score += 2

        if "{" in stripped or "}" in stripped:
            score += 2

        if re.search(
            r"""["'][^"']+["']\s*:\s*["']""",
            stripped
        ):
            score += 6

        if preferred_key:
            key_pattern = (
                rf"""["']{re.escape(preferred_key)}["']\s*:"""
            )

            if re.search(
                key_pattern,
                stripped,
                flags=re.IGNORECASE
            ):
                score += 8

        if re.search(
            r"\breturn\b",
            stripped
        ):
            score += 3

        if re.search(
            r"\bself\.[A-Za-z_][A-Za-z0-9_]*",
            stripped
        ):
            score += 3

        if stripped.startswith("#"):
            score -= 8

        if stripped.startswith(
            (
                "Твоя задача",
                "КРИТИЧЕСКИ ВАЖНО",
                "ВАЖНО",
                "ОБЯЗАТЕЛЬНО",
                "Нужно",
                "Если пользователь",
                "Например",
                "Нельзя",
                "НЕ ",
                "Не ",
                "Верни",
                "Формат",
            )
        ):
            score -= 5

        if '"""' in stripped or "'''" in stripped:
            score -= 6

        start = max(0, index - 5)
        end = min(len(lines), index + 6)

        nearby = "\n".join(
            lines[start:end]
        )

        prompt_markers = (
            "Ты — ИИ-агент",
            "Текущий файл",
            "Задача пользователя",
            "Верни только JSON",
            "НЕ ПИШИ",
            "КРИТИЧЕСКИ ВАЖНО",
        )

        for marker in prompt_markers:
            if marker in nearby:
                score -= 2

        if old_text in stripped:
            score += 1

        return score

    def _strip_matching_quotes(self, value):
        """
        Убирает внешние парные кавычки вокруг значения.
        """

        value = value.strip()

        if len(value) < 2:
            return value

        quote_pairs = [
            ('"', '"'),
            ("'", "'"),
            ("«", "»"),
        ]

        for opening, closing in quote_pairs:
            if (
                value.startswith(opening)
                and value.endswith(closing)
            ):
                return value[1:-1].strip()

        return value

    def _request_edit(
        self,
        filename,
        user_request,
        current_content
    ):
        """
        Первая попытка получить изменение в JSON.
        """

        prompt = f"""
Ты — ИИ-агент Акакий.

Нужно подготовить ОДНО точечное изменение файла.

Файл:

{filename}

Задача пользователя:

{user_request}

Текущий файл:

----- НАЧАЛО ФАЙЛА -----

{current_content}

----- КОНЕЦ ФАЙЛА -----

Твоя задача — найти ИМЕННО ТОТ фрагмент,
который относится к задаче пользователя.

КРИТИЧЕСКИ ВАЖНО:

Не выбирай случайный существующий текст.

Сначала определи, ЧТО именно просит изменить пользователь.

Затем найди в файле конкретный текст,
который непосредственно реализует это поведение.

Если пользователь просит изменить конкретный текст,
old_text должен содержать именно этот текст
и достаточный контекст, чтобы однозначно определить
нужное место.

Нельзя изменять другие строки файла,
даже если они технически подходят для замены.

ОБЯЗАТЕЛЬНО:

- old_text должен существовать в файле;
- old_text должен встречаться ровно один раз;
- old_text должен непосредственно относиться к задаче;
- new_text должен выполнять требуемое изменение;
- new_text должен отличаться от old_text;
- не переписывай весь файл;
- не используй случайные фрагменты;
- не объясняй решение;
- не пиши комментарии;
- не используй Markdown;
- верни только JSON.

Формат:

{{
    "old_text": "существующий фрагмент",
    "new_text": "новый фрагмент"
}}
"""

        response = self.ai.ask(
            prompt,
            add_to_history=False
        )

        return self._parse_json_response(
            response
        )

    def _request_edit_retry(
        self,
        filename,
        user_request,
        current_content,
        previous_error
    ):
        """
        Вторая и последняя попытка получить
        корректное точечное изменение.
        """

        prompt = f"""
Ты исправляешь результат предыдущей попытки
подготовки изменения файла.

Файл:

{filename}

Задача пользователя:

{user_request}

Предыдущая ошибка:

{previous_error}

Текущий файл:

----- НАЧАЛО ФАЙЛА -----

{current_content}

----- КОНЕЦ ФАЙЛА -----

Нужно вернуть ОДНО точечное изменение.

Сначала сопоставь задачу пользователя
с конкретным текстом файла.

ВАЖНО:

Если пользователь просит изменить конкретный текст,
old_text должен содержать именно этот текст
и достаточный контекст для однозначного выбора.

Не выбирай другой участок файла
только потому, что он существует.

old_text должен:

- существовать в текущем файле;
- встречаться ровно один раз;
- непосредственно соответствовать задаче;
- быть достаточно конкретным.

new_text должен непосредственно выполнять
задачу пользователя.

НЕЛЬЗЯ использовать в качестве old_text
слишком общие конструкции:

return

return {{

if

else

elif

pass

continue

break

{{

}}

Если меняется конкретная строка,
выбери эту строку или несколько соседних строк
с необходимым контекстом.

НЕ ПИШИ ОБЪЯСНЕНИЯ.

НЕ ПИШИ MARKDOWN.

НЕ ПИШИ ```.

Верни только JSON:

{{
    "old_text": "точный существующий фрагмент",
    "new_text": "новый фрагмент"
}}
"""

        response = self.ai.ask(
            prompt,
            add_to_history=False
        )

        return self._parse_json_response(
            response
        )

    def _validate_edit_semantics(
        self,
        filename,
        user_request,
        old_text,
        new_text,
        current_content
    ):
        """
        Проверяет, соответствует ли предложенное
        изменение реальной задаче пользователя.
        """

        prompt = f"""
Ты выполняешь строгую проверку безопасности
перед изменением файла.

Файл:

{filename}

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:

{user_request}

ПРЕДЛОЖЕННОЕ ИЗМЕНЕНИЕ:

OLD_TEXT:

{old_text}

NEW_TEXT:

{new_text}

Нужно определить, выполняет ли предложенное
изменение ИМЕННО задачу пользователя.

ACCEPT можно вернуть ТОЛЬКО если:

1. OLD_TEXT относится именно к объекту,
   поведению или тексту, который пользователь
   попросил изменить.

2. NEW_TEXT непосредственно реализует
   требуемое изменение.

3. Изменение не относится к другой части файла.

4. Изменение не является случайным.

5. Изменение можно напрямую связать
   с формулировкой задачи пользователя.

REJECT нужно вернуть, если:

- изменяется другой участок файла;
- изменение не решает задачу;
- изменение случайное;
- изменяется другой текст;
- связь с задачей пользователя неочевидна;
- есть сомнение в правильности изменения.

Особенно важно:

Если пользователь назвал конкретный текст,
проверь, что OLD_TEXT действительно содержит
этот текст.

При любом сомнении используй REJECT.

Ответь строго одним словом:

ACCEPT

или

REJECT

Не объясняй ответ.

Не используй Markdown.

Не добавляй другие слова.
"""

        response = self.ai.ask(
            prompt,
            add_to_history=False
        )

        if not isinstance(response, str):
            return {
                "success": False,
                "message": (
                    "Семантическая проверка "
                    "вернула некорректный ответ."
                )
            }

        normalized = response.strip().upper()

        if normalized == "ACCEPT":
            return {
                "success": True,
                "message": (
                    "Изменение соответствует задаче."
                )
            }

        if normalized == "REJECT":
            return {
                "success": False,
                "message": (
                    "Семантическая проверка отклонила "
                    "предложенное изменение: оно "
                    "не соответствует задаче пользователя."
                )
            }

        return {
            "success": False,
            "message": (
                "Семантическая проверка вернула "
                "неоднозначный ответ. "
                "Изменение отклонено для безопасности."
            )
        }

    def _parse_json_response(self, response):
        """
        Пытается извлечь JSON из ответа AI.
        """

        if not isinstance(response, str):
            return {
                "_error": (
                    "AI вернул ответ "
                    "некорректного типа."
                )
            }

        text = response.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            parts = text.split("```")

            for part in parts:
                candidate = part.strip()

                if candidate.lower().startswith("json"):
                    candidate = candidate[4:].strip()

                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        return {
            "_error": (
                "AI вернул некорректный JSON."
            ),
            "_raw_response": response
        }

    def _validate_prepared_edit(
        self,
        prepared,
        current_content
    ):
        """
        Проверяет результат, который вернул AI
        или детерминированный обработчик.
        """

        if not isinstance(prepared, dict):
            return {
                "success": False,
                "message": (
                    "AI вернул результат "
                    "некорректного формата."
                )
            }

        if prepared.get("_error"):
            return {
                "success": False,
                "message": prepared["_error"]
            }

        old_text = prepared.get("old_text")
        new_text = prepared.get("new_text")

        if not isinstance(old_text, str):
            return {
                "success": False,
                "message": (
                    "old_text отсутствует "
                    "или имеет некорректный тип."
                )
            }

        if not isinstance(new_text, str):
            return {
                "success": False,
                "message": (
                    "new_text отсутствует "
                    "или имеет некорректный тип."
                )
            }

        if not old_text.strip():
            return {
                "success": False,
                "message": "old_text пустой."
            }

        if old_text == new_text:
            return {
                "success": False,
                "message": (
                    "old_text и new_text совпадают. "
                    "Изменение отсутствует."
                )
            }

        occurrences = current_content.count(
            old_text
        )

        if occurrences == 0:
            return {
                "success": False,
                "message": (
                    "old_text не найден "
                    "в текущем содержимом файла."
                )
            }

        if occurrences > 1:
            return {
                "success": False,
                "message": (
                    "old_text найден несколько раз. "
                    f"Количество совпадений: {occurrences}."
                )
            }

        normalized_old_text = old_text.strip()

        forbidden_fragments = {
            "return",
            "return {",
            "if",
            "else",
            "elif",
            "pass",
            "continue",
            "break",
            "{",
            "}",
        }

        if normalized_old_text in forbidden_fragments:
            return {
                "success": False,
                "message": (
                    "AI выбрал слишком короткий "
                    "или общий фрагмент."
                )
            }

        if len(normalized_old_text) < 10:
            return {
                "success": False,
                "message": (
                    "AI выбрал слишком короткий "
                    "фрагмент для безопасного изменения."
                )
            }

        return {
            "success": True
        }
