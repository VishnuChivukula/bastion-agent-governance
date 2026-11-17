"""Export the requirements documents to Word and PDF (`make requirements-docs`).

For each Markdown document in docs/requirements/ this writes, into docs/requirements/exports/:

- a `.docx` (python-docx): title page, table of contents (a real TOC field), Word heading
  styles, real tables, diagrams as images, the document name in the header and
  `Page X of Y` in the footer (PAGE and NUMPAGES fields);
- a `.pdf` through the same Chromium path as the design pack (title page, contents with page
  numbers, the same header and footer).

Mermaid diagrams are rendered in a headless browser, which needs network access to load the
pinned Mermaid script.
"""

import io
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

from bastion import DISCLAIMER, __version__

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "requirements"
EXPORTS = SOURCE / "exports"
DOCUMENTS = ["FRD-AI-Native", "FRD-Enterprise", "Bastion-Requirements-Brief"]
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
ACCENT = RGBColor(0x1F, 0x4E, 0x8C)
BODY_WIDTH_CM = 17.0


# --- Markdown helpers ----------------------------------------------------------------------------
def strip_frame(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("**Bastion Kit ·"):
        lines = lines[1:]
    if lines and re.fullmatch(r"\*.+· Page 1 of 1\*", lines[-1].strip()):
        lines = lines[:-1]
        while lines and lines[-1].strip() in ("", "---"):
            lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def render_diagrams(sources: list[str]) -> list[bytes]:
    """PNG for each Mermaid source, in order."""
    if not sources:
        return []
    images = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
        page.set_content(
            f'<body style="margin:0;background:#fff"><div id="out"></div>'
            f'<script src="{MERMAID}"></script></body>',
            wait_until="networkidle",
        )
        page.evaluate(
            "mermaid.initialize({startOnLoad:false, theme:'neutral', securityLevel:'strict',"
            " flowchart:{htmlLabels:false}})"
        )
        for index, source in enumerate(sources):
            error = page.evaluate(
                """async ([id, source]) => {
                    try {
                        const { svg } = await mermaid.render(id, source);
                        const out = document.getElementById('out');
                        out.innerHTML = svg;
                        out.style.display = 'inline-block';
                        out.style.padding = '8px';
                        return null;
                    } catch (e) { return String(e.message || e); }
                }""",
                [f"d{index}", source],
            )
            if error:
                raise RuntimeError(f"Mermaid diagram {index + 1} did not render: {error[:300]}")
            images.append(page.locator("#out").screenshot())
        browser.close()
    return images


# --- Word plumbing -------------------------------------------------------------------------------
def field(paragraph, instruction: str, placeholder: str = "1"):
    """Insert a simple Word field (PAGE, NUMPAGES) into a paragraph."""
    for kind in ("begin", None, "separate", "text", "end"):
        run = paragraph.add_run()
        if kind == "text":
            run.text = placeholder
            continue
        if kind is None:
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = f" {instruction} "
        else:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
        run._r.append(node)
    return paragraph


def shade(cell, colour: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), colour)
    properties.append(shading)


def repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    properties.append(node)


def hyperlink(paragraph, text: str, url: str, size: Pt | None) -> None:
    rel = paragraph.part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )  # fmt: skip
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    colour = OxmlElement("w:color")
    colour.set(qn("w:val"), "1F4E8C")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(colour)
    props.append(underline)
    if size is not None:
        for tag in ("w:sz", "w:szCs"):
            node = OxmlElement(tag)
            node.set(qn("w:val"), str(int(size.pt * 2)))
            props.append(node)
    run.append(props)
    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    run.append(node)
    link.append(run)
    paragraph._p.append(link)


def absolute(target: str, base: str) -> str | None:
    if target.startswith(("http://", "https://", "mailto:")):
        return target
    if target.startswith("#"):
        return None
    parts: list[str] = []
    for part in f"{base}/{target.split('#')[0]}".split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "https://github.com/VishnuChivukula/bastion-agent-governance/blob/main/" + "/".join(
        parts
    )


