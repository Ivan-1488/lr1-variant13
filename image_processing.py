"""Image processing functions for Laboratory Work 1, variant 13."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


def cleanup_old_results(results_root: Path, retention_seconds: int) -> None:
    """Remove generated result folders older than the configured retention period."""
    now = time.time()
    if not results_root.exists():
        return
    for child in results_root.iterdir():
        if child.is_dir() and now - child.stat().st_mtime > retention_seconds:
            shutil.rmtree(child, ignore_errors=True)


def split_image(source: Image.Image) -> list[tuple[str, Image.Image]]:
    """Split an image into four non-overlapping quadrants without losing odd edge pixels."""
    width, height = source.size
    if width < 2 or height < 2:
        raise ValueError("Для разделения изображение должно быть не меньше 2 × 2 пикселей.")
    mid_x, mid_y = width // 2, height // 2
    return [
        ("Верхняя левая часть", source.crop((0, 0, mid_x, mid_y))),
        ("Верхняя правая часть", source.crop((mid_x, 0, width, mid_y))),
        ("Нижняя левая часть", source.crop((0, mid_y, mid_x, height))),
        ("Нижняя правая часть", source.crop((mid_x, mid_y, width, height))),
    ]


def save_color_histogram(image: Image.Image, output_path: Path, title: str) -> None:
    """Save an RGB histogram with 256 intensity bins for each color channel."""
    import numpy as np

    pixels = np.asarray(image.convert("RGB"))
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=130)
    channel_specs = ((0, "Красный", "#d94841"), (1, "Зелёный", "#269b58"), (2, "Синий", "#3678c8"))
    for index, label, color in channel_specs:
        counts, bins = np.histogram(pixels[:, :, index], bins=256, range=(0, 256))
        ax.plot(bins[:-1], counts, color=color, linewidth=1.15, label=label)
    ax.set_title(title)
    ax.set_xlabel("Интенсивность канала (0–255)")
    ax.set_ylabel("Количество пикселей")
    ax.set_xlim(0, 255)
    ax.grid(alpha=0.2)
    ax.legend(loc="upper right", frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(output_path, format="png", bbox_inches="tight")
    plt.close(fig)



WATERMARK_POSITIONS = {"top-left", "top-right", "center", "bottom-left", "bottom-right"}


def add_watermark(source: Image.Image, *, kind: str = "none", text: str = "",
                  watermark_image: Image.Image | None = None,
                  opacity: int = 50, position: str = "bottom-right") -> Image.Image:
    """Return a new RGB image with an optional semitransparent watermark."""
    if kind not in {"none", "text", "image"}:
        raise ValueError("Неизвестный тип водяного знака.")
    if not 0 <= opacity <= 100:
        raise ValueError("Прозрачность должна находиться в диапазоне от 0 до 100.")
    if position not in WATERMARK_POSITIONS:
        raise ValueError("Неизвестное положение водяного знака.")
    base = source.convert("RGBA")
    if kind == "none":
        return base.convert("RGB")
    if kind == "text":
        if not text.strip() or len(text) > 100:
            raise ValueError("Текст водяного знака должен содержать от 1 до 100 символов.")
        font_size = max(12, min(base.width, base.height) // 14)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
        temp_draw = ImageDraw.Draw(base)
        bbox = temp_draw.textbbox((0, 0), text, font=font, stroke_width=1)
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        mark = Image.new("RGBA", (width + 8, height + 8), (0, 0, 0, 0))
        drawer = ImageDraw.Draw(mark)
        alpha = round(255 * opacity / 100)
        drawer.text((4 - bbox[0], 4 - bbox[1]), text, font=font,
                    fill=(255, 255, 255, alpha), stroke_width=1,
                    stroke_fill=(0, 0, 0, alpha))
    else:
        if watermark_image is None:
            raise ValueError("Не загружено изображение водяного знака.")
        mark = watermark_image.convert("RGBA")
        target_width = min(mark.width, max(1, base.width // 4))
        target_height = min(mark.height, max(1, base.height // 4))
        mark.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        mark.putalpha(mark.getchannel("A").point(lambda a: round(a * opacity / 100)))
    margin = max(2, min(base.width, base.height) // 40)
    x = {"top-left": margin, "bottom-left": margin,
         "top-right": base.width - mark.width - margin,
         "bottom-right": base.width - mark.width - margin,
         "center": (base.width - mark.width) // 2}[position]
    y = {"top-left": margin, "top-right": margin,
         "bottom-left": base.height - mark.height - margin,
         "bottom-right": base.height - mark.height - margin,
         "center": (base.height - mark.height) // 2}[position]
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay.paste(mark, (max(0, x), max(0, y)))
    return Image.alpha_composite(base, overlay).convert("RGB")

def build_result(source: Image.Image, result_dir: Path, original_name: str, *,
                 watermark_kind: str = "none", watermark_text: str = "",
                 watermark_image: Image.Image | None = None,
                 watermark_opacity: int = 50, watermark_position: str = "bottom-right") -> dict:
    """Save the source image, its four quadrants and five RGB histograms."""
    result_dir.mkdir(parents=True, exist_ok=True)
    original = source.convert("RGB")
    original.save(result_dir / "original_unmarked.png", format="PNG")
    source = add_watermark(original, kind=watermark_kind, text=watermark_text,
                           watermark_image=watermark_image, opacity=watermark_opacity,
                           position=watermark_position)
    source_path = result_dir / "source.png"
    source.save(source_path, format="PNG", optimize=True)
    source_hist = result_dir / "hist_source.png"
    save_color_histogram(source, source_hist, "Распределение цветов исходного изображения")

    parts = []
    for index, (label, part_image) in enumerate(split_image(source), start=1):
        image_name = f"part_{index}.png"
        histogram_name = f"hist_part_{index}.png"
        part_image.save(result_dir / image_name, format="PNG", optimize=True)
        save_color_histogram(part_image, result_dir / histogram_name, f"Распределение цветов: {label.lower()}")
        parts.append({
            "label": label,
            "image": image_name,
            "histogram": histogram_name,
            "width": part_image.width,
            "height": part_image.height,
        })

    return {
        "original_name": original_name,
        "source": "source.png",
        "original_unmarked": "original_unmarked.png",
        "watermark_applied": watermark_kind != "none",
        "source_histogram": "hist_source.png",
        "width": source.width,
        "height": source.height,
        "parts": parts,
    }
