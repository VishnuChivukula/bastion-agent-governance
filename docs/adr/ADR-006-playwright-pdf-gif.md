# ADR-006: Playwright for the evidence PDF and the demo GIF

**Status:** accepted · 2026-11-16

## Context
Evidence packs need a header with the document name and a `Page X of Y` footer. The README needs a GIF of the console.

## Decision
Render Jinja2 → HTML → PDF with Playwright Chromium (`page.pdf` with header and footer templates). The same Playwright install scripts the console for screenshots, which Pillow assembles into the GIF.

## Consequences
- One dependency covers both needs, and the PDF matches the HTML preview.
- Chromium adds several hundred MB to the container image. Accepted for v0.1.
- PDF generation is unavailable where Chromium is not installed; the HTML pack still works.