def inline(paragraph, token, size: Pt | None = None, bold: bool = False) -> None:
    """Write a markdown-it inline token (text, bold, italic, code, links) into a paragraph."""
    strong = emphasis = 0
    link: str | None = None
    for child in token.children or []:
        kind = child.type
        if kind == "strong_open":
            strong += 1
        elif kind == "strong_close":
            strong -= 1
        elif kind == "em_open":
            emphasis += 1
        elif kind == "em_close":
            emphasis -= 1
        elif kind == "link_open":
            link = absolute(child.attrGet("href") or "", "docs/requirements")
        elif kind == "link_close":
            link = None
        elif kind in ("text", "code_inline", "softbreak", "hardbreak"):
            text = " " if kind == "softbreak" else "\n" if kind == "hardbreak" else child.content
            if link and kind == "text":
                hyperlink(paragraph, text, link, size)
                continue
            run = paragraph.add_run(text)
            run.bold = bool(strong) or bold
            run.italic = bool(emphasis)
            if kind == "code_inline":
                run.font.name = "Consolas"
                run.font.size = Pt((size.pt if size else 10) - 1)
            elif size is not None:
                run.font.size = size


def ensure_styles(doc) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    for level, size in ((1, 16), (2, 13), (3, 11), (4, 10)):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = ACCENT
    for level in (1, 2):  # the styles Word uses for a table of contents
        name = f"TOC {level}"
        if name not in [s.name for s in doc.styles]:
            style = doc.styles.add_style(name, 1)
            style.base_style = normal
            style.paragraph_format.left_indent = Cm(0.6 * (level - 1))
            style.paragraph_format.space_after = Pt(2)
            style.font.bold = level == 1


def header_footer(section, name: str) -> None:
    header = section.header.paragraphs[0]
    header.text = name
    header.runs[0].font.size = Pt(8)
    header.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run(f"{DISCLAIMER}    Page ")
    field(footer, "PAGE")
    footer.add_run(" of ")
    field(footer, "NUMPAGES")
    for run in footer.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)


def contents(doc, headings: list[tuple[int, str]]) -> None:
    """A real TOC field. Its cached result lists the headings so the page is useful before
    Word recalculates the page numbers (it does so when the document is opened)."""
    doc.add_heading("Contents", level=1)
    entries = [(level, text) for level, text in headings if level <= 2] or [(1, "")]
    for index, (level, text) in enumerate(entries):
        paragraph = doc.add_paragraph(style=f"TOC {level}")
        if index == 0:
            for kind in ("begin", None, "separate"):
                run = paragraph.add_run()
                if kind is None:
                    node = OxmlElement("w:instrText")
                    node.set(qn("xml:space"), "preserve")
                    node.text = ' TOC \\o "1-2" \\h \\z \\u '
                else:
                    node = OxmlElement("w:fldChar")
                    node.set(qn("w:fldCharType"), kind)
                    if kind == "begin":
                        node.set(qn("w:dirty"), "true")
                run._r.append(node)
        paragraph.add_run(text)
        if index == len(entries) - 1:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), "end")
            paragraph.add_run()._r.append(node)
    settings = doc.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


