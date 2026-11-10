"""
Модуль семантического планировщика редактирования изображений (EditPlanner).

Отвечает за ответственность Edit Planner:
1. Преобразование произвольной пользовательской инструкции в структурированный EditPlan.
2. Поддержку любых видов модификаций:
   - форма, пропорции, размеры (стройнее, массивнее, покатая крыша);
   - позы и положение (лежал, стоял, бежал);
   - добавление, замена, удаление элементов (добавь туман, убери забор, замени кота на собаку);
   - цвет, материалы, освещение, фон (рыжий, закатный свет, деревянный, море);
   - стиль и композиция (готический, кинематографичный, масляная живопись).
3. Гибридный анализ: быстрый детерминированный разбор (0 ms) + опциональный LLM-интерпретатор
   с валидацией и безопасным fallback.
4. Выбор подходящего режима обработки (img2img, pose_control, inpaint) и расчет адаптивного denoise.
5. Интеграцию с PromptCompiler для компиляции итоговых positive и negative промптов.
"""

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from tools.prompt_compiler import BASE_NEGATIVE_PROMPT, PromptCompiler

logger = logging.getLogger(__name__)


@dataclass
class EditPlan:
    """Структурированный план выполнения модификации изображения."""
    instruction: str
    target: str = "subject"
    action_type: str = "general"  # proportions, pose, remove, add, replace, color, lighting, background, style, general
    what_to_change: str = ""
    what_to_keep: str = "scene composition and context"
    recommended_mode: str = "img2img"  # img2img | pose_control | inpaint | text2img
    denoise: float = 0.60
    positive_prompt_additions: List[str] = field(default_factory=list)
    negative_prompt_additions: List[str] = field(default_factory=list)
    compiled_prompt: str = ""
    compiled_negative: str = BASE_NEGATIVE_PROMPT
    requires_specialized_model: Optional[str] = None  # "openpose" | "inpaint" | None
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instruction": self.instruction,
            "target": self.target,
            "action_type": self.action_type,
            "what_to_change": self.what_to_change,
            "what_to_keep": self.what_to_keep,
            "recommended_mode": self.recommended_mode,
            "denoise": self.denoise,
            "positive_prompt_additions": list(self.positive_prompt_additions),
            "negative_prompt_additions": list(self.negative_prompt_additions),
            "compiled_prompt": self.compiled_prompt,
            "compiled_negative": self.compiled_negative,
            "requires_specialized_model": self.requires_specialized_model,
            "explanation": self.explanation,
        }


