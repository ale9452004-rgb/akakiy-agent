"""
Модуль специализированного Sub-Agent'а создания презентаций (PresentationAgent).

Обеспечивает:
- генерацию валидных файлов презентаций .pptx по спецификации Office OpenXML;
- работу на чистой стандартной библиотеке Python (без сторонних зависимостей);
- поддержку структуры: титульный слайд, слайды содержания, текстовые блоки (bullet points);
- интеллектуальный разбор темы и структуры из текста задачи и метаданных;
- сохранение файлов в стандартной директории data/generated/presentations/;
- возврат стандартизированного AgentResult с Artifact типа presentation;
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

DEFAULT_OUTPUT_DIR = Path("data/generated/presentations")


def _xml_escape(text: Any) -> str:
    """Безопасное экранирование строк для вставки в OpenXML."""
    if text is None:
        return ""
    s = str(text)
    return saxutils.escape(s, {'"': "&quot;", "'": "&apos;"})


class PresentationAgent(SubAgent):
    """
    Специализированный Sub-Agent для генерации презентаций в формате .pptx.
    """

    name: str = "presentation"
    description: str = "Специализированный sub-agent создания презентаций (.pptx)."
    capabilities: List[str] = ["presentation", "pptx", "slides", "document"]

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
    # Разбор задачи и структуры презентации
    # =========================================================================

    def parse_task(
        self,
        task: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
        """
        Извлекает заголовок, подзаголовок и слайды из текста задачи и метаданных.

        Возвращает кортеж (title, subtitle, slides), где slides - список словарей:
        [{"title": str, "blocks": List[str]}, ...]
        """
        meta = metadata or {}

        # 1. Если слайды явно заданы в метаданных в структурированном виде
        raw_slides = meta.get("slides")
        meta_title = meta.get("title")
        meta_subtitle = meta.get("subtitle")

        if raw_slides and isinstance(raw_slides, list):
            parsed_slides: List[Dict[str, Any]] = []
            for item in raw_slides:
                if isinstance(item, dict):
                    s_title = item.get("title", "Слайд")
                    s_blocks = item.get("blocks") or item.get("content") or []
                    if isinstance(s_blocks, str):
                        s_blocks = [s_blocks]
                    parsed_slides.append({
                        "title": str(s_title),
                        "blocks": [str(b) for b in s_blocks]
                    })
                elif isinstance(item, str):
                    parsed_slides.append({
                        "title": item,
                        "blocks": []
                    })
            title = str(meta_title or (self._clean_title_prompt(task) or "Презентация"))
            subtitle = meta_subtitle or "Подготовлено Акакием"
            return title, subtitle, parsed_slides

        # 2. Если слайды не переданы в структурированном виде, извлекаем тему из задачи
        clean_prompt = self._clean_title_prompt(task)
        title = meta_title or clean_prompt or "Презентация"
        subtitle = meta_subtitle or "Подготовлено персональным ассистентом Акакий"

        # Проверяем, содержит ли task форматированный многострочный план
        lines = [line.strip() for line in task.splitlines() if line.strip()]
        slides_from_text: List[Dict[str, Any]] = []
        current_slide: Optional[Dict[str, Any]] = None

        slide_header_pattern = re.compile(
            r"^(?:слайд\s*\d*[:\-.]*|раздел\s*\d*[:\-.]*|#+\s+)(.*)$",
            re.IGNORECASE
        )

        for line in lines:
            m = slide_header_pattern.match(line)
            if m:
                s_title = m.group(1).strip() or f"Слайд {len(slides_from_text) + 1}"
                current_slide = {"title": s_title, "blocks": []}
                slides_from_text.append(current_slide)
            elif current_slide is not None:
                # Маркеры списков
                cleaned_line = re.sub(r"^[-*•\d.]+\s*", "", line).strip()
                if cleaned_line:
                    current_slide["blocks"].append(cleaned_line)

        if len(slides_from_text) >= 2:
            return title, subtitle, slides_from_text

        # 3. Дефолтная логическая структура для кратких запросов темы
        default_slides = [
            {
                "title": "Введение и ключевые цели",
                "blocks": [
                    f"Обзор предметной области: {title}",
                    "Ключевые предпосылки и актуальность темы",
                    "Целевые показатели и ожидаемые результаты"
                ]
            },
            {
                "title": "Основные компоненты и принципы",
                "blocks": [
                    "Базовая архитектура и ключевые модули",
                    "Механизмы взаимодействия и протоколы данных",
                    "Надёжность, масштабируемость и безопасность"
                ]
            },
            {
                "title": "Практическое применение",
                "blocks": [
                    "Типовые сценарии использования и рабочие процессы",
                    "Интеграция с существующей инфраструктурой",
                    "Оптимизация производительности и ресурсов"
                ]
            },
            {
                "title": "Заключение и выводы",
                "blocks": [
                    "Итоги рассмотрения ключевых аспектов",
                    "Дальнейшие шаги и рекомендации по развитию"
                ]
            }
        ]

        return title, subtitle, default_slides

    def _clean_title_prompt(self, task: str) -> str:
        """Очищает тему от префиксов команд генерации презентации."""
        text = task.strip()
        # Удаляем многострочный хвост, если есть
        first_line = text.splitlines()[0].strip()

        pattern = re.compile(
            r"^(?:создай|создайте|создать|сделай|сделайте|сделать|сгенерируй|сгенерируйте|сгенерировать|подготовь|подготовьте|подготовить)?(?:\s+мне)?\s*(?:презентаци\w*|слайд\w*)(?:\s*(?:на\s+тему|про|по|о|об))?(?:\s*:\s*|[,\s]+)",
            re.IGNORECASE
        )
        cleaned = pattern.sub("", first_line).strip()
        if not cleaned:
            cleaned = first_line
        # Убираем кавычки
        cleaned = cleaned.strip("\"'«»“”")
        return cleaned

    # =========================================================================
    # Построение OpenXML PPTX файла
    # =========================================================================

    def build_presentation(
        self,
        title: str,
        slides: List[Dict[str, Any]],
        subtitle: Optional[str] = None
    ) -> bytes:
        """
        Создаёт валидный файл .pptx (Office OpenXML) в памяти и возвращает байты.
        """
        buf = io.BytesIO()

        # Полный список слайдов: Слайд 1 (Титульный) + Слайды содержания
        all_slides: List[Dict[str, Any]] = [
            {
                "is_title_slide": True,
                "title": title,
                "subtitle": subtitle or "Подготовлено Акакием"
            }
        ]
        for s in slides:
            all_slides.append({
                "is_title_slide": False,
                "title": s.get("title", "Слайд"),
                "blocks": s.get("blocks", [])
            })

        total_slides = len(all_slides)

        # 1. [Content_Types].xml
        slide_overrides = "".join(
            f'<Override PartName="/ppt/slides/slide{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(total_slides)
        )
        content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  {slide_overrides}
</Types>"""

        # 2. _rels/.rels
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

        # 3. ppt/presentation.xml (Widescreen 16:9 = 12192000 x 6858000 EMU)
        sld_id_lst = "".join(
            f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>'
            for i in range(total_slides)
        )
        presentation_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    {sld_id_lst}
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""

        # 4. ppt/_rels/presentation.xml.rels
        slide_rels = "".join(
            f'<Relationship Id="rId{i + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i + 1}.xml"/>'
            for i in range(total_slides)
        )
        presentation_rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  {slide_rels}