def add_table(doc, rows: list[list], header: bool) -> None:
    columns = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    size = Pt(8 if columns >= 5 else 9)
    for r, row in enumerate(rows):
        for c in range(columns):
            cell = table.cell(r, c)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(1)
            if c < len(row):
                inline(paragraph, row[c], size=size, bold=header and r == 0)
            if header and r == 0:
                shade(cell, "E8EDF5")
        if header and r == 0:
            repeat_header(table.rows[0])
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build_docx(source: Path, out: Path) -> tuple[str, int]:
    md = MarkdownIt("commonmark").enable("table")
    tokens = md.parse(strip_frame(source.read_text(encoding="utf-8")))
    title = next(
        (tokens[i + 1].content for i, t in enumerate(tokens) if t.type == "heading_open"), out.stem
    )
    diagrams = iter(
        render_diagrams([t.content for t in tokens if t.type == "fence" and t.info == "mermaid"])
    )
    headings = [
        (int(t.tag[1]) - 1, re.sub(r"[`*]", "", tokens[i + 1].content))
        for i, t in enumerate(tokens)
        if t.type == "heading_open" and t.tag in ("h2", "h3")
    ]

    doc = Document()
    ensure_styles(doc)
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(2.0))
    section.top_margin, section.bottom_margin = Cm(2.2), Cm(2.0)
    section.different_first_page_header_footer = True  # no header or footer on the title page
    header_footer(section, title)

    # Title page
    for _ in range(7):
        doc.add_paragraph()
    heading = doc.add_paragraph()
    run = heading.add_run(title)
    run.font.size, run.font.bold, run.font.color.rgb = Pt(30), True, ACCENT
    sub = doc.add_paragraph()
    run = sub.add_run("Bastion: runtime governance control plane for AI agents")
    run.font.size, run.font.color.rgb = Pt(13), RGBColor(0x5B, 0x64, 0x75)
    meta = doc.add_paragraph()
    run = meta.add_run(f"Bastion v{__version__} · {datetime.now(UTC):%Y-%m-%d}")
    run.font.color.rgb = RGBColor(0x5B, 0x64, 0x75)
    doc.add_paragraph()
    notice = doc.add_paragraph()
    notice.add_run(DISCLAIMER).bold = True
    notice.add_run(
        " All data and examples are synthetic. Regulatory references are unverified starting "
        "points marked [VERIFY]."
    )
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    contents(doc, headings)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    lists: list[str] = []
    in_quote = False
    table_rows: list[list] = []
    table_has_header = False
    index = 0
    seen_title = False
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind == "heading_open":
            content = tokens[index + 1]
            level = int(token.tag[1])
            if level == 1 and not seen_title:
                seen_title = True  # already on the title page
            else:
                paragraph = doc.add_heading(level=max(level - 1, 1))
                inline(paragraph, content)
            index += 3
            continue
        if kind in ("bullet_list_open", "ordered_list_open"):
            lists.append("List Bullet" if kind.startswith("bullet") else "List Number")
        elif kind in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif kind == "blockquote_open":
            in_quote = True
        elif kind == "blockquote_close":
            in_quote = False
        elif kind == "paragraph_open" and not table_rows:
            content = tokens[index + 1]
            if lists:
                depth = min(len(lists), 3)
                style = lists[-1] + (f" {depth}" if depth > 1 else "")
                paragraph = doc.add_paragraph(style=style)
            else:
                paragraph = doc.add_paragraph()
            if in_quote:
                paragraph.paragraph_format.left_indent = Cm(0.6)
                border = OxmlElement("w:pBdr")
                left = OxmlElement("w:left")
                for key, value in (("val", "single"), ("sz", "18"), ("space", "8"),
                                   ("color", "9A6700")):  # fmt: skip
                    left.set(qn(f"w:{key}"), value)
                border.append(left)
                paragraph._p.get_or_add_pPr().append(border)
            inline(paragraph, content)
            index += 3
            continue
        elif kind == "fence":
            if token.info.strip() == "mermaid":
                image = next(diagrams)
                picture = doc.add_paragraph()
                picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
                shape = picture.add_run().add_picture(io.BytesIO(image))
                scale = min(1.0, Cm(BODY_WIDTH_CM) / shape.width, Cm(20.0) / shape.height)
                natural = 0.5 * 0.75  # screenshots are taken at 2x; show them at about 75%
                factor = min(scale, natural)
                shape.width, shape.height = int(shape.width * factor), int(shape.height * factor)
            else:
                for line in token.content.rstrip("\n").split("\n"):
                    paragraph = doc.add_paragraph()
                    paragraph.paragraph_format.space_after = Pt(0)
                    paragraph.paragraph_format.left_indent = Cm(0.4)
                    run = paragraph.add_run(line or " ")
                    run.font.name, run.font.size = "Consolas", Pt(8.5)
                doc.add_paragraph().paragraph_format.space_after = Pt(2)
        elif kind == "table_open":
            table_rows, table_has_header = [], False
        elif kind == "thead_open":
            table_has_header = True
        elif kind == "tr_open":
            table_rows.append([])
        elif kind == "inline" and table_rows and tokens[index - 1].type in ("th_open", "td_open"):
            table_rows[-1].append(token)
        elif kind == "table_close":
            add_table(doc, table_rows, table_has_header)
            table_rows = []
        index += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return title, len(headings)


def build_pdf(source: Path, out: Path, title: str) -> None:
    subprocess.run(  # noqa: S603 - this interpreter and a script in this repository
        [sys.executable, str(ROOT / "scripts" / "make_doc_pdf.py"), "--title", title,
         "--subtitle", "Bastion: runtime governance control plane for AI agents",
         "--out", str(out), str(source)],
        check=True, cwd=ROOT,
    )  # fmt: skip


def main() -> int:
    for name in DOCUMENTS:
        source = SOURCE / f"{name}.md"
        if not source.is_file():
            print(f"missing {source.relative_to(ROOT)}", file=sys.stderr)
            return 1
        title, count = build_docx(source, EXPORTS / f"{name}.docx")
        print(f"{(EXPORTS / (name + '.docx')).relative_to(ROOT)}: {count} headings")
        build_pdf(source, EXPORTS / f"{name}.pdf", title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
