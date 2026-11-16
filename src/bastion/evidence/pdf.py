"""HTML → PDF with headless Chromium (ADR-006).

Every page carries the document name in the header and `Page X of Y` in the footer.
"""

import html as html_lib

MARGIN = {"top": "22mm", "bottom": "20mm", "left": "16mm", "right": "16mm"}
_STYLE = "font-family: Helvetica, Arial, sans-serif; font-size: 8px; color: #555; width: 100%;"


class PdfUnavailable(RuntimeError):
    """Chromium is not installed (run `uv run playwright install chromium`)."""


def header_template(document_name: str) -> str:
    return (
        f'<div style="{_STYLE} padding: 0 16mm; border-bottom: 0.5px solid #bbb;">'
        f"{html_lib.escape(document_name)}</div>"
    )


def footer_template(note: str) -> str:
    return (
        f'<div style="{_STYLE} padding: 0 16mm; display: flex; justify-content: space-between;">'
        f"<span>{html_lib.escape(note)}</span>"
        '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>'
        "</div>"
    )


def html_to_pdf(html: str, *, document_name: str, footer_note: str = "") -> bytes:
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=header_template(document_name),
                    footer_template=footer_template(footer_note),
                    margin=MARGIN,
                )
            finally:
                browser.close()
    except Error as exc:
        if "Executable doesn't exist" in str(exc):
            raise PdfUnavailable(PdfUnavailable.__doc__) from exc
        raise
