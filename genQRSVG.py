#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera:
- tarjetas_anticaidas_5x5_vector.svg (400 x 400 mm; 25 celdas de 80 mm; si faltan filas, deja celdas en blanco)

Entradas (misma carpeta del .py):
- listado_tarjetas_25.csv  (columnas: CLIENTE, CODPRY, FECHA, TIPO_SISTEMA)
- template-anticaidas.svg  (IDs: TXT_CLIENTE, TXT_CODPRY, TXT_FECHA, TXT_TIPOSISTEMA, NUM_QR y <rect id="QR_BOX">)

QR vectorial (paths SVG), corrección H, quiet zone (border=1).
"""

import io
import re
import html
import sys
import os
import secrets
from pathlib import Path
import csv

import qrcode
from qrcode.image.svg import SvgPathImage
from PySide6.QtGui import QFontDatabase, QFont, QFontMetricsF, QPainterPath, QGuiApplication
from PySide6.QtCore import QPointF

# ====================== Configuración fija ======================
def here() -> Path:
    if getattr(sys, "frozen", False):
        return Path.cwd()
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return Path(sys.argv[0]).resolve().parent

BASE_DIR = here()
CSV_PATH = BASE_DIR / "listado_tarjetas_25.csv"
TPL_PATH = BASE_DIR / "template-anticaidas.svg"
SVG_OUT_PATH = BASE_DIR / "tarjetas_anticaidas_5x5_vector.svg"

QR_COLOR = "#400080"
BASE_QR_URL = "https://www.anticaidas.cl/consultaRegistroQR.php?LlaveQR="

# Medidas (mm)
CARD_MM = 80.0
COLS, ROWS = 5, 5
SHEET_W_MM, SHEET_H_MM = CARD_MM * COLS, CARD_MM * ROWS

# Texto → curvas (paths)
FONT_DIR = (Path(sys.argv[0]).resolve().parent / "fonts")
FONT_FILES = ["Arial CE Regular.ttf"]
FONT_FAMILY = None
TEXT_COLOR = "#400080"

SVG_DPI = 96.0
PX_TO_MM = 96 / SVG_DPI

# Tamaños por ID en px
FONT_PX = {
    "TXT_CLIENTE":      17.0,
    "TXT_CODPRY":       17.0,
    "TXT_FECHA":        13.0,
    "TXT_TIPOSISTEMA":  17.0,   # ← nuevo campo
    "NUM_QR":           10.0,
}

# Estilo texto
FORCE_UPPERCASE   = True
TEXT_OUTLINE_ONLY = True
TEXT_STROKE_MM    = 0.18
CONDENSE_X_MAP    = {
    'TXT_CLIENTE'    : 0.5,
    'TXT_CODPRY'     : 0.5,
    'TXT_FECHA'      : 0.5,
    'TXT_TIPOSISTEMA': 0.5,   # ← nuevo campo
    'NUM_QR'         : 0.8,
}
TEXT_SIZE_SCALE   = 1.20

# Alineación fina
BASELINE_NUDGE_MM = 0.5
NUDGE_Y_MM = {
    "TXT_CLIENTE": 0.0,
    "TXT_CODPRY" : 0.0,
    "TXT_FECHA"  : 0.0,
    "TXT_TIPOSISTEMA": 0.0,   # ← nuevo campo
    "NUM_QR"     : 0.60
}
NUDGE_X_MM = {}

def gen_qr_number(n: int = 30) -> str:
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(n))

def ensure_qt_app():
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication([])
    return app

def _load_embedded_fonts():
    global FONT_FAMILY
    families = []
    if FONT_DIR.exists():
        for fname in FONT_FILES:
            p = FONT_DIR / fname
            if p.exists():
                fid = QFontDatabase.addApplicationFont(str(p))
                if fid != -1:
                    families.extend(QFontDatabase.applicationFontFamilies(fid))
    if families:
        FONT_FAMILY = families[0]
    if not FONT_FAMILY:
        FONT_FAMILY = "Arial"

def _qt_path_to_svg_d(path: QPainterPath) -> str:
    cmds, i, n = [], 0, path.elementCount()
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
            p  = path.elementAt(i + 2)
            cmds.append(f"C{c1.x} {c1.y} {c2.x} {c2.y} {p.x} {p.y}")
            i += 2
        i += 1
    return " ".join(cmds)

def _parse_font_size_px(open_tag: str, default_px: float) -> float:
    m = re.search(r'font-size="([\d\.]+)\s*(px|mm|pt)?"', open_tag)
    if not m:
        m = re.search(r'font-size\s*:\s*([\d\.]+)\s*(px|mm|pt)?', open_tag)
    if not m:
        return default_px
    val = float(m.group(1)); unit = (m.group(2) or "px").lower()
    if unit == "mm":
        return val / PX_TO_MM
    if unit == "pt":
        return val * (96.0 / 72.0)
    return val

def _qt_text_path_group(open_tag: str, text: str, text_id: str) -> str:
    ax = re.search(r'\sx="([\d\.\-]+)"', open_tag)
    ay = re.search(r'\sy="([\d\.\-]+)"', open_tag)
    x_mm = float(ax.group(1)) if ax else 0.0
    y_mm = float(ay.group(1)) if ay else 0.0
    anch = re.search(r'text-anchor="(start|middle|end)"', open_tag)
    anchor = anch.group(1) if anch else "start"
    mtr = re.search(r'transform="([^"]+)"', open_tag)
    transform_outer = mtr.group(1) if mtr else None

    ensure_qt_app()
    _load_embedded_fonts()

    text_to_draw = text.upper() if FORCE_UPPERCASE else text

    px_size = _parse_font_size_px(open_tag, FONT_PX.get(text_id, 14.0))
    px_size *= TEXT_SIZE_SCALE

    f = QFont(FONT_FAMILY)
    f.setPixelSize(int(round(px_size)))
    metrics = QFontMetricsF(f)
    advance_px = metrics.horizontalAdvance(text_to_draw)

    cond = CONDENSE_X_MAP.get(text_id, 1.0)
    if cond <= 0:
        cond = 1.0

    if anchor == "middle":
        x_shift_px = - (advance_px * cond) / 2.0
    elif anchor == "end":
        x_shift_px = - (advance_px * cond)
    else:
        x_shift_px = 0.0

    try:
        cap_h = metrics.capHeight()
    except Exception:
        cap_h = metrics.ascent() * 0.7
    ascent_px = metrics.ascent()
    auto_nudge_mm = (ascent_px - cap_h) * PX_TO_MM
    y_mm += auto_nudge_mm + NUDGE_Y_MM.get(text_id, BASELINE_NUDGE_MM)
    x_mm += NUDGE_X_MM.get(text_id, 0.0)

    path = QPainterPath()
    path.addText(QPointF(x_shift_px, 0.0), f, text_to_draw)
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
        f'</g>'
    )
    if transform_outer:
        return f'<g transform="{transform_outer}">{inner}</g>'
    else:
        return inner

def replace_text_id_with_path(svg_fragment: str, text_id: str, new_text: str) -> str:
    m = re.search(rf'(<text[^>]*id="{re.escape(text_id)}"[^>]*>)(.*?)(</text>)',
                  svg_fragment, flags=re.DOTALL)
    if not m:
        return svg_fragment
    open_tag = m.group(1)
    group = _qt_text_path_group(open_tag, new_text, text_id)
    return svg_fragment[:m.start()] + group + svg_fragment[m.end():]

# ====================== Utilidades SVG ======================
def clean_inkscape_blocks(svg: str) -> str:
    svg = re.sub(r'<sodipodi:[^>]*>.*?</sodipodi:[^>]*>', '', svg, flags=re.DOTALL)
    svg = re.sub(r'<inkscape:[^>]*>.*?</inkscape:[^>]*>', '', svg, flags=re.DOTALL)
    svg = re.sub(r'<metadata[^>]*>.*?</metadata>', '', svg, flags=re.DOTALL)
    svg = re.sub(r'\s+(inkscape|sodipodi|xmlns:inkscape|xmlns:sodipodi):[a-zA-Z0-9_-]+="[^"]*"', '', svg)
    return svg

CLASS_FONT_PX = {}

def _build_class_font_map(style_css: str):
    CLASS_FONT_PX.clear()
    if not style_css:
        return
    for m in re.finditer(r'\.([A-Za-z0-9_\-]+)\s*\{[^}]*font-size\s*:\s*([\d\.]+)\s*(px|mm|pt)?', style_css):
        cls = m.group(1)
        val = float(m.group(2))
        unit = (m.group(3) or 'px').lower()
        if unit == 'mm':
            px = val / (25.4/96.0)
        elif unit == 'pt':
            px = val * (96.0/72.0)
        else:
            px = val
        CLASS_FONT_PX[cls] = px

def _get_style_css(svg_text: str) -> str:
    m = re.search(r'<style[^>]*>(.*?)</style>', svg_text, flags=re.DOTALL|re.IGNORECASE)
    return m.group(1) if m else ""

def extract_inner_from_template(template_svg: str) -> str:
    style_css = _get_style_css(template_svg)
    _build_class_font_map(style_css)

    m = re.search(r'(<g[^>]*id="layer-MC0"[^>]*>.*?</g>)', template_svg, flags=re.DOTALL)
    if m:
        inner = m.group(1)
    else:
        inner = re.sub(r'^.*?<svg[^>]*>\s*', '', template_svg, flags=re.DOTALL)
        inner = re.sub(r'\s*</svg>\s*$', '', inner, flags=re.DOTALL)
    return clean_inkscape_blocks(inner)

def replace_text_by_id(svg_fragment: str, text_id: str, new_text: str) -> str:
    pattern = rf'(<text[^>]*id="{re.escape(text_id)}"[^>]*>)(.*?)(</text>)'
    replacement = r'\1<tspan>' + html.escape(str(new_text)) + r'</tspan>\3'
    return re.sub(pattern, replacement, svg_fragment, flags=re.DOTALL)

def strip_all_ids(svg_fragment: str) -> str:
    return re.sub(r'\s+id="[^"]*"', '', svg_fragment)

def remove_qr_rect(svg_fragment: str) -> str:
    return re.sub(r'<rect[^>]*id="QR_BOX"[^>]*/>', '', svg_fragment)

# ====================== QR vectorial (NO TOCAR) ======================
def make_qr_svg_group(data: str, x: float, y: float, w: float, h: float) -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=1, box_size=10)
    qr.add_data(str(data)); qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    bio = io.BytesIO(); img.save(bio)
    qr_svg = bio.getvalue().decode("utf-8")

    m_vb = re.search(r'viewBox="([\d\.\s\-]+)"', qr_svg)
    if m_vb:
        _, _, vb_w, vb_h = map(float, m_vb.group(1).split())
    else:
        vb_w = float(re.search(r'width="([\d\.]+)"', qr_svg).group(1))
        vb_h = float(re.search(r'height="([\d\.]+)"', qr_svg).group(1))

    qr_inner = re.sub(r'^.*?<svg[^>]*>\s*', '', qr_svg, flags=re.DOTALL)
    qr_inner = re.sub(r'\s*</svg>\s*$', '', qr_inner, flags=re.DOTALL)

    qr_inner = re.sub(r'fill="[^"]*"', f'fill="{QR_COLOR}"', qr_inner)
    qr_inner = re.sub(r'stroke="none"', f'stroke="{QR_COLOR}"', qr_inner)
    qr_inner = re.sub(r'fill:[#\w\d]+', f'fill:{QR_COLOR}', qr_inner)
    qr_inner = re.sub(r'stroke:[#\w\d]+', f'stroke:{QR_COLOR}', qr_inner)

    qr_inner = f'<g fill="{QR_COLOR}" stroke="{QR_COLOR}" stroke-width="0">{qr_inner}</g>'

    s = min(float(w)/vb_w, float(h)/vb_h)
    dx = float(x) + (float(w) - vb_w*s)/2
    dy = float(y) + (float(h) - vb_h*s)/2
    return f'<g transform="translate({dx},{dy}) scale({s})">{qr_inner}</g>'

def replace_qr_rect_with_vector(svg_fragment: str, qr_data: str) -> str:
    m = re.search(r'(<rect[^>]*id="QR_BOX"[^>]*>)', svg_fragment)
    if not m:
        return svg_fragment
    rect_tag = m.group(1)
    attrs = dict(re.findall(r'(\w+)=["\']([^"\']+)["\']', rect_tag))
    x = float(attrs.get("x", "0"))
    y = float(attrs.get("y", "0"))
    w = float(attrs.get("width", "40"))
    h = float(attrs.get("height", "40"))
    qr_group = make_qr_svg_group(qr_data, x, y, w, h)
    return svg_fragment.replace(rect_tag, qr_group)

# ====================== Render de tarjeta ======================
def render_card(inner_template: str, row: dict, blank: bool = False) -> str:
    if blank or not row:
        return ""

    s = inner_template

    # Textos
    s = replace_text_id_with_path(s, "TXT_CLIENTE",      row.get("CLIENTE", "")) 
    s = replace_text_id_with_path(s, "TXT_CODPRY",       row.get("CODPRY",  "")) 
    s = replace_text_id_with_path(s, "TXT_FECHA",        row.get("FECHA",   "")) 
    s = replace_text_id_with_path(s, "TXT_TIPOSISTEMA",  row.get("TIPO_SISTEMA", ""))  # ← nuevo

    # QR
    num_qr = gen_qr_number(30)
    url_qr = BASE_QR_URL + num_qr
    s = replace_text_id_with_path(s, "NUM_QR", num_qr)
    s = replace_qr_rect_with_vector(s, url_qr)

    s = strip_all_ids(s)
    s = clean_inkscape_blocks(s)
    return s

# ====================== Componer hoja 5x5 ======================
def build_sheet_svg(inner_template: str, rows_or_blanks: list[dict]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W_MM}mm" height="{SHEET_H_MM}mm" viewBox="0 0 {SHEET_W_MM} {SHEET_H_MM}">'
    ]
    total = COLS * ROWS
    for i in range(total):
        r = i // COLS
        c = i % COLS
        x = c * CARD_MM
        y = r * CARD_MM
        row = rows_or_blanks[i]
        is_blank = (not row)

        content = render_card(inner_template, row, blank=is_blank)
        if content:
            parts.append(f'<g transform="translate({x},{y})">{content}</g>')

    parts.append('</svg>')
    return "\n".join(parts)

# ====================== Plantilla mínima por defecto ======================
DEFAULT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="80mm" viewBox="0 0 80 80">
  <style>
    .border { fill: none; stroke: #222; stroke-width: 0.4; }
    .title  { font-family: Arial, Helvetica, sans-serif; font-size: 6.2px; font-weight: 700; text-anchor: middle; }
    .text   { font-family: Arial, Helvetica, sans-serif; font-size: 4.2px; font-weight: 400; text-anchor: middle; }
    .small  { font-family: Arial, Helvetica, sans-serif; font-size: 3.6px; text-anchor: middle; fill: #333; }
  </style>
  <rect x="0.6" y="0.6" width="78.8" height="78.8" rx="3" ry="3" class="border"/>
  <text id="TXT_CODPRY"        class="title" x="40" y="11"><tspan>CODPRY</tspan></text>
  <text id="TXT_CLIENTE"       class="text"  x="40" y="17"><tspan>CLIENTE</tspan></text>
  <text id="TXT_TIPOSISTEMA"   class="text"  x="40" y="22"><tspan>TIPO DE SISTEMA</tspan></text>
  <text id="TXT_FECHA"         class="small" x="40" y="27"><tspan>FECHA</tspan></text>
  <text id="NUM_QR"            class="small" x="40" y="32"><tspan>000000000000000000000000000000</tspan></text>
  <rect id="QR_BOX" x="15" y="35" width="50" height="40" fill="none" stroke="#bbb" stroke-width="0.2" stroke-dasharray="1.2 1.2"/>
</svg>
"""