</Relationships>"""

        # 5. ppt/slideMasters/slideMaster1.xml
        slide_master = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
    <p:sldLayoutId id="2147483650" r:id="rId2"/>
  </p:sldLayoutIdLst>
  <p:txStyles>
    <p:titleStyle/>
    <p:bodyStyle/>
    <p:otherStyle/>
  </p:txStyles>
</p:sldMaster>"""

        # 6. ppt/slideMasters/_rels/slideMaster1.xml.rels
        slide_master_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

        # 7. ppt/slideLayouts/slideLayout1.xml (Title Slide Layout)
        slide_layout1 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="title">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMap/></p:clrMapOvr>
</p:sldLayout>"""

        slide_layout1_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

        # 8. ppt/slideLayouts/slideLayout2.xml (Content Slide Layout)
        slide_layout2 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="obj">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMap/></p:clrMapOvr>
</p:sldLayout>"""

        slide_layout2_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

        # 9. ppt/theme/theme1.xml
        theme_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Akakiy Modern Slate Theme">
  <a:themeElements>
    <a:clrScheme name="ModernSlate">
      <a:dk1><a:srgbClr val="0F172A"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1E293B"/></a:dk2>
      <a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
      <a:accent1><a:srgbClr val="2563EB"/></a:accent1>
      <a:accent2><a:srgbClr val="0284C7"/></a:accent2>
      <a:accent3><a:srgbClr val="0D9488"/></a:accent3>
      <a:accent4><a:srgbClr val="E11D48"/></a:accent4>
      <a:accent5><a:srgbClr val="F59E0B"/></a:accent5>
      <a:accent6><a:srgbClr val="8B5CF6"/></a:accent6>
      <a:hlink><a:srgbClr val="2563EB"/></a:hlink>
      <a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="ModernFonts">
      <a:majorFont><a:latin typeface="Calibri"/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="ModernFormat">
      <a:fillStyleLst><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:fillStyleLst>
      <a:lnStyleLst><a:ln w="9525"><a:solidFill><a:srgbClr val="E2E8F0"/></a:solidFill></a:ln></a:lnStyleLst>
      <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
      <a:bgFillStyleLst><a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill></a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""

        # 10. Генерация файлов слайдов
        slide_files: Dict[str, str] = {}
        slide_rel_files: Dict[str, str] = {}

        for idx, sdata in enumerate(all_slides, start=1):
            is_title = sdata.get("is_title_slide", False)
            stitle = _xml_escape(sdata.get("title", f"Слайд {idx}"))

            if is_title:
                # Титульный слайд (акцентный заголовок по центру + подзаголовок)
                ssub = _xml_escape(sdata.get("subtitle", "Подготовлено Акакием"))
                slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      <!-- Декоративная акцентная плашка -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="AccentLine"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1000000" y="1600000"/><a:ext cx="1200000" cy="60000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:solidFill><a:srgbClr val="2563EB"/></a:solidFill>
        </p:spPr>
      </p:sp>
      <!-- Заголовок презентации -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Title"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="ctrTitle"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1000000" y="1900000"/><a:ext cx="10192000" cy="2000000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="t"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="ru-RU" sz="4400" b="1">
                <a:solidFill><a:srgbClr val="0F172A"/></a:solidFill>
              </a:rPr>
              <a:t>{stitle}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <!-- Подзаголовок презентации -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="4" name="Subtitle"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="subTitle" idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1000000" y="4100000"/><a:ext cx="10192000" cy="1200000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="t"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="ru-RU" sz="2200">
                <a:solidFill><a:srgbClr val="64748B"/></a:solidFill>
              </a:rPr>
              <a:t>{ssub}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMap/></p:clrMapOvr>
