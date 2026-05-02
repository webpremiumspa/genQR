#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask endpoint for PythonAnywhere.

Power Automate sends Excel rows to /generate-svg. The SVG template is read from
the server project folder by default, so the flow does not need to send the
template on every request.
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from genQRSVG import generate_svg_from_rows


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = Path(
    os.getenv("TEMPLATE_SVG_PATH", str(BASE_DIR / "template-anticaidas.svg"))
)
DEFAULT_RESPONSE_MODE = os.getenv("SVG_RESPONSE_MODE", "json").lower()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))


def _api_key_error():
    expected = os.getenv("SVG_API_KEY", "").strip()
    if not expected:
        return None

    received = request.headers.get("X-API-Key", "").strip()
    if not hmac.compare_digest(received, expected):
        return jsonify({"error": "API key invalida o ausente."}), 401
    return None


def _load_template_svg(payload: dict[str, Any]) -> str:
    inline_template = payload.get("template_svg")
    if isinstance(inline_template, str) and inline_template.strip():
        return inline_template

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"No se encontro la plantilla SVG en: {TEMPLATE_PATH}"
        )
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if rows is None:
        rows = payload.get("value")

    body = payload.get("body")
    if rows is None and isinstance(body, dict):
        rows = body.get("value")

    if rows is None:
        raise ValueError("El payload debe incluir 'rows' con las filas de Excel.")
    if not isinstance(rows, list):
        raise ValueError("'rows' debe ser una lista.")
    return rows


def _default_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"tarjetas_anticaidas_5x5_vector_{stamp}.svg"


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "template_path": str(TEMPLATE_PATH),
            "template_exists": TEMPLATE_PATH.exists(),
        }
    )


@app.post("/generate-svg")
def generate_svg():
    auth_error = _api_key_error()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    try:
        rows = _extract_rows(payload)
        template_svg = _load_template_svg(payload)
        result = generate_svg_from_rows(rows=rows, template_svg=template_svg)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    filename = str(payload.get("filename") or _default_filename())
    response_mode = str(payload.get("response_mode") or DEFAULT_RESPONSE_MODE).lower()

    if response_mode == "svg":
        return Response(
            result["svg"],
            mimetype="image/svg+xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    result["filename"] = filename
    return jsonify(result)