class EditPlanner:
    """
    Планировщик операций редактирования изображений.
    """

    def __init__(self, ai_client: Optional[Any] = None) -> None:
        self.ai_client = ai_client

    def plan(
        self,
        instruction: str,
        base_prompt: str = "",
        active_image_path: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        use_llm: Optional[bool] = None
    ) -> EditPlan:
        """
        Главный метод создания плана редактирования.
        """
        instr = str(instruction or "").strip()
        base_p = str(base_prompt or "").strip()

        # 1. Быстрый детерминированный анализ (0 ms)
        fast_plan = self._deterministic_parse(instr, base_p)

        # 2. Семантический LLM-анализ: вызывается только для нераспознанных или общих инструкций
        # при наличии доступного ai_client (сохраняя детерминированный быстрый путь для известных категорий)
        should_use_llm = use_llm if use_llm is not None else (fast_plan.action_type == "general")
        if should_use_llm and self.ai_client:
            llm_plan = self._llm_parse(instr, base_p)
            if llm_plan:
                fast_plan = llm_plan

        # 3. Финализация промптов через PromptCompiler
        self._compile_effective_prompts(fast_plan, base_p)

        # 4. Проверка моделей и выставление требований
        if fast_plan.action_type == "pose":
            fast_plan.recommended_mode = "pose_control"
            fast_plan.requires_specialized_model = "openpose"
        elif fast_plan.action_type == "remove":
            fast_plan.recommended_mode = "inpaint"
            fast_plan.requires_specialized_model = "inpaint"
        else:
            fast_plan.recommended_mode = "img2img"
            fast_plan.requires_specialized_model = None

        return fast_plan

    def _deterministic_parse(self, instr: str, base_p: str) -> EditPlan:
        """
        Быстрый анализ текста на основе семантических паттернов.
        """
        text_lower = instr.lower()

        # Определение типа действия и параметров
        action_type = "general"
        target = "subject"
        what_to_change = instr
        what_to_keep = "основная сцена и окружение"
        denoise = 0.60
        pos_additions: List[str] = []
        neg_additions: List[str] = []

        action_text = text_lower
        # Выделение условий сохранения/изменения
        m_rev = re.search(
            r"^(?:сохрани[в]?|оставь|не\s+меняй)\s+(.+?)[,;\s]+(?:но|а|только|поменяй\s+только|сделай\s+только|при\s+этом)\s+(.+)$",
            text_lower,
            re.IGNORECASE
        )
        if m_rev:
            what_to_keep = m_rev.group(1).strip()
            action_text = m_rev.group(2).strip()
            what_to_change = action_text
        else:
            m_keep = re.search(
                r"[,;\s]+(?:сохрани[в]?|оставь|не\s+меняй|с\s+сохранением)\s+(.+)$",
                text_lower,
                re.IGNORECASE
            )
            if m_keep:
                what_to_keep = m_keep.group(1).strip()
                action_text = text_lower[:m_keep.start()].strip()
                what_to_change = action_text

        # 0. Конструкции замены: "замени/замена/поменяй <исходное> на <желаемое>", "преврати <объект> в <желаемое>" и англ. "replace <X> with <Y>"
        m_rep = re.search(
            r"\b(?:замен[аиеу]?|поменяй|смени)\s+(?:мне\s+)?(.+?)\s+на\s+(.+)$",
            action_text,
            re.IGNORECASE
        ) or re.search(
            r"\b(?:replace|swap|exchange)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:with|for|into|to)\s+(.+)$",
            action_text,
            re.IGNORECASE
        )
        if not m_rep:
            m_conv = re.search(
                r"\bпреврат\w*\s+(?:мне\s+)?(.+?)\s+в[о]?\s+(.+)$",
                action_text,
                re.IGNORECASE
            ) or re.search(
                r"\b(?:turn|transform|convert|change)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:into|to)\s+(.+)$",
                action_text,
                re.IGNORECASE
            )
            if m_conv:
                c_from = m_conv.group(1).strip().lower()
                c_to = m_conv.group(2).strip().lower()
                if (
                    c_from not in {"это", "it", "this", "scene", "image", "все", "всё", "картинку", "изображение", "сцену", "фото"}
                    and not re.match(r"^(?:что-то|нечто|something)\b", c_to, re.IGNORECASE)
                ):
                    m_rep = m_conv
        if m_rep:
            from_part = m_rep.group(1).strip()
            to_part = m_rep.group(2).strip()

            # Если изменение касается позы
            if re.search(r"\bпоз[ауыеой]\b", from_part) or re.search(r"\bпоз[ауыеой]\b", action_text):
                action_type = "pose"
                denoise = 0.70
                what_to_keep = "внешность персонажа, фон и стиль"
                what_to_change = f"поза -> {to_part}"
                if "спин" in action_text:
                    pos_additions.append("lying on back, belly up")
                elif "лежа" in action_text or "лежать" in action_text:
                    pos_additions.append("lying down, resting pose")
                elif "сидя" in action_text or "сидеть" in action_text:
                    pos_additions.append("sitting pose")
                elif "стоя" in action_text or "стоять" in action_text:
                    pos_additions.append("standing pose")

            # Если изменение касается цвета/окраса
            elif re.search(r"\b(?:цвет\w*|окрас\w*|шерст\w*)\b", from_part):
                action_type = "color"
                denoise = 0.45
                what_to_keep = "поза, форма объекта, композиция и фон"
                what_to_change = f"цвет -> {to_part}"
                if re.search(r"\b(?:ч[её]рн\w*)\b", to_part):
                    pos_additions.extend(["jet black", "glossy black"])
                    neg_additions.extend(["white", "ginger", "spotted"])
                elif re.search(r"\b(?:бел\w*)\b", to_part):
                    pos_additions.extend(["pure white", "snow white"])
                    neg_additions.extend(["black", "ginger", "dark"])
                elif re.search(r"\b(?:рыж\w*|оранжев\w*)\b", to_part):
                    pos_additions.extend(["vibrant ginger fur", "rich orange tabby"])
                    neg_additions.extend(["white fur", "black fur", "grey fur"])
                elif re.search(r"\b(?:син\w*)\b", to_part):
                    pos_additions.extend(["deep blue"])
                elif re.search(r"\b(?:красн\w*)\b", to_part):
                    pos_additions.extend(["vivid red"])

            # Если замена касается фона
            elif re.search(r"\bфон\w*\b", from_part):
                action_type = "background"
                denoise = 0.65
                what_to_change = f"фон -> {to_part}"
                what_to_keep = "главный персонаж/объект на переднем плане"
                target = "фон"
                if "закат" in to_part:
                    pos_additions.extend(["sunset sky background", "golden hour scenery"])
                elif "лес" in to_part:
                    pos_additions.extend(["lush green forest background", "pine trees"])
                elif "мор" in to_part or "пляж" in to_part:
                    pos_additions.extend(["sandy beach", "blue ocean waves"])
                elif "гор" in to_part:
                    pos_additions.extend(["mountain peaks", "rocky landscape"])
                elif "город" in to_part:
                    pos_additions.extend(["modern city skyline background"])
            else:
                action_type = "replace"
                denoise = 0.58
                what_to_change = f"{from_part} -> {to_part}"
                what_to_keep = "окружение и остальные элементы сцены"

                # Анализ исходного (удаляемого) состояния -> в negative_prompt_additions
                if re.search(r"\bдеревянн\w*\b|\bwood(?:en)?\b", from_part):
                    neg_additions.extend(["wooden", "wood material", "wooden texture"])
                elif re.search(r"\bстеклянн\w*\b|\bglass\b", from_part):
                    neg_additions.extend(["glass", "glass material"])
                elif re.search(r"\bметаллическ\w*\b|\bmetal(?:lic)?\b", from_part):
                    neg_additions.extend(["metallic", "metal"])
                elif re.search(r"\b(?:фарфор\w*|керамич\w*|ceramic|porcelain)\b", from_part):
                    neg_additions.extend(["porcelain", "ceramic"])
                if re.search(r"\bбел\w*\b|\bwhite\b", from_part):
                    neg_additions.append("white")
                elif re.search(r"\bч[её]рн\w*\b|\bblack\b", from_part):
                    neg_additions.append("black")
                elif re.search(r"\bсин\w*\b|\bblue\b", from_part):
                    neg_additions.append("blue")
                elif re.search(r"\bкрасн\w*\b|\bred\b", from_part):
                    neg_additions.append("red")
                elif re.search(r"\bрыж\w*|оранжев\w*\b|\b(?:ginger|orange)\b", from_part):
                    neg_additions.extend(["ginger", "orange"])

                if re.search(r"\b(?:кружк\w*|чашк\w*|mug|cup)\b", from_part):
                    neg_additions.extend(["mug", "ceramic cup"])
                elif re.search(r"\bбутыл\w*\b|\bbottle\b", from_part):
                    neg_additions.extend(["bottle", "glass bottle"])

                # Анализ целевого (желаемого) состояния -> в positive_prompt_additions
                if re.search(r"\bстеклянн\w*\b|\bglass\b", to_part):
                    pos_additions.extend(["glass material", "transparent glass finish"])
                elif re.search(r"\bдеревянн\w*\b|\bwood(?:en)?\b", to_part):
                    pos_additions.extend(["wooden texture", "polished wood"])
                elif re.search(r"\bметаллическ\w*\b|\bmetal(?:lic)?\b", to_part):
                    pos_additions.extend(["metallic surface", "chrome finish"])
                if re.search(r"\bбел\w*\b|\bwhite\b", to_part):
                    pos_additions.append("pure white")
                elif re.search(r"\bч[её]рн\w*\b|\bblack\b", to_part):
                    pos_additions.append("jet black")
                elif re.search(r"\bсин\w*\b|\bblue\b", to_part):
                    pos_additions.append("deep blue")
                elif re.search(r"\bкрасн\w*\b|\bred\b", to_part):
                    pos_additions.append("vivid red")
                elif re.search(r"\bрыж\w*|оранжев\w*\b|\b(?:ginger|orange)\b", to_part):
                    pos_additions.extend(["vibrant ginger", "rich orange"])
                if re.search(r"\bсобак\w*\b|\bdog\b", to_part):
                    pos_additions.extend(["dog", "canine"])
                elif re.search(r"\bкот\w*\b|\bcat\b", to_part):
                    pos_additions.extend(["cat", "feline"])
                elif re.search(r"\bбутыл\w*\b|\bbottle\b", to_part):
                    pos_additions.extend(["glass bottle", "bottle"])
                elif re.search(r"\b(?:кружк\w*|чашк\w*|mug|cup)\b", to_part):
                    pos_additions.extend(["mug", "cup"])

                for w in ("стол", "стул", "диван", "кот", "собака", "машина", "окно", "дверь", "дом", "забор", "cup", "mug", "bottle", "table", "chair", "cat", "dog", "car"):
                    if w in from_part or w in to_part:
                        target = w
                        break

        # 1. Поза и положение тела (pose)
        elif re.search(r"\b(?:поз[ауыеой]|положен\w*|ракурс\w*|лежал\w*|сидел\w*|стоял\w*|бежал\w*|поверни|разверни|на\s+спин\w*|на\s+бок\w*|на\s+живот\w*)\b", action_text):
            action_type = "pose"
            denoise = 0.70
            what_to_keep = "внешность персонажа, фон и стиль"
            if "спин" in action_text:
                pos_additions.append("lying on back, belly up")
            elif "лежа" in action_text or "лежать" in action_text:
                pos_additions.append("lying down, resting pose")
            elif "сидя" in action_text or "сидеть" in action_text:
                pos_additions.append("sitting pose")
            elif "стоя" in action_text or "стоять" in action_text:
                pos_additions.append("standing pose")

        # 2. Удаление объектов (remove)
        elif re.search(r"\b(?:убер\w*|удал\w*|сотри|стереть|лишн\w*|второ\w*\s+кот\w*|второг\w*|без\s+второг\w*)\b", action_text):
            action_type = "remove"
            denoise = 0.55
            what_to_keep = "основной объект и фон"
            neg_additions.extend(["extra objects", "duplicate", "extra limbs", "two subjects", "second cat"])
            pos_additions.append("single subject, clean scene")

        # 3. Фон, локация, окружение (background)
        elif re.search(r"\b(?:фон\w*|задн\w*\s+план\w*|пейзаж\w*|локаци\w*|окружен\w*|вместо\s+фона)\b", action_text) or (
            re.search(r"\b(?:мор\w*|пляж\w*|лес\w*|гор\w*|город\w*|комнат\w*|неб\w*)\b", action_text)
            and not re.search(r"\b(?:свет\w*|освещен\w*|туман\w*)\b", action_text)
        ):
            action_type = "background"
            denoise = 0.65
            what_to_keep = "главный персонаж/объект на переднем плане"
            if "закат" in action_text:
                pos_additions.extend(["sunset sky background", "golden hour scenery"])
            elif "лес" in action_text:
                pos_additions.extend(["lush green forest background", "pine trees"])
            elif "мор" in action_text or "пляж" in action_text:
                pos_additions.extend(["sandy beach", "blue ocean waves"])
            elif "гор" in action_text:
                pos_additions.extend(["mountain peaks", "rocky landscape"])
            elif "город" in action_text:
                pos_additions.extend(["modern city skyline background"])

        # 4. Пропорции, форма, размеры (proportions)
        elif re.search(r"\b(?:стройнее|худее|толще|массивнее|мускулист\w*|больше|меньше|размер\w*|пропорци\w*|форм\w*|покат\w*|вытянут\w*|круглее|шире|уже|длиннее|короче|толщин\w*)\b", action_text):
            action_type = "proportions"
            denoise = 0.55
            what_to_keep = "персонаж, окружение и цветовая гамма"
            if "стройнее" in action_text or "худее" in action_text:
                pos_additions.extend(["slender", "slim build", "lean proportions"])
                neg_additions.extend(["fat", "chubby", "overweight"])
            elif "толще" in action_text or "полнее" in action_text:
                pos_additions.extend(["chubby", "plump", "heavier build"])
                neg_additions.extend(["skinny", "slender"])
            elif "мускулист" in action_text:
                pos_additions.extend(["muscular", "athletic build"])
            elif "покат" in action_text:
                pos_additions.extend(["slanted", "sloped"])

        # 5. Цвет, окрас, текстура, материал (color / material)
        elif re.search(r"\b(?:цвет\w*|окрас\w*|шерст\w*|перекрас\w*|рыж\w*|бел\w*|ч[её]рн\w*|сер\w*|красн\w*|син\w*|зелен\w*|зел[её]н\w*|золот\w*|материал\w*|деревянн\w*|металлическ\w*|стеклянн\w*)\b", action_text):
            action_type = "color"
            denoise = 0.45
            what_to_keep = "поза, форма объекта, композиция и фон"
            if re.search(r"\b(?:рыж\w*|оранжев\w*)\b", action_text):
                pos_additions.extend(["vibrant ginger fur", "rich orange tabby"])
                neg_additions.extend(["white fur", "black fur", "grey fur"])
            elif re.search(r"\b(?:бел\w*)\b", action_text):
                pos_additions.extend(["pure white", "snow white"])
                neg_additions.extend(["black", "ginger", "dark"])
            elif re.search(r"\b(?:ч[её]рн\w*)\b", action_text):
                pos_additions.extend(["jet black", "glossy black"])
                neg_additions.extend(["white", "ginger", "spotted"])
            elif re.search(r"\b(?:деревянн\w*)\b", action_text):
                pos_additions.extend(["wooden texture", "polished wood"])
            elif re.search(r"\b(?:металлическ\w*)\b", action_text):
                pos_additions.extend(["metallic surface", "chrome metal finish"])
            elif re.search(r"\b(?:стеклянн\w*)\b", action_text):
                pos_additions.extend(["glass material", "transparent glass finish"])

        # 6. Освещение, погода, время суток (lighting)
        elif re.search(r"\b(?:освещен\w*|свет\w*|закат\w*|рассвет\w*|вечер\w*|тень\w*|тен\w*|ярче|темнее|туман\w*|солнц\w*|лун\w*|ночь\w*|ночн\w*|день\w*|пасмурн\w*|золот\w*\s+час)\b", action_text):
            action_type = "lighting"
            denoise = 0.50
            what_to_keep = "объекты сцены и их положение"
            if "закат" in action_text or "закатное" in action_text:
                pos_additions.extend(["sunset lighting", "golden hour", "warm orange glow"])
            elif "вечер" in action_text or "вечерн" in action_text:
                pos_additions.extend(["evening lighting", "dusk atmosphere", "warm twilight glow"])
            elif "туман" in action_text:
                pos_additions.extend(["misty fog", "atmospheric haze"])
            elif "ночь" in action_text or "ночн" in action_text:
                pos_additions.extend(["nighttime", "moonlight", "dark atmosphere"])
            elif "ярче" in action_text or "светлее" in action_text:
                pos_additions.extend(["bright daylight", "vibrant illumination"])

        # 7. Стиль, жанр, рендеринг (style)
        elif re.search(r"\b(?:стил\w*|реалистичн\w*|аниме|кинематограф\w*|акварел\w*|масл\w*|готическ\w*|футуристическ\w*|киберпанк|рисунок|картина\s+маслом|живопис\w*)\b", action_text):
            action_type = "style"
            denoise = 0.62
            what_to_keep = "композиция и сюжет сцены"
            if "готическ" in action_text:
                pos_additions.extend(["gothic architecture style", "dark moody aesthetic", "ornate spires"])
            elif "аниме" in action_text:
                pos_additions.extend(["anime style", "makoto shinkai aesthetic"])
            elif "кинематограф" in action_text:
                pos_additions.extend(["cinematic shot", "35mm photograph", "photorealistic"])

        # 8. Добавление или восстановление отсутствующего элемента (add)
        elif re.search(
            r"\b(?:добав\w*|дорисуй|пририсуй|вставь|помести|расположи|нарисуй|надень|наложи|положи|прицепи|"
            r"чтобы\s+(?:\w+\s+){0,3}(?:была|был|было|были|появил\w*)|появил\w*|не\s+хватает|отсутствует|нет\s+на\s+картинк\w*|нет\s+в\s+кадре)\b",
            action_text,
            re.IGNORECASE
        ):
            action_type = "add"
            denoise = 0.60
            what_to_keep = "остальные элементы сцены, композиция и фон"
            if re.search(r"\b(?:нив\w*|ваз[- ]?2121|2121|lada\s*niva)\b", action_text, re.IGNORECASE):
                target = "ВАЗ-2121 Нива"
                what_to_change = "добавление автомобиля ВАЗ-2121 Нива"
                what_to_keep = "штормовое море, берег, композиция и атмосфера исходника"
                pos_additions.extend([
                    "VAZ-2121 Niva",
                    "classic Russian compact 4x4 offroad vehicle",
                    "rugged 3-door SUV, boxy angular body, round front headlights",
                    "retro small offroader parked on the coastal shore",
                    "highly detailed automobile, sharp focus"
                ])
                neg_additions.extend([
                    "UAZ-450, van, minivan, bus, truck, commercial van, bukhanka, modern sleek sportscar",
                    "multiple cars, two cars, extra vehicles, duplicate cars"
                ])
            elif re.search(r"\b(?:машин\w*|автомоб\w*|авто\b|car\w*)\b", action_text, re.IGNORECASE):
                target = "автомобиль"
                what_to_change = "добавление автомобиля"
                pos_additions.extend(["automobile parked in scene", "detailed car"])
                neg_additions.extend(["multiple cars, extra vehicles"])
            elif re.search(r"\bотражен\w*\b", action_text):
                pos_additions.extend(["glass reflection", "reflective surface"])
            elif re.search(r"\bшляп\w*|кепк\w*|шапк\w*\b", action_text):
                pos_additions.extend(["wearing a hat"])
            elif re.search(r"\bочк\w*\b", action_text):
                pos_additions.extend(["wearing sunglasses"])
            elif re.search(r"\bтуман\w*\b", action_text):
                pos_additions.extend(["misty fog", "atmospheric haze"])

        # Извлечение вероятного объекта (существительного)
        if target == "subject":
            if re.search(r"\b(?:нив\w*|ваз[- ]?2121|2121|lada\s*niva)\b", text_lower, re.IGNORECASE):
                target = "ВАЗ-2121 Нива"
            else:
                m_subj = re.search(r"\b(?:кот\w*|кошк\w*|собак\w*|зам\w*|дом\w*|машин\w*|фон\w*|человек\w*|девушк\w*|парен\w*|крыш\w*|неб\w*|деревь\w*|дерево\b|стол\w*|окн\w*|комнат\w*|стен\w*|пол\b|двер\w*|озер\w*|вод\w*)\b", text_lower)
                if m_subj:
                    target = m_subj.group(0)

        return EditPlan(
            instruction=instr,
            target=target,
            action_type=action_type,
            what_to_change=what_to_change,
            what_to_keep=what_to_keep,
            denoise=denoise,
            positive_prompt_additions=pos_additions,
            negative_prompt_additions=neg_additions,
        )

    def _llm_parse(self, instr: str, base_p: str) -> Optional[EditPlan]:
        """
        Семантический анализ через LLM с гарантированной валидацией схемы JSON.
        """
        if not self.ai_client:
            return None

        prompt = (
            "You are an AI image editing planner. Analyze the user edit instruction and output ONLY a JSON object:\n"
            "Schema:\n"
            "{\n"
            '  "target": "object or scene part being modified",\n'
            '  "action_type": "proportions|pose|remove|add|replace|color|lighting|background|style|general",\n'
            '  "what_to_change": "concise description of requested change",\n'
            '  "what_to_keep": "concise description of what to preserve",\n'
            '  "denoise": 0.35 to 0.75,\n'
            '  "positive_tags": ["tag1", "tag2"],\n'
            '  "negative_tags": ["tag1", "tag2"]\n'
            "}\n\n"
            f"Base prompt: {base_p}\n"
            f"User instruction: {instr}\n"
            "JSON:"
        )

        try:
            resp_text = ""
            if hasattr(self.ai_client, "send_chat") and callable(self.ai_client.send_chat):
                res = self.ai_client.send_chat([{"role": "user", "content": prompt}], tools=None)
                if isinstance(res, dict):
                    resp_text = res.get("content", "")
                elif hasattr(res, "content"):
                    resp_text = str(res.content)
                else:
                    resp_text = str(res)
            elif hasattr(self.ai_client, "ask") and callable(self.ai_client.ask):
                resp_text = str(self.ai_client.ask(prompt))

            # Извлечение JSON из ответа
            m = re.search(r"\{.*\}", resp_text, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group(0))

            action_type = str(data.get("action_type", "general")).lower()
            if action_type not in (
                "proportions", "pose", "remove", "add", "replace",
                "color", "lighting", "background", "style", "general"
            ):
                action_type = "general"

            denoise = float(data.get("denoise", 0.60))
            denoise = max(0.2, min(0.85, denoise))

            pos_tags = [str(t) for t in data.get("positive_tags", []) if t]
            neg_tags = [str(t) for t in data.get("negative_tags", []) if t]

            return EditPlan(
                instruction=instr,
                target=str(data.get("target", "subject")),
                action_type=action_type,
                what_to_change=str(data.get("what_to_change", instr)),
                what_to_keep=str(data.get("what_to_keep", "scene context")),
                denoise=denoise,
                positive_prompt_additions=pos_tags,
                negative_prompt_additions=neg_tags,
            )
        except Exception as ex:
            logger.debug("EditPlanner LLM parsing fallback due to: %s", ex)
            return None

    def _compile_effective_prompts(self, plan: EditPlan, base_p: str) -> None:
        """
        Компилирует Positive и Negative промпты для KSampler ComfyUI.
        """
        instr = plan.instruction
        pos_add = ", ".join(plan.positive_prompt_additions)
        neg_add = ", ".join(plan.negative_prompt_additions)

        # Базовая склейка промпта
        if base_p:
            if pos_add:
                merged_pos = f"{base_p}, {pos_add}".strip(" ,")
            else:
                merged_pos = f"{base_p}, {instr}".strip(" ,")
        else:
            merged_pos = f"{instr}, {pos_add}".strip(" ,") if pos_add else instr

        # Компиляция через PromptCompiler для чистоты тегов
        compiled_pos, compiled_neg, _ = PromptCompiler.compile(
            raw_prompt=merged_pos,
            negative_prompt=BASE_NEGATIVE_PROMPT
        )

        if plan.positive_prompt_additions:
            for tag in plan.positive_prompt_additions:
                if tag.lower() not in compiled_pos.lower():
                    compiled_pos = f"{compiled_pos}, {tag}".strip(" ,")

        if plan.negative_prompt_additions:
            for tag in plan.negative_prompt_additions:
                if tag.lower() not in compiled_neg.lower():
                    compiled_neg = f"{compiled_neg}, {tag}".strip(" ,")

        plan.compiled_prompt = compiled_pos
        plan.compiled_negative = compiled_neg