# ====================== Main ======================
def main() -> int:
    if not CSV_PATH.exists():
        print(f"[ERROR] No se encontró {CSV_PATH.name} en la carpeta del script.", file=sys.stderr)
        return 1

    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)

            rows_all = []
            for row in reader:
                norm = {}
                for k, v in row.items():
                    if k is None:
                        continue
                    k2 = k.strip().lstrip("\ufeff")
                    norm[k2] = (v or "").strip()
                rows_all.append(norm)
    except Exception as e:
        print(f"[ERROR] No se pudo leer {CSV_PATH.name}: {e}", file=sys.stderr)
        return 1

    required = {"CLIENTE", "CODPRY", "FECHA", "TIPO_SISTEMA"}  # ← agregado
    present = set(rows_all[0].keys()) if rows_all else set()
    faltan = required - present
    if faltan:
        print(f"[ERROR] Faltan columnas en el CSV: {', '.join(sorted(faltan))}", file=sys.stderr)
        return 1

    n = min(len(rows_all), 25)
    rows = rows_all[:n]
    rows += [{} for _ in range(25 - n)]

    if TPL_PATH.exists():
        template_svg = TPL_PATH.read_text(encoding="utf-8")
    else:
        template_svg = DEFAULT_TEMPLATE
        try:
            TPL_PATH.write_text(template_svg, encoding="utf-8")
        except Exception:
            pass

    inner = extract_inner_from_template(template_svg)
    final_svg = build_sheet_svg(inner, rows)
    SVG_OUT_PATH.write_text(final_svg, encoding="utf-8")
    print(f"OK -> {SVG_OUT_PATH.name}")
    return 0

if __name__ == "__main__":
    _app = QGuiApplication.instance() or QGuiApplication([])
    rc = main()
    _app.quit()
    sys.exit(rc)
