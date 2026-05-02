#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVG card sheet generator for Power Automate + PythonAnywhere.

This module is intentionally API-oriented: it does not read a local CSV and it
does not write output files. The caller provides rows and an SVG template, and
receives the generated SVG plus the QR numbers used on each card.
"""

from __future__ import annotations

import io
import os
import re
import secrets
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import qrcode
from qrcode.image.svg import SvgPathImage
from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QPainterPath,
)


BASE_DIR = Path(__file__).resolve().parent

QR_COLOR = os.getenv("SVG_QR_COLOR", "#400080")
TEXT_COLOR = os.getenv("SVG_TEXT_COLOR", "#400080")
BASE_QR_URL = os.getenv(
    "BASE_QR_URL",
    "https://www.anticaidas.cl/consultaRegistroQR.php?LlaveQR=",
)

# Sheet and card measures in millimeters.
CARD_MM = 80.0
COLS, ROWS = 5, 5
MAX_CARDS = COLS * ROWS
SHEET_W_MM, SHEET_H_MM = CARD_MM * COLS, CARD_MM * ROWS

REQUIRED_COLUMNS = ("CLIENTE", "CODPRY", "FECHA", "TIPO_SISTEMA")
COLUMN_ALIASES = {
    "CLIENTE": "CLIENTE",
    "CODPRY": "CODPRY",
    "COD_PRY": "CODPRY",
    "FECHA": "FECHA",
    "TIPO_SISTEMA": "TIPO_SISTEMA",
    "TIPOSISTEMA": "TIPO_SISTEMA",
    "TIPO_DE_SISTEMA": "TIPO_SISTEMA",
    "NUM_QR": "NUM_QR",
    "NUMQR": "NUM_QR",
}

# Text to paths.
FONT_DIR = Path(os.getenv("SVG_FONT_DIR", str(BASE_DIR / "fonts")))
FONT_FILES = [
    name.strip()
    for name in os.getenv("SVG_FONT_FILES", "Arial CE Regular.ttf").split(";")
    if name.strip()
]
FONT_FAMILY: str | None = None
FONT_LOADED = False

SVG_DPI = 96.0
PX_TO_MM = 96 / SVG_DPI

FONT_PX = {
    "TXT_CLIENTE": 17.0,
    "TXT_CODPRY": 17.0,
    "TXT_FECHA": 13.0,
    "TXT_TIPOSISTEMA": 17.0,
    "NUM_QR": 10.0,
}

FORCE_UPPERCASE = True
TEXT_OUTLINE_ONLY = True
TEXT_STROKE_MM = 0.18
TEXT_SIZE_SCALE = 1.20
BASELINE_NUDGE_MM = 0.5

CONDENSE_X_MAP = {
    "TXT_CLIENTE": 0.5,
    "TXT_CODPRY": 0.5,
    "TXT_FECHA": 0.5,
    "TXT_TIPOSISTEMA": 0.5,
    "NUM_QR": 0.8,
}

NUDGE_Y_MM = {
    "TXT_CLIENTE": 0.0,
    "TXT_CODPRY": 0.0,
    "TXT_FECHA": 0.0,
    "TXT_TIPOSISTEMA": 0.0,
    "NUM_QR": 0.60,
}
NUDGE_X_MM: dict[str, float] = {}


def gen_qr_number(n: int = 30) -> str:
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(n))


def ensure_qt_app() -> QGuiApplication:
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication([])
    return app


def _load_embedded_fonts() -> None:
    global FONT_FAMILY, FONT_LOADED
    if FONT_LOADED and FONT_FAMILY:
        return

    families: list[str] = []
    if FONT_DIR.exists():
        for fname in FONT_FILES:
            font_path = FONT_DIR / fname
            if font_path.exists():
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                if font_id != -1:
                    families.extend(QFontDatabase.applicationFontFamilies(font_id))

    FONT_FAMILY = families[0] if families else "Arial"
    FONT_LOADED = True


def _qt_path_to_svg_d(path: QPainterPath) -> str:
    cmds: list[str] = []
    i, n = 0, path.elementCount()
    while i < n:
        el = path.elementAt(i)
        et = path.elementAt(i).type
        if et == QPainterPath.ElementType.MoveToElement:
            cmds.append(f"M{el.x} {el.y}")
        elif et == QPainterPath.ElementType.LineToElement:
            cmds.append(f"L{el.x} {el.y}")
        elif et == QPainterPath.ElementType.CurveToElement and i + 2 < n:
            c1 = el
            c2 = path.elementAt(i + 1)
            p = path.elementAt(i + 2)
            cmds.append(f"C{c1.x} {c1.y} {c2.x} {c2.y} {p.x} {p.y}")
            i += 2
        i += 1
    return " ".join(cmds)


def _parse_font_size_px(open_tag: str, default_px: float) -> float:
    match = re.search(r'font-size="([\d.]+)\s*(px|mm|pt)?"', open_tag)
    if not match:
        match = re.search(r"font-size\s*:\s*([\d.]+)\s*(px|mm|pt)?", open_tag)
    if not match:
        return default_px

    value = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    if unit == "mm":
        return value / PX_TO_MM
    if unit == "pt":
        return value * (96.0 / 72.0)
    return value


def _qt_text_path_group(open_tag: str, text: Any, text_id: str) -> str:
    ax = re.search(r'\sx="([\d.\-]+)"', open_tag)
    ay = re.search(r'\sy="([\d.\-]+)"', open_tag)
    x_mm = float(ax.group(1)) if ax else 0.0
    y_mm = float(ay.group(1)) if ay else 0.0

    anch = re.search(r'text-anchor="(start|middle|end)"', open_tag)
    anchor = anch.group(1) if anch else "start"

    mtr = re.search(r'transform="([^"]+)"', open_tag)
    transform_outer = mtr.group(1) if mtr else None

    ensure_qt_app()
    _load_embedded_fonts()

    text_value = "" if text is None else str(text)
    text_to_draw = text_value.upper() if FORCE_UPPERCASE else text_value

    px_size = _parse_font_size_px(open_tag, FONT_PX.get(text_id, 14.0))
    px_size *= TEXT_SIZE_SCALE

    font = QFont(FONT_FAMILY)
    font.setPixelSize(int(round(px_size)))
    metrics = QFontMetricsF(font)
    advance_px = metrics.horizontalAdvance(text_to_draw)

    cond = CONDENSE_X_MAP.get(text_id, 1.0)
    if cond <= 0:
        cond = 1.0

    if anchor == "middle":
        x_shift_px = -(advance_px * cond) / 2.0
    elif anchor == "end":
        x_shift_px = -(advance_px * cond)
    else:
        x_shift_px = 0.0

    try:
        cap_h = metrics.capHeight()
    except Exception:
        cap_h = metrics.ascent() * 0.7

    auto_nudge_mm = (metrics.ascent() - cap_h) * PX_TO_MM
    y_mm += auto_nudge_mm + NUDGE_Y_MM.get(text_id, BASELINE_NUDGE_MM)
    x_mm += NUDGE_X_MM.get(text_id, 0.0)

    path = QPainterPath()
    path.addText(QPointF(x_shift_px, 0.0), font, text_to_draw)
    d = _qt_path_to_svg_d(path)

    sx = PX_TO_MM * cond
    sy = PX_TO_MM

    if TEXT_OUTLINE_ONLY:
        style = f'fill="none" stroke="{TEXT_COLOR}" stroke-width="{TEXT_STROKE_MM}"'
    else:
        style = f'fill="{TEXT_COLOR}" stroke="none"'

    inner = (
        f'<g transform="translate({x_mm},{y_mm}) scale({sx},{sy})">'
        f'<path d="{d}" {style}/>'
        f"</g>"
    )
    if transform_outer:
        return f'<g transform="{transform_outer}">{inner}</g>'
    return inner


def replace_text_id_with_path(svg_fragment: str, text_id: str, new_text: Any) -> str:
    match = re.search(
        rf'(<text[^>]*id="{re.escape(text_id)}"[^>]*>)(.*?)(</text>)',
        svg_fragment,
        flags=re.DOTALL,
    )
    if not match:
        return svg_fragment

    open_tag = match.group(1)
    group = _qt_text_path_group(open_tag, new_text, text_id)
    return svg_fragment[: match.start()] + group + svg_fragment[match.end() :]


def clean_inkscape_blocks(svg: str) -> str:
    svg = re.sub(r"<sodipodi:[^>]*>.*?</sodipodi:[^>]*>", "", svg, flags=re.DOTALL)
    svg = re.sub(r"<inkscape:[^>]*>.*?</inkscape:[^>]*>", "", svg, flags=re.DOTALL)
    svg = re.sub(r"<metadata[^>]*>.*?</metadata>", "", svg, flags=re.DOTALL)
    svg = re.sub(
        r'\s+(inkscape|sodipodi|xmlns:inkscape|xmlns:sodipodi):[a-zA-Z0-9_-]+="[^"]*"',
        "",
        svg,
    )
    return svg


def extract_inner_from_template(template_svg: str) -> str:
    match = re.search(
        r'(<g[^>]*id="layer-MC0"[^>]*>.*?</g>)',
        template_svg,
        flags=re.DOTALL,
    )
    if match:
        inner = match.group(1)
    else:
        inner = re.sub(r"^.*?<svg[^>]*>\s*", "", template_svg, flags=re.DOTALL)
        inner = re.sub(r"\s*</svg>\s*$", "", inner, flags=re.DOTALL)
    return clean_inkscape_blocks(inner)


def make_qr_svg_group(data: str, x: float, y: float, w: float, h: float) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        border=1,
        box_size=10,
    )
    qr.add_data(str(data))
    qr.make(fit=True)

    img = qr.make_image(image_factory=SvgPathImage)
    bio = io.BytesIO()
    img.save(bio)
    qr_svg = bio.getvalue().decode("utf-8")

    match_vb = re.search(r'viewBox="([\d.\s\-]+)"', qr_svg)
    if match_vb:
        _, _, vb_w, vb_h = map(float, match_vb.group(1).split())
    else:
        vb_w = float(re.search(r'width="([\d.]+)"', qr_svg).group(1))
        vb_h = float(re.search(r'height="([\d.]+)"', qr_svg).group(1))

    qr_inner = re.sub(r"^.*?<svg[^>]*>\s*", "", qr_svg, flags=re.DOTALL)
    qr_inner = re.sub(r"\s*</svg>\s*$", "", qr_inner, flags=re.DOTALL)
    qr_inner = re.sub(r'fill="[^"]*"', f'fill="{QR_COLOR}"', qr_inner)
    qr_inner = re.sub(r'stroke="none"', f'stroke="{QR_COLOR}"', qr_inner)
    qr_inner = re.sub(r"fill:[#\w\d]+", f"fill:{QR_COLOR}", qr_inner)
    qr_inner = re.sub(r"stroke:[#\w\d]+", f"stroke:{QR_COLOR}", qr_inner)
    qr_inner = f'<g fill="{QR_COLOR}" stroke="{QR_COLOR}" stroke-width="0">{qr_inner}</g>'

    scale = min(float(w) / vb_w, float(h) / vb_h)
    dx = float(x) + (float(w) - vb_w * scale) / 2
    dy = float(y) + (float(h) - vb_h * scale) / 2
    return f'<g transform="translate({dx},{dy}) scale({scale})">{qr_inner}</g>'


def replace_qr_rect_with_vector(svg_fragment: str, qr_data: str) -> str:
    match = re.search(r'(<rect[^>]*id="QR_BOX"[^>]*>)', svg_fragment)
    if not match:
        return svg_fragment

    rect_tag = match.group(1)
    attrs = dict(re.findall(r'(\w+)=["\']([^"\']+)["\']', rect_tag))
    x = float(attrs.get("x", "0"))
    y = float(attrs.get("y", "0"))
    w = float(attrs.get("width", "40"))
    h = float(attrs.get("height", "40"))
    qr_group = make_qr_svg_group(qr_data, x, y, w, h)
    return svg_fragment.replace(rect_tag, qr_group)


def _canonical_column_name(key: Any) -> str:
    clean = str(key).strip().lstrip("\ufeff")
    normalized = re.sub(r"\s+", "_", clean.upper())
    return COLUMN_ALIASES.get(normalized, clean)


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    norm: dict[str, str] = {}
    for key, value in (row or {}).items():
        if key is None:
            continue
        if str(key).startswith("@odata."):
            continue
        canonical = _canonical_column_name(key)
        norm[canonical] = "" if value is None else str(value).strip()
    return norm


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise ValueError("El campo 'rows' debe ser una lista de registros.")
    return [normalize_row(row) for row in rows if isinstance(row, dict)]


def validate_required_columns(rows: list[dict[str, str]]) -> None:
    present: set[str] = set()
    for row in rows:
        present.update(row.keys())

    missing = set(REQUIRED_COLUMNS) - present
    if missing:
        raise ValueError(f"Faltan columnas: {', '.join(sorted(missing))}.")


def is_blank_data_row(row: dict[str, str]) -> bool:
    return not any(str(row.get(col, "")).strip() for col in REQUIRED_COLUMNS)


def prepare_sheet_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int, int]:
    normalized = normalize_rows(rows)
    validate_required_columns(normalized)

    data_rows = [row for row in normalized if not is_blank_data_row(row)]
    if not data_rows:
        raise ValueError("No hay filas con datos para generar tarjetas.")

    used_rows = data_rows[:MAX_CARDS]
    ignored_rows = max(0, len(data_rows) - MAX_CARDS)
    sheet_rows = used_rows + [{} for _ in range(MAX_CARDS - len(used_rows))]
    return sheet_rows, len(used_rows), ignored_rows


def strip_all_ids(svg_fragment: str) -> str:
    return re.sub(r'\s+id="[^"]*"', "", svg_fragment)


def render_card(
    inner_template: str,
    row: dict[str, str],
    blank: bool = False,
) -> tuple[str, dict[str, str] | None]:
    if blank or not row:
        return "", None

    svg = inner_template
    svg = replace_text_id_with_path(svg, "TXT_CLIENTE", row.get("CLIENTE", ""))
    svg = replace_text_id_with_path(svg, "TXT_CODPRY", row.get("CODPRY", ""))
    svg = replace_text_id_with_path(svg, "TXT_FECHA", row.get("FECHA", ""))
    svg = replace_text_id_with_path(svg, "TXT_TIPOSISTEMA", row.get("TIPO_SISTEMA", ""))

    num_qr = row.get("NUM_QR") or gen_qr_number(30)
    url_qr = BASE_QR_URL + num_qr
    svg = replace_text_id_with_path(svg, "NUM_QR", num_qr)
    svg = replace_qr_rect_with_vector(svg, url_qr)
    svg = strip_all_ids(svg)
    svg = clean_inkscape_blocks(svg)

    qr_entry = {
        "CLIENTE": row.get("CLIENTE", ""),
        "CODPRY": row.get("CODPRY", ""),
        "NUM_QR": num_qr,
        "URL_QR": url_qr,
    }
    return svg, qr_entry


def build_sheet_svg(
    inner_template: str,
    rows_or_blanks: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{SHEET_W_MM}mm" height="{SHEET_H_MM}mm" '
            f'viewBox="0 0 {SHEET_W_MM} {SHEET_H_MM}">'
        ),
    ]
    qr_numbers: list[dict[str, str]] = []

    for i in range(MAX_CARDS):
        r = i // COLS
        c = i % COLS
        x = c * CARD_MM
        y = r * CARD_MM
        row = rows_or_blanks[i]

        content, qr_entry = render_card(inner_template, row, blank=not row)
        if content:
            parts.append(f'<g transform="translate({x},{y})">{content}</g>')
        if qr_entry:
            qr_entry["index"] = str(i + 1)
            qr_numbers.append(qr_entry)

    parts.append("</svg>")
    return "\n".join(parts), qr_numbers


def generate_svg_from_rows(
    rows: list[dict[str, Any]],
    template_svg: str,
) -> dict[str, Any]:
    if not isinstance(template_svg, str) or not template_svg.strip():
        raise ValueError("El campo 'template_svg' es obligatorio.")

    sheet_rows, used_rows, ignored_rows = prepare_sheet_rows(rows)
    inner_template = extract_inner_from_template(template_svg)
    svg, qr_numbers = build_sheet_svg(inner_template, sheet_rows)

    return {
        "svg": svg,
        "qr_numbers": qr_numbers,
        "used_rows": used_rows,
        "ignored_rows": ignored_rows,
        "max_cards": MAX_CARDS,
    }


__all__ = [
    "MAX_CARDS",
    "REQUIRED_COLUMNS",
    "generate_svg_from_rows",
]
