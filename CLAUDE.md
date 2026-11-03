# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small Flask HTTP API that generates print-ready vector SVGs of QR inspection cards (fall-protection / "anticaídas" systems). It is called from Power Automate / AppSheet with a JSON list of records and returns SVG strings in JSON. It does not read CSVs or write files; `listado_tarjetas_25.csv` is only sample data showing the expected columns.

Code comments, API messages, and commit messages are in Spanish.

## Commands

There is no test suite, linter, or build step.

```bash
pip install -r requirements.txt
flask --app app run                 # local dev server (entry object is `application`, not `app`)
gunicorn app:application            # production-style
```

Smoke test (add `-H "X-API-Key: ..."` if `SVG_API_KEY` is set):

```bash
curl http://127.0.0.1:5000/         # GET: health + template registry
curl -X POST http://127.0.0.1:5000/ -H "Content-Type: application/json" \
  -d '{"template":"siesa","rows":[{"CLIENTE":"Acme","CODPRY":"PRY-1","FECHA":"01-10-2025","TIPO_SISTEMA":"PUNTO ANCLAJE","NUMERO":"7"}]}'
```

## Architecture

- [app.py](app.py): the HTTP layer. Single route `/`. GET reports which templates exist. POST checks the optional `X-API-Key` (enforced only when the `SVG_API_KEY` env var is set), resolves `template` (accepts `siesa`, `template-siesa`, `template-siesa.svg`; defaults to `anticaidas`), and calls `generate_svg_bundle_from_rows`. The `TEMPLATES` dict holds each template's SVG file and its QR base URL. Adding a brand means adding an entry here, a `template-<key>.svg` file, and a copy line in `.cpanel.yml`.
- [genQRSVG.py](genQRSVG.py): the rendering engine. Pipeline:
  1. `prepare_sheet_rows`: normalize column names through `COLUMN_ALIASES` (drops `@odata.*` keys), require `CLIENTE, CODPRY, FECHA, TIPO_SISTEMA`, skip blank rows, keep the first 25 (`MAX_CARDS`, a 5×5 grid of 80 mm cards) and pad with empty rows.
  2. `assign_qr_numbers_once`: give each row a random 30-digit `NUM_QR` unless one was supplied. This runs **before** rendering so the sheet and the individual card SVGs share the same QR. Keep that ordering when refactoring.
  3. `extract_inner_from_template`: strip the `<svg>` wrapper and keep all root-level `<g>` groups, not only `layer-MC0` (the SIESA logo sits in a sibling group), then remove Inkscape/sodipodi metadata.
  4. `render_card`: replace placeholder elements by `id`, using regexes on the SVG string (no XML parser):
     - `<text id="TXT_CLIENTE|TXT_CODPRY|TXT_FECHA|TXT_TIPOSISTEMA|TXT_NUMERO|NUM_QR">` → text converted to **outlined vector paths** through Qt (`QPainterPath.addText`), so output never depends on fonts installed at print time. Per-field size, horizontal condense, and nudge values live in the `FONT_PX`, `CONDENSE_X_MAP`, and `NUDGE_Y_MM`/`NUDGE_X_MM` dicts at the top of the file.
     - `<rect id="QR_BOX">` → vector QR (`qrcode` SvgPathImage, error correction H) encoding `base_qr_url + NUM_QR`, scaled to fit the rect.
     - All `id` attributes are then stripped so the 25 card copies don't collide.
  5. Output: one 400×400 mm sheet SVG plus one 80×80 mm SVG per record, all in the JSON response (`files`, `qr_numbers`, `used_rows`, `ignored_rows`). `generate_svg_from_rows` is an older sheet-only variant.

### SVG templates

`template-*.svg` are Inkscape files whose coordinates are in mm. To be filled, a template must contain the placeholder ids listed above. The text position comes from the `x`/`y`/`text-anchor`/`transform`/`font-size` attributes on the `<text>` open tag, and the `QR_BOX` rect must have `x/y/width/height`. Placeholders that are missing are skipped silently.

### Qt dependency

PySide6 is used only for font metrics and glyph outlines. `QT_QPA_PLATFORM=offscreen` is set before Qt is imported in both modules, so it runs headless. The font comes from `fonts/` (`SVG_FONT_DIR`, `SVG_FONT_FILES` separated by `;`) and falls back to system "Arial".

### Environment variables

`SVG_API_KEY`, `BASE_QR_URL_ANTICAIDAS`, `BASE_QR_URL_SIESA`, `BASE_QR_URL` (fallback when no base URL is passed), `SVG_QR_COLOR`, `SVG_TEXT_COLOR` (both default `#400080`), `SVG_FONT_DIR`, `SVG_FONT_FILES`.

## Deployment

Deployed to cPanel (CloudLinux Passenger, Python 3.11) through `.cpanel.yml`. [passenger_wsgi.py](passenger_wsgi.py) imports `application`. The deploy copies an **explicit list of files**, so any new module, template, or asset must be added to `.cpanel.yml` or it won't reach the server. `.htaccess` is copied only when the server doesn't already have one (it holds the Passenger config and env vars managed by cPanel), and the deploy touches `tmp/restart.txt` to restart the app.