</p:sld>"""
                target_layout = "../slideLayouts/slideLayout1.xml"

            else:
                # Слайд с контентом (заголовок + список блоков)
                blocks = sdata.get("blocks", [])
                body_paragraphs = ""
                for b in blocks:
                    eb = _xml_escape(b)
                    body_paragraphs += f"""
          <a:p>
            <a:pPr marL="360000" indent="-288000">
              <a:buChar char="•"/>
            </a:pPr>
            <a:r>
              <a:rPr lang="ru-RU" sz="2000">
                <a:solidFill><a:srgbClr val="334155"/></a:solidFill>
              </a:rPr>
              <a:t>{eb}</a:t>
            </a:r>
          </a:p>"""

                slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      <!-- Заголовок слайда -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="title"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="838200" y="550000"/><a:ext cx="10515600" cy="1100000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="t"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="ru-RU" sz="3200" b="1">
                <a:solidFill><a:srgbClr val="0F172A"/></a:solidFill>
              </a:rPr>
              <a:t>{stitle}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <!-- Содержимое слайда -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Content Placeholder"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="838200" y="1800000"/><a:ext cx="10515600" cy="4400000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="t"/>
          <a:lstStyle/>
          {body_paragraphs}
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMap/></p:clrMapOvr>
</p:sld>"""
                target_layout = "../slideLayouts/slideLayout2.xml"

            slide_rel = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="{target_layout}"/>
