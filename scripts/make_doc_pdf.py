"""Build one PDF from a set of Markdown documents (`make design-pdf`).

    python scripts/make_doc_pdf.py --title "Bastion Design Pack" --out docs/design/X.pdf A.md B.md

Markdown → HTML (markdown-it) → headless Chromium, the same path the evidence pack uses.
The PDF has a title page, a table of contents with page numbers, the document name in the
header and `Page X of Y` in the footer. Mermaid diagrams are rendered in the browser, which
needs network access to load the Mermaid script; the build fails if a diagram does not render.
"""

import argparse
import html
import io
import re
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from bastion import DISCLAIMER, __version__
from bastion.evidence.pdf import MARGIN, footer_template, header_template

ROOT = Path(__file__).resolve().parents[1]
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
MARK = "@@"
REPO_URL = "https://github.com/VishnuChivukula/bastion-agent-governance/blob/main/"

CSS = """
:root { --ink: #1a1f2b; --muted: #5b6475; --line: #d5d9e2; --soft: #f4f6fa; --accent: #1f4e8c; }
* { box-sizing: border-box; }
body { font-family: Helvetica, Arial, sans-serif; color: var(--ink); font-size: 9.5pt;
       line-height: 1.42; margin: 0; }
h1 { font-size: 19pt; color: var(--accent); margin: 0 0 10px; }
h2 { font-size: 13pt; margin: 20px 0 6px; padding-bottom: 3px; border-bottom: 1.2px solid var(--accent);
     break-after: avoid; }
h3 { font-size: 10.5pt; margin: 14px 0 4px; break-after: avoid; }
h4 { font-size: 9.5pt; margin: 10px 0 4px; break-after: avoid; }
p, ul, ol { margin: 5px 0; } ul, ol { padding-left: 18px; }
a { color: var(--accent); text-decoration: none; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 8pt; }
th, td { border: 1px solid var(--line); padding: 3px 5px; text-align: left; vertical-align: top;
         overflow-wrap: anywhere; }
th { background: var(--soft); } tr { break-inside: avoid; }
code { font-family: Menlo, Consolas, monospace; font-size: 7.6pt; overflow-wrap: anywhere; }
pre { background: var(--soft); border: 1px solid var(--line); border-radius: 4px; padding: 6px 8px;
      white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre.mermaid { background: #fff; border: none; text-align: center; padding: 4px 0; }
pre.mermaid svg { max-width: 100%; max-height: 235mm; height: auto; }
blockquote { border-left: 3px solid #9a6700; background: #fff8e6; margin: 8px 0; padding: 4px 10px; }
section.doc { break-before: page; }
.title { height: 235mm; display: flex; flex-direction: column; justify-content: center; }
.title h1 { font-size: 30pt; margin-bottom: 6px; } .title .sub { font-size: 13pt; color: var(--muted); }
.title .meta { margin-top: 26px; color: var(--muted); } .title .notice { margin-top: 30px; max-width: 150mm; }
.toc { break-before: page; } .toc h1 { margin-bottom: 12px; }
.toc .row { display: flex; align-items: baseline; margin: 1.5px 0; }
.toc .row.l1 { font-weight: 600; margin-top: 9px; } .toc .row.l2 { padding-left: 14px; font-size: 8.8pt; }
.toc .dots { flex: 1; border-bottom: 1px dotted #9aa3b5; margin: 0 6px; }
.pm { font-size: 1px; color: #fff; }
.toc .page { width: 22px; text-align: right; font-variant-numeric: tabular-nums; }
"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def strip_frame(text: str) -> str:
    """Drop the kit's first line (**Bastion Kit · name**) and its page footer."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("**Bastion Kit ·"):
        lines = lines[1:]
    if lines and re.fullmatch(r"\*.+· Page 1 of 1\*", lines[-1].strip()):
        lines = lines[:-1]
        while lines and lines[-1].strip() in ("", "---"):
            lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def render_doc(
    path: Path, names: set[str], rel_base: str
) -> tuple[str, list[tuple[int, str, str]]]:
    """HTML for one document and its (level, text, anchor) headings for the contents page."""
    md = MarkdownIt("commonmark").enable("table")
    doc_id = "doc-" + slug(path.stem)
    tokens = md.parse(strip_frame(path.read_text(encoding="utf-8")))
    headings: list[tuple[int, str, str]] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag in ("h1", "h2"):
            text = tokens[index + 1].content
            plain = re.sub(r"[`*_]|\[VERIFY\]", "", text).strip()
            anchor = doc_id if token.tag == "h1" else f"{doc_id}-{slug(plain)}"
            token.attrSet("id", anchor)
            headings.append((int(token.tag[1]), plain, anchor))
            marker = tokens[index + 1].children
            if marker is not None:  # an invisible tag the page lookup can find exactly
                tag = Token("html_inline", "", 0)
                tag.content = f'<span class="pm">{MARK}{anchor}{MARK}</span>'
                marker.append(tag)
        if token.type == "fence" and token.info.strip() == "mermaid":
            token.type, token.content = (
                "html_block",
                (f'<pre class="mermaid">{html.escape(token.content)}</pre>\n'),
            )
    body = md.renderer.render(tokens, md.options, {})

    def link(match: re.Match) -> str:
        target = match.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)
        name = target.split("#")[0].split("/")[-1]
        if name in names:  # another document of this pack
            return f'href="#doc-{slug(Path(name).stem)}"'
        resolved = (Path(rel_base) / target.split("#")[0]).as_posix()
        parts: list[str] = []
        for part in resolved.split("/"):
            if part == "..":
                parts.pop()
            elif part not in (".", ""):
                parts.append(part)
        return f'href="{REPO_URL}{"/".join(parts)}"'

    body = re.sub(r'href="([^"]+)"', link, body)
    return f'<section class="doc">{body}</section>', headings


