"""Check that every exported requirements document opens and is laid out as intended.

    uv run --with pymupdf python scripts/verify_exports.py [output-folder]

For each document in docs/requirements/exports/:

- the `.docx` is opened with python-docx and checked for Word heading styles, real tables, a
  TOC field, the document name in the header and PAGE / NUMPAGES fields in the footer;
- if LibreOffice (`soffice`) is available, the `.docx` is converted to PDF with it (CI does
  this; it is an independent renderer);
- page 1 and the last page of each PDF (converted and Chromium-built) are rendered to PNG,
  and the header text and `Page N of N` footer are checked on the last page.

Exit 1 if a file cannot be opened or a header or footer is missing.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "docs" / "requirements" / "exports"


def check_docx(path: Path) -> list[str]:
    problems = []
    document = Document(str(path))
    styles = [p.style.name for p in document.paragraphs]
    headings = [s for s in styles if s.startswith("Heading")]
    body_xml = document.element.xml
    section = document.sections[0]
    header_text = " ".join(p.text for p in section.header.paragraphs)
    footer_xml = section.footer._element.xml
    if len(headings) < 3:
        problems.append("fewer than three Word headings")
    if not document.tables:
        problems.append("no Word tables")
    if 'TOC \\o "1-2"' not in body_xml:
        problems.append("no TOC field")
    if not header_text.strip():
        problems.append("empty header")
    for name in ("PAGE", "NUMPAGES"):
        if not re.search(rf"<w:instrText[^>]*> {name} </w:instrText>", footer_xml):
            problems.append(f"no {name} field in the footer")
    print(f"ok    {path.name:<38} {len(headings):>3} headings · {len(document.tables):>3} tables"
          f" · header: {header_text[:40]!r}" if not problems else f"CHECK {path.name}")  # fmt: skip
    return [f"{path.name}: {p}" for p in problems]


def soffice_to_pdf(docx: Path, out_dir: Path) -> Path:
    subprocess.run(  # noqa: S603 - fixed command, local files
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],  # noqa: S607
        check=True, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    produced = out_dir / f"{docx.stem}.pdf"
    target = out_dir / f"{docx.stem}.from-docx.pdf"
    produced.rename(target)
    return target


def check_pdf(
    pdf: Path, out_dir: Path, label: str, title: str, bare_title_page: bool = False
) -> list[str]:
    document = pymupdf.open(pdf)
    pages = document.page_count
    for number in sorted({0, pages - 1}):
        document[number].get_pixmap(dpi=70).save(out_dir / f"{label}-p{number + 1}.png")
    first = " ".join(document[0].get_text().split())
    last = " ".join(document[pages - 1].get_text().split())
    document.close()
    problems = []
    if f"Page {pages} of {pages}" not in last:
        problems.append(f"'Page {pages} of {pages}' not found on the last page")
    if title not in last:
        problems.append("document name not found in the header of the last page")
    if bare_title_page and re.search(r"Page 1 of \d+", first):
        problems.append("the title page should carry no page footer")
    print(f"{'ok' if not problems else 'CHECK':<5} {label:<38} {pages:>3} pages")
    return [f"{label}: {p}" for p in problems]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else EXPORTS / "_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    have_soffice = shutil.which("soffice") is not None
    problems: list[str] = []
    documents = sorted(p for p in EXPORTS.glob("*.docx") if not p.name.startswith("~$"))
    if not documents:
        problems.append("no .docx exports found")
    for docx in documents:
        problems += check_docx(docx)
        header = Document(str(docx)).sections[0].header.paragraphs[0].text
        chromium = EXPORTS / f"{docx.stem}.pdf"
        if not chromium.is_file():
            problems.append(f"{chromium.name}: missing")
        else:
            problems += check_pdf(chromium, out_dir, f"{docx.stem}.pdf", header)
        if have_soffice:
            try:
                converted = soffice_to_pdf(docx, out_dir)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                problems.append(f"{docx.name}: LibreOffice could not convert it ({exc})")
                continue
            problems += check_pdf(
                converted, out_dir, f"{docx.stem}.docx", header, bare_title_page=True
            )
    if not have_soffice:
        print("note: LibreOffice (soffice) not found: the .docx → PDF rendering was skipped here."
              " CI runs it.")  # fmt: skip
    for problem in problems:
        print(f"PROBLEM {problem}", file=sys.stderr)
    print(f"images in {out_dir}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
