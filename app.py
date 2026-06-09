# -*- coding: utf-8 -*-

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from flask import Flask, request, jsonify
from genQRSVG import generate_svg_bundle_from_rows

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "template-anticaidas.svg"
API_KEY = os.getenv("SVG_API_KEY", "")

application = Flask(__name__)


@application.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "message": "API SVG funcionando",
            "template_exists": TEMPLATE_PATH.exists(),
            "template_file": TEMPLATE_PATH.name
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

        if not TEMPLATE_PATH.exists():
            return jsonify({
                "ok": False,
                "error": "No existe template-anticaidas.svg en el servidor"
            }), 500

        template_svg = TEMPLATE_PATH.read_text(encoding="utf-8")

        result = generate_svg_bundle_from_rows(rows, template_svg)

        return jsonify({
            "ok": True,
            "filename": "tarjetas_anticaidas_5x5_vector.svg",
            **result
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500