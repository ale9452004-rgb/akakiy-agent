"""
Модуль семантического компилятора промптов (PromptCompiler) для модели SDXL-Lightning в ComfyUI.

Обеспечивает:
1. Анализ пользовательского запроса на русском и английском языках:
   - определение основного объекта (subject) и его числа (единственное / множественное);
   - определение количества объектов (строго один / несколько);
   - выявление обязательных визуальных характеристик (цвет, текстура, шерсть/окрас);
   - выявление действий и поз (загорает, лежит, сидит, бежит и т.д.);
   - выявление локации, окружения и освещения (пляж, море, закат, солнце, лес и т.д.);
   - извлечение явных исключений ("без белой шерсти", "без других животных" и т.п.).
2. Формирование однозначного Positive Prompt для SDXL с тегами качества и акцентами.
3. Формирование строгого Negative Prompt для ComfyUI KSampler:
   - подавление лишних объектов (multiple cats, two cats, extra animals, group, crowd);
   - подавление нежелательных или конфликтующих признаков (white fur, black fur для рыжего кота);
   - устранение артефактов анатомии, искажений и водяных знаков.
4. Обобщённость: работает для любых объектов (животные, люди, техника, архитектура, природа),
   а не только для котов.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Базовый Negative Prompt для качества и артефактов SDXL
BASE_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, bad anatomy, ugly, watermark, signature, "
    "deformed limbs, extra limbs, bad proportions, duplicate, lowres, text, error"
)

# Словарь распознавания основных объектов (существительные)
# формат: (pattern, en_singular, en_plural, category)
SUBJECT_CATALOG: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\b(?:кот\w*|кошк\w*|котя\w*|кошач\w*|cat\w*|kitten\w*|feline)\b", re.IGNORECASE), "cat", "cats", "animal"),
    (re.compile(r"\b(?:собак\w*|п[её]с\w*|щен\w*|dog\w*|puppy|canine)\b", re.IGNORECASE), "dog", "dogs", "animal"),
    (re.compile(r"\b(?:лис\w*|fox\w*)\b", re.IGNORECASE), "fox", "foxes", "animal"),
    (re.compile(r"\b(?:волк\w*|wolf|wolves)\b", re.IGNORECASE), "wolf", "wolves", "animal"),
    (re.compile(r"\b(?:медвед\w*|мишк\w*|bear\w*)\b", re.IGNORECASE), "bear", "bears", "animal"),
    (re.compile(r"\b(?:лев|льв\w*|lion\w*)\b", re.IGNORECASE), "lion", "lions", "animal"),
    (re.compile(r"\b(?:тигр\w*|tiger\w*)\b", re.IGNORECASE), "tiger", "tigers", "animal"),
    (re.compile(r"\b(?:птиц\w*|пернат\w*|bird\w*|eagle\w*|parrot\w*)\b", re.IGNORECASE), "bird", "birds", "animal"),
    (re.compile(r"\b(?:лошад\w*|кон\w*|horse\w*|stallion|mare)\b", re.IGNORECASE), "horse", "horses", "animal"),
    (re.compile(r"\b(?:рыб\w*|рыбк\w*|fish)\b", re.IGNORECASE), "fish", "fishes", "animal"),
    (re.compile(r"\b(?:дракон\w*|dragon\w*)\b", re.IGNORECASE), "dragon", "dragons", "fantasy"),
    (re.compile(r"\b(?:робот\w*|киборг\w*|андроид\w*|robot\w*|cyborg\w*|android\w*)\b", re.IGNORECASE), "robot", "robots", "tech"),
    (re.compile(r"\b(?:человек\w*|люд\w*|person|people)\b", re.IGNORECASE), "person", "people", "human"),
    (re.compile(r"\b(?:девушк\w*|женщин\w*|woman|women|girl\w*)\b", re.IGNORECASE), "woman", "women", "human"),
    (re.compile(r"\b(?:парен\w*|мужчин\w*|man|men|boy\w*)\b", re.IGNORECASE), "man", "men", "human"),
    (re.compile(r"\b(?:машин\w*|автомоб\w*|спорткар\w*|авто\b|car\w*|vehicle\w*)\b", re.IGNORECASE), "car", "cars", "vehicle"),
    (re.compile(r"\b(?:самол[её]т\w*|вертол[её]т\w*|airplane|plane|helicopter)\b", re.IGNORECASE), "airplane", "airplanes", "vehicle"),
    (re.compile(r"\b(?:корабл\w*|лодк\w*|яхт\w*|катер\w*|ship\w*|boat\w*|yacht\w*)\b", re.IGNORECASE), "ship", "ships", "vehicle"),
    (re.compile(r"\b(?:замок\b|замк\w*|дворец\w*|дворц\w*|castle\w*|palace\w*)\b", re.IGNORECASE), "castle", "castles", "architecture"),
    (re.compile(r"\b(?:дом\b|дом[а-я]*|здани\w*|коттедж\w*|house\w*|building\w*|cottage\w*)\b", re.IGNORECASE), "house", "houses", "architecture"),
    (re.compile(r"\b(?:комнат\w*|гостин\w*|спальн\w*|кабинет\w*|room\w*|bedroom|living\s*room)\b", re.IGNORECASE), "room", "rooms", "interior"),
    (re.compile(r"\b(?:стол\b|стол[а-я]*|table\w*|desk\w*)\b", re.IGNORECASE), "table", "tables", "furniture"),
    (re.compile(r"\b(?:окн\w*|window\w*)\b", re.IGNORECASE), "window", "windows", "interior"),
    (re.compile(r"\b(?:улиц\w*|street\w*)\b", re.IGNORECASE), "street", "streets", "scenery"),
    (re.compile(r"\b(?:город\w*|city\w*|town\w*)\b", re.IGNORECASE), "city", "cities", "scenery"),
    (re.compile(r"\b(?:лес\w*|тайг\w*|forest\w*|woods)\b", re.IGNORECASE), "forest", "forests", "nature"),
    (re.compile(r"\b(?:озер\w*|lake\w*)\b", re.IGNORECASE), "lake", "lakes", "nature"),
    (re.compile(r"\b(?:пейзаж\w*|ландшафт\w*|landscape\w*|scenery)\b", re.IGNORECASE), "landscape", "landscapes", "scenery"),
]

NON_SUBJECT_WORDS: Set[str] = {
    "cinematic", "photorealistic", "wooden", "metallic", "glass", "slender", "chubby",
    "gothic", "sunset", "sunrise", "misty", "foggy", "golden", "bright", "dark",
    "warm", "cold", "blue", "red", "green", "orange", "white", "black", "grey", "gray",
    "vibrant", "rich", "pure", "shot", "style", "view", "background", "lighting",
    "color", "texture", "detailed", "quality", "masterpiece", "sharp", "focus",
    "indoor", "outdoor", "cozy", "urban", "modern", "vintage", "retro", "evening",
    "night", "morning", "day", "light", "shadow", "glow", "atmosphere", "atmospheric",
    "clean", "scene", "soft", "spectacular", "photograph", "photo", "image", "picture",
    "art", "rendering", "finish", "tone", "aesthetic", "slim", "plump", "lean", "muscular",
    "dusk", "twilight", "reflection", "reflective", "transparent", "clear"
}

# Маркеры цвета и окраса: (regex, positive_en, negative_en)
COLOR_CATALOG: List[Tuple[re.Pattern, List[str], List[str]]] = [
    (
        re.compile(r"\b(?:рыж\w*|оранжев\w*|ginger|orange fur|orange coat|red fur)\b", re.IGNORECASE),
        ["vibrant ginger fur", "rich orange fur", "orange tabby", "bright ginger coat"],
        ["white fur", "black fur", "grey fur", "dark fur", "calico", "spotted fur"]
    ),
    (
        re.compile(r"\b(?:бел\w*|white fur|white coat|pure white)\b", re.IGNORECASE),
        ["pure white fur", "snow white coat"],
        ["black fur", "orange fur", "ginger fur", "brown fur", "spotted"]
    ),
    (
        re.compile(r"\b(?:ч[её]рн\w*|black fur|black coat|jet black)\b", re.IGNORECASE),
        ["jet black fur", "glossy black coat"],
        ["white fur", "orange fur", "ginger fur", "grey fur"]
    ),
    (
        re.compile(r"\b(?:сер\w*|grey fur|gray fur|silver coat)\b", re.IGNORECASE),
        ["silver grey fur", "grey coat"],
        ["orange fur", "ginger fur", "white fur"]
    ),
    (
        re.compile(r"\b(?:коричнев\w*|бур\w*|brown fur|chocolate coat)\b", re.IGNORECASE),
        ["rich brown fur", "warm chocolate coat"],
        ["white fur", "orange fur", "black fur"]
    ),
    (
        re.compile(r"\b(?:золот\w*|золотист\w*|golden)\b", re.IGNORECASE),
        ["golden shimmering fur", "warm golden tone"],
        []
    ),
    (
        re.compile(r"\b(?:зел[её]н\w*|green)\b", re.IGNORECASE),
        ["vibrant green"],
        []
    ),
    (
        re.compile(r"\b(?:син\w*|голуб\w*|blue)\b", re.IGNORECASE),
        ["deep blue", "azure"],
        []
    ),
    (
        re.compile(r"\b(?:красн\w*|red)\b", re.IGNORECASE),
        ["vivid red"],
        []
    ),
]

# Маркеры действий и поз
ACTION_CATALOG: List[Tuple[re.Pattern, List[str]]] = [
    (
        re.compile(r"\b(?:загора\w*|гре[еет]\w*|sunbath\w*|basking)\b", re.IGNORECASE),
        ["sunbathing", "basking in the warm sun", "relaxing under sunlight"]
    ),
    (
        re.compile(r"\b(?:леж[аит]\w*|отдыха\w*|lying|reclining)\b", re.IGNORECASE),
        ["lying down comfortably", "relaxed posture on the ground"]
    ),
    (
        re.compile(r"\b(?:сид[еия]\w*|sitting|seated)\b", re.IGNORECASE),
        ["sitting upright", "attentive posture"]
    ),
    (
        re.compile(r"\b(?:сто[ия]\w*|standing)\b", re.IGNORECASE),
        ["standing"]
    ),
    (
        re.compile(r"\b(?:беж\w*|бег\w*|running)\b", re.IGNORECASE),
        ["running dynamically", "in motion"]
    ),
    (
        re.compile(r"\b(?:сп[ия]\w*|засну\w*|sleeping|asleep)\b", re.IGNORECASE),
        ["sleeping peacefully", "curled up asleep"]
    ),
    (
        re.compile(r"\b(?:плава\w*|плыв\w*|swimming)\b", re.IGNORECASE),
        ["swimming in water"]
    ),
    (
        re.compile(r"\b(?:игра\w*|playing|playful)\b", re.IGNORECASE),
        ["playful", "playing"]
    ),
    (
        re.compile(r"\b(?:смотр\w*|глядя\w*|looking|gazing)\b", re.IGNORECASE),
        ["looking towards the viewer", "curious expression"]
    ),
]

# Маркеры локации, фона и окружения
ENVIRONMENT_CATALOG: List[Tuple[re.Pattern, List[str]]] = [
    (
        re.compile(r"\b(?:пляж\w*|пес[оч]\w*|beach|sandy beach|seashore)\b", re.IGNORECASE),
        ["on a sandy beach", "golden warm sand", "coastal shoreline"]
    ),
    (
        re.compile(r"\b(?:мор[яееиуом]\w*|морск\w*|океан\w*|sea|ocean|waves)\b", re.IGNORECASE),
        ["sea in the background", "ocean waves", "blue water horizon"]
    ),
    (
        re.compile(r"\b(?:солн\w*|солнечн\w*|sunny|bright sun)\b", re.IGNORECASE),
        ["sunny day", "bright natural sunlight", "clear summer sky"]
    ),
    (
        re.compile(r"\b(?:закат\w*|sunset|golden hour)\b", re.IGNORECASE),
        ["golden hour", "spectacular warm sunset", "soft evening glow"]
    ),
    (
        re.compile(r"\b(?:рассвет\w*|sunrise|dawn)\b", re.IGNORECASE),
        ["sunrise lighting", "early morning glow"]
    ),
    (
        re.compile(r"\b(?:ночь\w*|ночн\w*|night|nighttime)\b", re.IGNORECASE),
        ["nighttime", "starry sky", "moonlight"]
    ),
    (
        re.compile(r"\b(?:лес\w*|тайг\w*|бор\b|рощ\w*|деревь\w*|деревья|дерево\b|дерева\b|деревьев|forest|woods|trees)\b", re.IGNORECASE),
        ["in a lush forest", "tall green trees"]
    ),
    (
        re.compile(r"\b(?:гор\w*|скал\w*|mountain\w*|rock\w*)\b", re.IGNORECASE),
        ["mountain landscape", "majestic peaks"]
    ),
    (
        re.compile(r"\b(?:город\w*|улиц\w*|city|urban|street)\b", re.IGNORECASE),
        ["modern city background", "urban street"]
    ),
    (
        re.compile(r"\b(?:комнат\w*|дом[ае]\b|интерьер\w*|indoor|room)\b", re.IGNORECASE),
        ["cozy indoor room", "warm interior lighting"]
    ),
    (
        re.compile(r"\b(?:зим\w*|снег\w*|winter|snow)\b", re.IGNORECASE),
        ["winter scenery", "snowy ground"]
    ),
]

# Паттерны отрицаний пользователя ("без X", "не Y")
EXPLICIT_EXCLUSION_PATTERN = re.compile(
    r"\b(?:без|кроме|исключ\w*|не\s+(?:нужно|надо|хочу)|without|no)\s+([а-яa-z0-9\s,\-]+?)(?=[,;.!?]|$)",
    re.IGNORECASE
)


class PromptCompiler:
    """
    Семантический компилятор промптов для SDXL-Lightning.
    Преобразует неструктурированные русские/английские описания в строго специфицированные
    Positive и Negative промпты для точного соответствия ограничениям модели.
    """

    @classmethod
    def compile(
        cls,
        raw_prompt: str,
        count: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        is_revision: bool = False,
        critique_details: Optional[str] = None
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Главный метод компиляции промпта.
        
        Args:
            raw_prompt: Исходный текст запроса пользователя (русский или английский).
            count: Явно заданное число объектов (если известно).
            negative_prompt: Базовый негативный промпт (если передан вызывающей стороной).
            is_revision: Флаг ревизии после замечания пользователя.
            critique_details: Дополнительный текст замечания пользователя.
            
        Returns:
            Tuple[compiled_positive, compiled_negative, metadata]
        """
        text = str(raw_prompt or "").strip()
        critique = str(critique_details or "").strip()
        combined_text = f"{text} {critique}".strip()

        # 1. Поиск основного объекта
        detected_subject = None
        detected_subject_plural = None
        detected_category = None

        for pattern, s_sing, s_plur, cat in SUBJECT_CATALOG:
            if pattern.search(combined_text):
                detected_subject = s_sing
                detected_subject_plural = s_plur
                detected_category = cat
                break

        # Если объект не из каталога, пробуем выделить английское существительное (исключая модификаторы и стили)
        if not detected_subject:
            en_words = re.findall(r"\b[a-zA-Z]{3,}\b", combined_text)
            candidates = [w.lower() for w in en_words if w.lower() not in NON_SUBJECT_WORDS]
            if candidates:
                detected_subject = candidates[0]
                detected_subject_plural = f"{detected_subject}s"
                detected_category = "general"
            else:
                detected_subject = None
                detected_subject_plural = None
                detected_category = "general"

        # 2. Определение количества объектов
        # Проверяем явные указания на единичность
        single_markers = re.search(
            r"\b(?:один|одн[аоу]|одним|одного|одной|1|1\s*шт|единственн\w*|solo|single|one|only\s+one)\b",
            combined_text,
            re.IGNORECASE
        )
        # Проверяем явные указания на множественность
        multi_markers = re.search(
            r"\b(?:два|две|двое|двух|2|три|тр[её]х|3|четыр\w*|4|нескольк\w*|пар[ау]|two|three|multiple|group)\b",
            combined_text,
            re.IGNORECASE
        )

        is_singular = True
        if count is not None and count > 1:
            is_singular = False
        elif multi_markers and not single_markers:
            is_singular = False
        elif single_markers:
            is_singular = True
        else:
            # По умолчанию в русском запросе единичное существительное (кот, собака) считается одним объектом
            is_singular = True

        # Если в critique указано "а я просил одного" — жестко форсируем singular
        if re.search(r"\b(?:одного|одну|один|только\s+один|single|one)\b", critique, re.IGNORECASE):
            is_singular = True

        # 3. Извлечение цветов и окраса
        positive_colors: List[str] = []
        negative_colors: List[str] = []

        for pattern, pos_tags, neg_tags in COLOR_CATALOG:
            if pattern.search(combined_text):
                for pt in pos_tags:
                    if pt not in positive_colors:
                        positive_colors.append(pt)
                for nt in neg_tags:
                    if nt not in negative_colors:
                        negative_colors.append(nt)

        # 4. Извлечение действий и поз
        positive_actions: List[str] = []
        for pattern, act_tags in ACTION_CATALOG:
            if pattern.search(combined_text):
                for at in act_tags:
                    if at not in positive_actions:
                        positive_actions.append(at)

        # 5. Извлечение окружения, фона и освещения
        positive_env: List[str] = []
        for pattern, env_tags in ENVIRONMENT_CATALOG:
            if pattern.search(combined_text):
                for et in env_tags:
                    if et not in positive_env:
                        positive_env.append(et)

        # 6. Обработка явных отрицаний пользователя ("без белой шерсти", "без других животных")
        user_explicit_negatives: List[str] = []
        for match in EXPLICIT_EXCLUSION_PATTERN.finditer(combined_text):
            neg_phrase = match.group(1).strip()
            # Переводим частые маркеры исключений
            if re.search(r"бел\w*\s+шерст\w*|бел\w*", neg_phrase, re.IGNORECASE):
                user_explicit_negatives.append("white fur")
            if re.search(r"черн\w*|чёрн\w*", neg_phrase, re.IGNORECASE):
                user_explicit_negatives.append("black fur")
            if re.search(r"друг\w*\s+животн\w*|лишн\w*", neg_phrase, re.IGNORECASE):
                user_explicit_negatives.extend(["extra animals", "multiple animals", "other animals"])
            if re.search(r"люд\w*|человек\w*", neg_phrase, re.IGNORECASE):
                user_explicit_negatives.extend(["people", "humans", "person"])
            if re.search(r"два\s+кот\w*|двух\s+кот\w*", neg_phrase, re.IGNORECASE):
                user_explicit_negatives.extend(["two cats", "multiple cats", "pair of cats"])

        # 7. Формирование Positive Prompt
        pos_parts: List[str] = []

        # Строгое количество и субъект (если субъект определен)
        if detected_subject:
            if is_singular:
                pos_parts.append(f"solo, single {detected_subject}, 1{detected_subject}")
            else:
                eff_count = count if (count and count > 1) else 2
                pos_parts.append(f"{eff_count} {detected_subject_plural}")

        # Цвета и окрас
        if positive_colors:
            pos_parts.extend(positive_colors)

        # Действие / поза
        if positive_actions:
            pos_parts.extend(positive_actions)

        # Локация и окружение
        if positive_env:
            pos_parts.extend(positive_env)

        # Теги фотографического качества и реализма для SDXL
        pos_parts.extend([
            "photorealistic",
            "8k resolution",
            "highly detailed",
            "sharp focus",
            "cinematic lighting",
            "masterpiece"
        ])

        compiled_positive = ", ".join(pos_parts)

        # 8. Формирование Negative Prompt
        neg_parts: List[str] = []

        # Защита от лишних объектов (если требуется строго 1 конкретный объект)
        if is_singular and detected_subject:
            neg_parts.extend([
                f"multiple {detected_subject_plural}",
                f"two {detected_subject_plural}",
                f"extra {detected_subject_plural}",
                f"group of {detected_subject_plural}",
                "crowd",
                f"cloned {detected_subject}",
            ])
            if detected_category == "animal":
                neg_parts.extend([
                    "extra animals",
                    "two animals",
                    "multiple animals",
                ])
            elif detected_category == "human":
                neg_parts.extend([
                    "extra people",
                    "two people",
                    "multiple people",
                ])

        # Конфликтующие цвета (например, белая шерсть при запросе рыжего кота)
        if negative_colors:
            for nc in negative_colors:
                if nc not in neg_parts:
                    neg_parts.append(nc)

        # Явные исключения от пользователя
        for un in user_explicit_negatives:
            if un not in neg_parts:
                neg_parts.append(un)

        # Базовый негативный промпт качества
        base_neg = negative_prompt.strip() if negative_prompt else BASE_NEGATIVE_PROMPT
        for item in base_neg.split(","):
            cleaned = item.strip()
            if cleaned and cleaned not in neg_parts:
                neg_parts.append(cleaned)

        compiled_negative = ", ".join(neg_parts)

        metadata = {
            "subject": detected_subject,
            "subject_plural": detected_subject_plural,
            "category": detected_category,
            "is_singular": is_singular,
            "colors": positive_colors,
            "negative_colors": negative_colors,
            "actions": positive_actions,
            "environment": positive_env,
            "user_explicit_negatives": user_explicit_negatives,
            "is_revision": is_revision
        }

        return compiled_positive, compiled_negative, metadata


def compile_image_prompt(
    raw_prompt: str,
    count: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    is_revision: bool = False,
    critique_details: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """Функция-обёртка для вызова компилятора промптов."""
    return PromptCompiler.compile(
        raw_prompt=raw_prompt,
        count=count,
        negative_prompt=negative_prompt,
        is_revision=is_revision,
        critique_details=critique_details
    )