def build_html(
    title: str, subtitle: str, docs: list[str], toc: list[tuple[int, str, str, str]]
) -> str:
    rows = "".join(
        f'<div class="row l{level}"><a href="#{anchor}">{html.escape(text)}</a>'
        f'<span class="dots"></span><span class="page">{page}</span></div>'
        for level, text, anchor, page in toc
    )
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<div class="title"><h1>{html.escape(title)}</h1><div class="sub">{html.escape(subtitle)}</div>
<div class="meta">Bastion v{__version__} · generated {generated}</div>
<blockquote class="notice"><strong>{DISCLAIMER}</strong> All data is synthetic. Regulatory
references are unverified starting points marked [VERIFY].</blockquote></div>
<div class="toc"><h1>Contents</h1>{rows}</div>
{"".join(docs)}
<script src="{MERMAID}"></script>
<script>
  window.__diagrams = 'pending';
  (async () => {{
    try {{
      mermaid.initialize({{ startOnLoad: false, theme: 'neutral', securityLevel: 'strict',
                           flowchart: {{ htmlLabels: false }} }});
      await mermaid.run({{ querySelector: 'pre.mermaid' }});
      window.__diagrams = 'ok';
    }} catch (error) {{ window.__diagrams = 'error: ' + (error.message || error); }}
  }})();
</script></body></html>"""


def to_pdf(page_html: str, title: str, footer_note: str) -> bytes:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(page_html, wait_until="networkidle", timeout=120_000)
            if 'pre class="mermaid"' in page_html:
                page.wait_for_function("window.__diagrams !== 'pending'", timeout=120_000)
                state = page.evaluate("window.__diagrams")
                if state != "ok":
                    raise RuntimeError(f"a Mermaid diagram did not render ({state})")
            return page.pdf(
                format="A4", print_background=True, display_header_footer=True,
                header_template=header_template(title),
                footer_template=footer_template(footer_note), margin=MARGIN,
            )  # fmt: skip
        finally:
            browser.close()


def squash(text: str) -> str:
    """Comparable text: PDF extraction turns "fi" into a ligature and reflows spaces."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def page_numbers(pdf: bytes, headings: list[tuple[int, str, str]]) -> list[str]:
    """The page each heading is printed on, found through its invisible marker."""
    reader = PdfReader(io.BytesIO(pdf))
    pages = [squash(p.extract_text() or "") for p in reader.pages]
    found = []
    for _, _, anchor in headings:
        needle = f"{MARK}{anchor}{MARK}"
        hit = next((i for i, text in enumerate(pages) if needle in text), None)
        found.append(str(hit + 1) if hit is not None else "")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--footer", default=DISCLAIMER)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    paths = [Path(f).resolve() for f in args.files]
    names = {p.name for p in paths}
    docs, headings = [], []
    for path in paths:
        try:
            rel_base = path.parent.relative_to(ROOT).as_posix()
        except ValueError:
            rel_base = ""
        body, found = render_doc(path, names, rel_base)
        docs.append(body)
        headings += found

    # Pass 1 lays the pack out with blank page numbers; pass 2 fills them in. The contents
    # page has the same height in both passes, so the numbers found in pass 1 stay right.
    blank = [(level, text, anchor, "") for level, text, anchor in headings]
    first = to_pdf(build_html(args.title, args.subtitle, docs, blank), args.title, args.footer)
    numbers = page_numbers(first, headings)
    toc = [(lv, text, anchor, n) for (lv, text, anchor), n in zip(headings, numbers, strict=True)]
    clean = [re.sub(r'<span class="pm">.*?</span>', "", doc) for doc in docs]
    final = to_pdf(build_html(args.title, args.subtitle, clean, toc), args.title, args.footer)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(final)
    total = len(PdfReader(io.BytesIO(final)).pages)
    missing = [text for (_, text, _), n in zip(headings, numbers, strict=True) if not n]
    print(f"{out}: {total} pages, {len(headings)} contents entries, {len(final) // 1024} kB")
    if missing:
        print(f"warning: no page number found for: {missing[:5]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
