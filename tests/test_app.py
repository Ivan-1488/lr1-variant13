from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("flask")
pytest.importorskip("flask_wtf")

from app import create_app
from image_processing import split_image


@pytest.fixture()
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret",
        "RESULTS_DIR": tmp_path / "results",
    })
    return app.test_client(), tmp_path / "results"


def make_png(width=5, height=7):
    image = Image.new("RGB", (width, height))
    for y in range(height):
        for x in range(width):
            image.putpixel((x, y), (x * 25, y * 20, (x + y) * 15))
    data = BytesIO()
    image.save(data, format="PNG")
    data.seek(0)
    return data


def test_split_preserves_every_pixel_and_expected_sizes():
    source = Image.new("RGB", (5, 7), "red")
    parts = split_image(source)
    assert [p.size for _, p in parts] == [(2, 3), (3, 3), (2, 4), (3, 4)]
    assert sum(p.width * p.height for _, p in parts) == 5 * 7


def test_split_rejects_too_small_image():
    with pytest.raises(ValueError):
        split_image(Image.new("RGB", (1, 3)))


def test_index_shows_captcha(client):
    test_client, _ = client
    response = test_client.get("/")
    assert response.status_code == 200
    assert b"\xd0\x90\xd0\xbd\xd0\xb0\xd0\xbb\xd0\xb8\xd0\xb7" in response.data


def test_process_creates_four_parts_and_five_histograms(client):
    test_client, results_root = client
    with test_client.session_transaction() as session:
        session["captcha_answer"] = 7
        session["form_started_at"] = 0
    response = test_client.post("/process", data={
        "captcha_answer": "7",
        "image": (make_png(), "test.png"),
    }, content_type="multipart/form-data")
    assert response.status_code == 200
    folders = list(results_root.iterdir())
    assert len(folders) == 1
    output_files = {p.name for p in folders[0].iterdir()}
    assert {"source.png", "hist_source.png", "part_1.png", "part_2.png", "part_3.png", "part_4.png",
            "hist_part_1.png", "hist_part_2.png", "hist_part_3.png", "hist_part_4.png"} <= output_files
    assert "Верхняя левая часть".encode() in response.data


def test_captcha_failure_does_not_process_image(client):
    test_client, results_root = client
    with test_client.session_transaction() as session:
        session["captcha_answer"] = 7
        session["form_started_at"] = 0
    response = test_client.post("/process", data={"captcha_answer": "8"}, follow_redirects=True)
    assert response.status_code == 200
    assert not list(results_root.iterdir())


def test_invalid_extension_is_rejected(client):
    test_client, results_root = client
    with test_client.session_transaction() as session:
        session["captcha_answer"] = 7
        session["form_started_at"] = 0
    response = test_client.post("/process", data={
        "captcha_answer": "7", "image": (BytesIO(b"not image"), "bad.exe")
    }, content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200
    assert not list(results_root.iterdir())


def test_verify_hash_matches_normalized_response(client):
    import hashlib
    import re
    from app import VERIFY_TOKEN, normalize_html
    test_client, _ = client
    response = test_client.get("/verify")
    assert response.status_code == 200
    assert VERIFY_TOKEN.encode("utf-8") in response.data
    assert re.fullmatch(r"[0-9a-f]{64}", response.headers["X-Verify-Hash"])
    expected = hashlib.sha256(normalize_html(response.get_data(as_text=True)).encode("utf-8")).hexdigest()
    assert expected == response.headers["X-Verify-Hash"]


def test_text_watermark_via_http(client):
    test_client, results_root = client
    with test_client.session_transaction() as sess:
        sess["captcha_answer"] = 7
        sess["form_started_at"] = 0
    response = test_client.post("/process", data={
        "captcha_answer": "7", "image": (make_png(200, 120), "test.png"),
        "watermark_type": "text", "watermark_text": "TUSUR",
        "watermark_opacity": "100", "watermark_position": "center",
    }, content_type="multipart/form-data")
    assert response.status_code == 200
    out = next(results_root.iterdir())
    with Image.open(out / "source.png") as marked, Image.open(out / "original_unmarked.png") as unmarked:
        assert marked.tobytes() != unmarked.tobytes()


def test_invalid_watermark_rejected(client):
    test_client, results_root = client
    with test_client.session_transaction() as sess:
        sess["captcha_answer"] = 7
        sess["form_started_at"] = 0
    response = test_client.post("/process", data={
        "captcha_answer": "7", "image": (make_png(), "test.png"),
        "watermark_type": "text", "watermark_text": "",
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    assert not list(results_root.iterdir())
