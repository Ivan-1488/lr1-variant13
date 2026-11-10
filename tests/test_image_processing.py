from pathlib import Path

import pytest
from PIL import Image

from image_processing import build_result, save_color_histogram, split_image


def test_split_preserves_every_pixel_and_expected_sizes():
    source = Image.new("RGB", (5, 7), "red")
    parts = split_image(source)
    assert [part.size for _, part in parts] == [(2, 3), (3, 3), (2, 4), (3, 4)]
    assert sum(part.width * part.height for _, part in parts) == 5 * 7


def test_split_rejects_too_small_image():
    with pytest.raises(ValueError):
        split_image(Image.new("RGB", (1, 3)))


def test_even_image_splits_into_equal_quadrants():
    parts = split_image(Image.new("RGB", (8, 6), "blue"))
    assert [part.size for _, part in parts] == [(4, 3)] * 4


def test_build_result_creates_four_images_and_five_histograms(tmp_path: Path):
    source = Image.new("RGB", (7, 5), "navy")
    result = build_result(source, tmp_path / "result", "input.png")
    files = {p.name for p in (tmp_path / "result").iterdir()}
    assert len(result["parts"]) == 4
    assert {"source.png", "hist_source.png", *(f"part_{i}.png" for i in range(1, 5)),
            *(f"hist_part_{i}.png" for i in range(1, 5))} <= files
    assert sum(p.stat().st_size for p in (tmp_path / "result").glob("hist_*.png")) > 0
    assert result["width"] == 7 and result["height"] == 5


def test_histogram_is_written_as_png(tmp_path: Path):
    path = tmp_path / "histogram.png"
    save_color_histogram(Image.new("RGB", (10, 10), (10, 20, 30)), path, "test")
    with Image.open(path) as result:
        assert result.format == "PNG"
        assert result.width > 0 and result.height > 0

from image_processing import add_watermark


def test_text_watermark_changes_pixels_but_not_original():
    original = Image.new("RGB", (320, 200), (20, 40, 60))
    untouched = original.copy()
    marked = add_watermark(original, kind="text", text="TUSUR", opacity=90, position="center")
    assert marked.size == original.size
    assert original.tobytes() == untouched.tobytes()
    assert marked.tobytes() != original.tobytes()


def test_image_watermark_and_opacity():
    original = Image.new("RGB", (100, 80), "navy")
    logo = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    invisible = add_watermark(original, kind="image", watermark_image=logo, opacity=0)
    visible = add_watermark(original, kind="image", watermark_image=logo,
                            opacity=100, position="top-left")
    assert invisible.tobytes() == original.tobytes()
    assert visible.tobytes() != original.tobytes()


def test_invalid_watermark_options():
    image = Image.new("RGB", (80, 80), "white")
    with pytest.raises(ValueError):
        add_watermark(image, kind="text", text="")
    with pytest.raises(ValueError):
        add_watermark(image, kind="image")
    with pytest.raises(ValueError):
        add_watermark(image, kind="text", text="A", opacity=101)
    with pytest.raises(ValueError):
        add_watermark(image, kind="text", text="A", position="unknown")


def test_build_result_with_watermark_preserves_original(tmp_path):
    image = Image.new("RGB", (160, 120), (12, 34, 56))
    output = tmp_path / "marked"
    data = build_result(image, output, "input.png", watermark_kind="text",
                        watermark_text="TEST", watermark_opacity=100,
                        watermark_position="center")
    assert data["watermark_applied"] is True
    with Image.open(output / "original_unmarked.png") as original:
        assert original.getpixel((80, 60)) == (12, 34, 56)
    with Image.open(output / "source.png") as marked:
        assert marked.tobytes() != image.tobytes()
    assert len(list(output.glob("hist_*.png"))) == 5
