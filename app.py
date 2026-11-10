from __future__ import annotations

import os
import hashlib
import re
from datetime import date
from io import BytesIO
import secrets
import time
import uuid
from pathlib import Path

from flask import Flask, flash, make_response, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect
from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename

from image_processing import WATERMARK_POSITIONS, build_result, cleanup_old_results

VERIFY_TOKEN = "TUSUR-SHAPKIN-20261108-012952EA"


def normalize_html(html: str) -> str:
    """Normalize lines and whitespace as required by the instructor."""
    lines = [line.strip() for line in html.split("\n")]
    lines = [line for line in lines if line]
    lines = [re.sub(r"\s+", " ", line) for line in lines]
    return "\n".join(lines)


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "static" / "results"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
ImageFile.LOAD_TRUNCATED_IMAGES = False


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-me"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        WTF_CSRF_ENABLED=True,
        RESULT_RETENTION_SECONDS=24 * 60 * 60,
    )
    if test_config:
        app.config.update(test_config)

    CSRFProtect(app)
    results_root = Path(app.config.get("RESULTS_DIR", RESULTS_DIR))
    results_root.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index():
        a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
        from flask import session
        session["captcha_answer"] = a + b
        session["form_started_at"] = time.time()
        return render_template("index.html", captcha_question=f"{a} + {b}")

    @app.post("/process")
    def process():
        from flask import session
        # Honeypot: ordinary users never see or fill this field.
        if request.form.get("website", "").strip():
            flash("Запрос отклонён.", "error")
            return redirect(url_for("index"))

        try:
            expected = int(session.get("captcha_answer", -10_000))
            supplied = int(request.form.get("captcha_answer", ""))
        except (TypeError, ValueError):
            expected, supplied = -10_000, -20_000
        if supplied != expected:
            flash("Проверка от роботов не пройдена. Решите пример ещё раз.", "error")
            return redirect(url_for("index"))

        started = float(session.get("form_started_at", 0))
        if started and time.time() - started < 1.0:
            flash("Форма отправлена слишком быстро. Повторите попытку.", "error")
            return redirect(url_for("index"))

        uploaded = request.files.get("image")
        if uploaded is None or not uploaded.filename:
            flash("Выберите изображение.", "error")
            return redirect(url_for("index"))

        filename = secure_filename(uploaded.filename)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in ALLOWED_EXTENSIONS:
            flash("Поддерживаются PNG, JPG, JPEG, WEBP и BMP.", "error")
            return redirect(url_for("index"))

        raw = uploaded.read(MAX_UPLOAD_BYTES + 1)
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            flash("Файл пустой или превышает ограничение 8 Мбайт.", "error")
            return redirect(url_for("index"))

        try:
            with Image.open(BytesIO(raw)) as probe:
                if probe.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                    raise ValueError("Недопустимый формат изображения.")
                if probe.width < 2 or probe.height < 2:
                    raise ValueError("Минимальный размер изображения - 2 × 2 пикселя.")
                if probe.width * probe.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Изображение слишком большое по количеству пикселей.")
                probe.verify()
            with Image.open(BytesIO(raw)) as source_file:
                source = ImageOps.exif_transpose(source_file).convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
            flash(f"Не удалось обработать изображение: {exc}", "error")
            return redirect(url_for("index"))

        watermark_kind = request.form.get("watermark_type", "none")
        watermark_text = request.form.get("watermark_text", "")
        watermark_position = request.form.get("watermark_position", "bottom-right")
        try:
            watermark_opacity = int(request.form.get("watermark_opacity", "50"))
            if watermark_kind not in {"none", "text", "image"}:
                raise ValueError("Недопустимый тип водяного знака.")
            if watermark_position not in WATERMARK_POSITIONS or not 0 <= watermark_opacity <= 100:
                raise ValueError("Недопустимые параметры водяного знака.")
            if watermark_kind == "text" and (not watermark_text.strip() or len(watermark_text) > 100):
                raise ValueError("Введите текст водяного знака длиной до 100 символов.")
            watermark_image = None
            if watermark_kind == "image":
                mark_upload = request.files.get("watermark_image")
                if mark_upload is None or not mark_upload.filename:
                    raise ValueError("Выберите изображение водяного знака.")
                mark_data = mark_upload.read(1024 * 1024 + 1)
                if not mark_data or len(mark_data) > 1024 * 1024:
                    raise ValueError("Файл водяного знака должен быть не более 1 МиБ.")
                with Image.open(BytesIO(mark_data)) as mark_probe:
                    if mark_probe.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                        raise ValueError("Недопустимый формат водяного знака.")
                    if mark_probe.width * mark_probe.height > 2_000_000:
                        raise ValueError("Изображение водяного знака слишком большое.")
                    mark_probe.verify()
                with Image.open(BytesIO(mark_data)) as mark_file:
                    watermark_image = ImageOps.exif_transpose(mark_file).convert("RGBA")
        except (TypeError, ValueError, OSError, UnidentifiedImageError,
                Image.DecompressionBombError) as exc:
            flash(f"Ошибка водяного знака: {exc}", "error")
            return redirect(url_for("index"))

        cleanup_old_results(results_root, app.config["RESULT_RETENTION_SECONDS"])
        result_id = uuid.uuid4().hex
        result_dir = results_root / result_id
        result_dir.mkdir(parents=True, exist_ok=False)
        try:
            result = build_result(source, result_dir, filename or "source",
                                  watermark_kind=watermark_kind, watermark_text=watermark_text,
                                  watermark_image=watermark_image, watermark_opacity=watermark_opacity,
                                  watermark_position=watermark_position)
        except Exception:
            # Do not leave partial artifacts after an unexpected processing error.
            for child in result_dir.glob("*"):
                child.unlink(missing_ok=True)
            result_dir.rmdir()
            app.logger.exception("Image processing failed")
            flash("Во время обработки изображения произошла ошибка.", "error")
            return redirect(url_for("index"))

        session.pop("captcha_answer", None)
        session.pop("form_started_at", None)
        return render_template("result.html", result=result, result_id=result_id)

    @app.get("/verify")
    def verify():
        today = date.today().isoformat()
        html = f"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Verification</title></head>
<body>
<h1>Верификация</h1>
<p>Token: {VERIFY_TOKEN}</p>
<p>Date: {today}</p>
</body>
</html>"""
        normalized = normalize_html(html)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        response = make_response(html)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["X-Verify-Hash"] = digest
        return response

    @app.errorhandler(413)
    def too_large(_error):
        flash("Файл превышает ограничение 8 Мбайт.", "error")
        return redirect(url_for("index")), 303

    return app



app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
