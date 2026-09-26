"""
Модуль специализированного Sub-Agent'а создания документов (DocumentAgent).

Обеспечивает:
- генерацию валидных текстовых документов в формате Microsoft Word (.docx, Office OpenXML);
- работу на чистой стандартной библиотеке Python (без сторонних зависимостей);
- поддержку структуры: титульный заголовок, подзаголовок, разделы, абзацы и маркированные списки;
- интеллектуальный разбор темы и структуры из текста задачи и метаданных;
- сохранение файлов в стандартной директории data/generated/documents/;
- возврат стандартизированного AgentResult с Artifact типа document;
- надежную обработку исключений и валидацию входного контекста.
"""

import io
import os
import re
import time
import uuid
import xml.sax.saxutils as saxutils
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType

DEFAULT_OUTPUT_DIR = Path("data/generated/documents")


def _xml_escape(text: Any) -> str:
    """Безопасное экранирование строк для вставки в OpenXML."""
    if text is None:
        return ""
    s = str(text)
    return saxutils.escape(s, {'"': "&quot;", "'": "&apos;"})


class DocumentAgent(SubAgent):
    """
    Специализированный Sub-Agent для генерации документов в формате .docx.
    """

    name: str = "document"
    description: str = "Специализированный sub-agent создания документов (.docx)."
    capabilities: List[str] = ["document", "docx", "word", "text", "report"]

    def __init__(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        enabled: bool = True
    ):
        super().__init__(
            name=self.name,
            description=self.description,
            capabilities=self.capabilities,
            enabled=enabled
        )
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR

    # =========================================================================
    # Разбор задачи и структуры документа
    # =========================================================================

    def parse_task(
        self,
        task: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
        """
        Извлекает заголовок, подзаголовок и разделы из текста задачи и метаданных.

        Возвращает кортеж (title, subtitle, sections), где sections - список словарей:
        [{"heading": str, "paragraphs": List[str], "bullets": List[str]}, ...]
        """
        meta = metadata or {}

        meta_title = meta.get("title")
        meta_subtitle = meta.get("subtitle")
        raw_sections = meta.get("sections")

        # 1. Если разделы переданы в метаданных в структурированном виде
        if raw_sections and isinstance(raw_sections, list):
            parsed_sections: List[Dict[str, Any]] = []
            for item in raw_sections:
                if isinstance(item, dict):
                    h = item.get("heading") or item.get("title") or "Раздел"
                    raw_p = item.get("paragraphs") or item.get("content") or []
                    if isinstance(raw_p, str):
                        raw_p = [raw_p]
                    raw_b = item.get("bullets") or item.get("items") or []
                    if isinstance(raw_b, str):
                        raw_b = [raw_b]

                    parsed_sections.append({
                        "heading": str(h),
                        "paragraphs": [str(p) for p in raw_p],
                        "bullets": [str(b) for b in raw_b]
                    })
                elif isinstance(item, str):
                    parsed_sections.append({
                        "heading": item,
                        "paragraphs": [],
                        "bullets": []
                    })
            title = str(meta_title or (self._clean_title_prompt(task) or "Документ"))
            subtitle = meta_subtitle or "Подготовлено Акакием"
            return title, subtitle, parsed_sections

        # 2. Если разделы не переданы, извлекаем тему из задачи
        clean_prompt = self._clean_title_prompt(task)
        title = meta_title or clean_prompt or "Документ"
        subtitle = meta_subtitle or "Подготовлено персональным ассистентом Акакий"

        # Проверяем, содержит ли task структурированный многострочный текст
        lines = [line.strip() for line in task.splitlines() if line.strip()]
        sections_from_text: List[Dict[str, Any]] = []
        current_section: Optional[Dict[str, Any]] = None

        heading_pattern = re.compile(
            r"^(?:раздел\s*\d*[:\-.]*|глава\s*\d*[:\-.]*|параграф\s*\d*[:\-.]*|#+\s+)(.*)$",
            re.IGNORECASE
        )

        for line in lines:
            m = heading_pattern.match(line)
            if m:
                h_text = m.group(1).strip() or f"Раздел {len(sections_from_text) + 1}"
                current_section = {"heading": h_text, "paragraphs": [], "bullets": []}
                sections_from_text.append(current_section)
            elif current_section is not None:
                # Маркер списка
                if re.match(r"^[-*•]\s+", line):
                    b_text = re.sub(r"^[-*•]\s+", "", line).strip()
                    if b_text:
                        current_section["bullets"].append(b_text)
                else:
                    current_section["paragraphs"].append(line)

        if len(sections_from_text) >= 2:
            return title, subtitle, sections_from_text

        # 3. Дефолтная логическая структура для кратких запросов темы
        default_sections = [
            {
                "heading": "1. Введение и назначение",
                "paragraphs": [
                    f"Настоящий документ содержит систематизированное описание и ключевые требования по теме: {title}."
                ],
                "bullets": [
                    "Обзор контекста разработки и предпосылок",
                    "Целевая аудитория и область применения решения",
                    "Ожидаемые результаты и критерии успешности"
                ]
            },
            {
                "heading": "2. Архитектура и состав компонентов",
                "paragraphs": [
                    "В данном разделе описывается компонентная модель, принципы модульности и протоколы взаимодействия составных частей системы."
                ],
                "bullets": [
                    "Изоляция функциональных обязанностей модулей",
                    "Унифицированные контракты передачи данных и результатов",
                    "Интеграция с локальной инфраструктурой и сервисами"
                ]
            },
            {
                "heading": "3. Требования к надёжности и ресурсам",
                "paragraphs": [
                    "Реализация механизмов отказоустойчивости, валидации входных данных и оптимизации используемых ресурсов."
                ],
                "bullets": [
                    "Контроль жизненного цикла задач и состояний выполнения",
                    "Автономное функционирование без сторонних зависимостей",
                    "Защита от сбоев и корректная обработка граничных условий"
                ]
            },
            {
                "heading": "4. Заключение и выводы",
                "paragraphs": [
                    f"Рассмотренные подходы обеспечивают высокую стабильность, воспроизводимость и безопасность реализации задачи '{title}'."
                ],
                "bullets": [
                    "Итоги рассмотрения ключевых аспектов",
                    "Рекомендации по дальнейшему внедрению и масштабированию"
                ]
            }
        ]

        return title, subtitle, default_sections

    def _clean_title_prompt(self, task: str) -> str:
        """Очищает тему документа от служебных префиксов."""
        text = task.strip()
        first_line = text.splitlines()[0].strip()

        pattern = re.compile(
            r"^(?:создай|создайте|создать|сделай|сделайте|сделать|сгенерируй|сгенерируйте|сгенерировать|подготовь|подготовьте|подготовить|напиши|напишите|написать)?(?:\s+мне)?\s*(?:документ\w*|отчет\w*|файл\w*)(?:\s*(?:на\s+тему|про|по|о|об))?(?:\s*:\s*|[,\s]+)",
            re.IGNORECASE
        )
        cleaned = pattern.sub("", first_line).strip()
        if not cleaned:
            cleaned = first_line
        cleaned = cleaned.strip("\"'«»“”")
        return cleaned

    # =========================================================================
    # Построение OpenXML DOCX файла
    # =========================================================================

    def build_document(
        self,
        title: str,
        sections: List[Dict[str, Any]],
        subtitle: Optional[str] = None
    ) -> bytes:
        """
        Создаёт валидный файл .docx (Office OpenXML) в памяти и возвращает байты.
        """
        buf = io.BytesIO()

        # 1. [Content_Types].xml
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>"""

        # 2. _rels/.rels
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

        # 3. word/_rels/document.xml.rels
        doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>"""

        # 4. word/settings.xml
        settings_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:zoom w:percent="100"/>
</w:settings>"""

        # 5. word/styles.xml
        styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
        <w:sz w:val="22"/>
        <w:color w:val="334155"/>
        <w:lang w:val="ru-RU"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:rPr>
      <w:b/>
      <w:sz w:val="52"/>
      <w:color w:val="0F172A"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle">
    <w:name w:val="Subtitle"/>
    <w:rPr>
      <w:i/>
      <w:sz w:val="24"/>
      <w:color w:val="64748B"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:rPr>
      <w:b/>
      <w:sz w:val="34"/>
      <w:color w:val="1E293B"/>
    </w:rPr>
  </w:style>
</w:styles>"""

        # 6. word/document.xml - формирование тела документа
        body_xml = []

        # Заголовок документа (Title)
        esc_title = _xml_escape(title)
        body_xml.append(f"""    <w:p>
      <w:pPr>
        <w:pStyle w:val="Title"/>
        <w:spacing w:before="0" w:after="160"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:b/><w:sz w:val="52"/><w:color w:val="0F172A"/></w:rPr>
        <w:t>{esc_title}</w:t>
      </w:r>
    </w:p>""")

        # Подзаголовок документа (Subtitle / Дата / Автор)
        if subtitle:
            esc_sub = _xml_escape(subtitle)
            body_xml.append(f"""    <w:p>
      <w:pPr>
        <w:pStyle w:val="Subtitle"/>
        <w:spacing w:before="0" w:after="360"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:i/><w:sz w:val="24"/><w:color w:val="64748B"/></w:rPr>
        <w:t>{esc_sub}</w:t>
      </w:r>
    </w:p>""")

        # Разделы документа
        for sec in sections:
            h_text = _xml_escape(sec.get("heading", "Раздел"))
            body_xml.append(f"""    <w:p>
      <w:pPr>
        <w:pStyle w:val="Heading1"/>
        <w:spacing w:before="300" w:after="140"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:b/><w:sz w:val="34"/><w:color w:val="1E293B"/></w:rPr>
        <w:t>{h_text}</w:t>
      </w:r>
    </w:p>""")

            # Обычные абзацы раздела
            for p in sec.get("paragraphs", []):
                esc_p = _xml_escape(p)
                body_xml.append(f"""    <w:p>
      <w:pPr>
        <w:spacing w:before="0" w:after="140" w:line="276" w:lineRule="auto"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:sz w:val="22"/><w:color w:val="334155"/></w:rPr>
        <w:t>{esc_p}</w:t>
      </w:r>
    </w:p>""")

            # Элементы маркированного списка
            for b in sec.get("bullets", []):
                esc_b = _xml_escape(b)
                body_xml.append(f"""    <w:p>
      <w:pPr>
        <w:ind w:left="420" w:hanging="260"/>
        <w:spacing w:before="0" w:after="80"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:color w:val="2563EB"/><w:b/><w:sz w:val="22"/></w:rPr>
        <w:t>• </w:t>
      </w:r>
      <w:r>
        <w:rPr><w:sz w:val="22"/><w:color w:val="334155"/></w:rPr>
        <w:t>{esc_b}</w:t>
      </w:r>
    </w:p>""")

        # Параметры страницы: A4 (11906 x 16838 dxa), поля по 1 дюйму (1440 dxa)
        body_xml.append("""    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>""")

        document_content = "\n".join(body_xml)
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
{document_content}
  </w:body>
</w:document>"""

        # Упаковка в ZIP-архив .docx
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", root_rels)
            zf.writestr("word/_rels/document.xml.rels", doc_rels)
            zf.writestr("word/settings.xml", settings_xml)
            zf.writestr("word/styles.xml", styles_xml)
            zf.writestr("word/document.xml", document_xml)

        return buf.getvalue()

    # =========================================================================
    # Сохранение на диск
    # =========================================================================

    def _generate_safe_filename(self, title: Optional[str] = None) -> str:
        """Формирует безопасное уникальное имя файла документа."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]

        prefix = "doc"
        if title:
            sanitized = re.sub(r"[^\w\-]+", "_", title.strip().lower())[:30].strip("_")
            if sanitized:
                prefix = f"doc_{sanitized}"

        return f"{prefix}_{timestamp}_{uid}.docx"

    def save_document(
        self,
        data: bytes,
        filename: Optional[str] = None,
        title: Optional[str] = None
    ) -> Path:
        """
        Сохраняет байты документа на диск в директорию self.output_dir.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or self._generate_safe_filename(title)
        if not fname.lower().endswith(".docx"):
            fname += ".docx"

        target_path = (self.output_dir / fname).resolve()
        with open(target_path, "wb") as f:
            f.write(data)
        return target_path

    # =========================================================================
    # Основной контракт выполнения SubAgent.run()
    # =========================================================================

    def run(self, context: AgentContext) -> AgentResult:
        """
        Основной метод генерации документа по переданному контексту.
        """
        # 1. Валидация входного контекста
        if not self.validate_context(context):
            return AgentResult.fail(
                error="Некорректный контекст: ожидается экземпляр AgentContext."
            )

        if not self.enabled:
            return AgentResult.fail(
                error=f"Sub-agent '{self.name}' отключен."
            )

        task_str = str(context.task or "").strip()
        if not task_str and not context.get("title") and not context.get("sections"):
            return AgentResult.fail(
                error="Не указана тема или содержание для создания документа.",
                message="Необходимо указать тему или содержание документа."
            )

        try:
            # 2. Разбор структуры документа
            title, subtitle, sections = self.parse_task(task_str, context.metadata)

            # 3. Построение байтов DOCX
            docx_bytes = self.build_document(
                title=title,
                sections=sections,
                subtitle=subtitle
            )

            # 4. Сохранение файла на диск
            custom_filename = context.get("filename")
            saved_path = self.save_document(
                data=docx_bytes,
                filename=custom_filename,
                title=title
            )

            # 5. Создание артефакта
            artifact = Artifact.from_document(
                path=str(saved_path),
                name=saved_path.name,
                title=title,
                sections_count=len(sections),
                file_size_bytes=len(docx_bytes)
            )

            msg = f"Документ успешно создан: {saved_path.name} ({len(sections)} разделов)"

            res_data = {
                "title": title,
                "subtitle": subtitle,
                "sections_count": len(sections),
                "saved_to": str(saved_path),
                "file_size_bytes": len(docx_bytes)
            }

            return AgentResult.ok(
                message=msg,
                created_files=[str(saved_path)],
                artifacts=[artifact],
                data=res_data
            )

        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка генерации документа: {ex}",
                message=f"Не удалось создать документ: {ex}"
            )
