# -*- coding: utf-8 -*-

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from flask import Flask, request, jsonify
from genQRSVG import generate_svg_bundle_from_rows

BASE_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("SVG_API_KEY", "")

DEFAULT_TEMPLATE = "anticaidas"
TEMPLATES = {
    "anticaidas": {
        "file": "template-anticaidas.svg",
        "base_qr_url": os.getenv(
            "BASE_QR_URL_ANTICAIDAS",
            "https://www.anticaidas.cl/consultaRegistroQR.php?LlaveQR=",
        ),
    },
    "siesa": {
        "file": "template-siesa.svg",
        "base_qr_url": os.getenv(
            "BASE_QR_URL_SIESA",
            "https://www.siesa.cl/consultaRegistroQR.php?LlaveQR=",
        ),
    },
}

application = Flask(__name__)


def resolve_template_key(value):
    """
    Acepta 'siesa', 'SIESA', 'template-siesa' o 'template-siesa.svg'.
    Devuelve la clave valida, o None si el template no existe en el registro.
    Si no viene nada, usa el template por defecto.
    """
    key = ("" if value is None else str(value)).strip().lower()
    if not key:
        return DEFAULT_TEMPLATE
    if key.endswith(".svg"):
        key = key[:-4]
    if key.startswith("template-"):
        key = key[len("template-"):]
    return key if key in TEMPLATES else None


def template_path(key):
    return BASE_DIR / TEMPLATES[key]["file"]


@application.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "message": "API SVG funcionando",
            "default_template": DEFAULT_TEMPLATE,
            "templates": {
                key: {
                    "file": cfg["file"],
                    "exists": template_path(key).exists(),
                    "base_qr_url": cfg["base_qr_url"],
                }
                for key, cfg in TEMPLATES.items()
            },
        })

    try:
        if API_KEY:
            received_key = request.headers.get("X-API-Key", "")
            if received_key != API_KEY:
                return jsonify({
                    "ok": False,
                    "error": "No autorizado"
                }), 401

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "ok": False,
                "error": "No se recibio JSON valido"
            }), 400

        rows = data.get("rows")

        template_key = resolve_template_key(data.get("template"))
        if template_key is None:
            return jsonify({
                "ok": False,
                "error": "Template no valido. Opciones: " + ", ".join(sorted(TEMPLATES)),
            }), 400

        svg_path = template_path(template_key)
        if not svg_path.exists():
            return jsonify({
                "ok": False,
                "error": f"No existe {svg_path.name} en el servidor"
            }), 500

        template_svg = svg_path.read_text(encoding="utf-8")
        sheet_filename = f"tarjetas_{template_key}_5x5_vector.svg"

        result = generate_svg_bundle_from_rows(
            rows,
            template_svg,
            base_qr_url=TEMPLATES[template_key]["base_qr_url"],
            sheet_filename=sheet_filename,
        )

        return jsonify({
            "ok": True,
            "template": template_key,
            "filename": sheet_filename,
            **result,
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