</Relationships>"""

            slide_files[f"ppt/slides/slide{idx}.xml"] = slide_xml
            slide_rel_files[f"ppt/slides/_rels/slide{idx}.xml.rels"] = slide_rel

        # Упаковка в ZIP-архив .pptx
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", root_rels)
            zf.writestr("ppt/presentation.xml", presentation_xml)
            zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
            zf.writestr("ppt/slideMasters/slideMaster1.xml", slide_master)
            zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", slide_master_rels)
            zf.writestr("ppt/slideLayouts/slideLayout1.xml", slide_layout1)
            zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", slide_layout1_rels)
            zf.writestr("ppt/slideLayouts/slideLayout2.xml", slide_layout2)
            zf.writestr("ppt/slideLayouts/_rels/slideLayout2.xml.rels", slide_layout2_rels)
            zf.writestr("ppt/theme/theme1.xml", theme_xml)

            for spath, scontent in slide_files.items():
                zf.writestr(spath, scontent)
            for rpath, rcontent in slide_rel_files.items():
                zf.writestr(rpath, rcontent)

        return buf.getvalue()

    # =========================================================================
    # Сохранение на диск
    # =========================================================================

    def _generate_safe_filename(self, title: Optional[str] = None) -> str:
        """Формирует безопасное уникальное имя файла презентации."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]

        prefix = "pres"
        if title:
            # Преобразуем кириллицу/символы в безопасный суффикс
            sanitized = re.sub(r"[^\w\-]+", "_", title.strip().lower())[:30].strip("_")
            if sanitized:
                prefix = f"pres_{sanitized}"

        return f"{prefix}_{timestamp}_{uid}.pptx"

    def save_presentation(
        self,
        data: bytes,
        filename: Optional[str] = None,
        title: Optional[str] = None
    ) -> Path:
        """
        Сохраняет байты презентации на диск в директорию self.output_dir.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or self._generate_safe_filename(title)
        if not fname.lower().endswith(".pptx"):
            fname += ".pptx"

        target_path = (self.output_dir / fname).resolve()
        with open(target_path, "wb") as f:
            f.write(data)
        return target_path

    # =========================================================================
    # Основной контракт выполнения SubAgent.run()
    # =========================================================================

    def run(self, context: AgentContext) -> AgentResult:
        """
        Основной метод генерации презентации по переданному контексту.
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
        if not task_str and not context.get("title") and not context.get("slides"):
            return AgentResult.fail(
                error="Не указана тема или содержание для создания презентации.",
                message="Необходимо указать тему или содержание презентации."
            )

        try:
            # 2. Разбор структуры презентации
            title, subtitle, slides = self.parse_task(task_str, context.metadata)

            # 3. Построение байтов PPTX
            pptx_bytes = self.build_presentation(
                title=title,
                slides=slides,
                subtitle=subtitle
            )

            # 4. Сохранение файла на диск
            custom_filename = context.get("filename")
            saved_path = self.save_presentation(
                data=pptx_bytes,
                filename=custom_filename,
                title=title
            )

            # 5. Создание артефакта
            total_slides_count = len(slides) + 1  # титульный + слайды содержания
            artifact = Artifact.from_presentation(
                path=str(saved_path),
                name=saved_path.name,
                title=title,
                slides_count=total_slides_count,
                file_size_bytes=len(pptx_bytes)
            )

            msg = f"Презентация успешно создана: {saved_path.name} ({total_slides_count} слайдов)"

            res_data = {
                "title": title,
                "subtitle": subtitle,
                "slides_count": total_slides_count,
                "saved_to": str(saved_path),
                "file_size_bytes": len(pptx_bytes)
            }

            return AgentResult.ok(
                message=msg,
                created_files=[str(saved_path)],
                artifacts=[artifact],
                data=res_data
            )

        except Exception as ex:
            return AgentResult.fail(
                error=f"Ошибка генерации презентации: {ex}",
                message=f"Не удалось создать презентацию: {ex}"
            )
