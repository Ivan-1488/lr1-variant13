"""Run a deterministic non-HTTP example of the variant 13 image algorithm."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from image_processing import build_result

PROJECT_ROOT = Path(__file__).resolve().parents[1]
source_path = PROJECT_ROOT / "examples" / "demo_input.png"
output_path = PROJECT_ROOT / "examples" / "generated"

with Image.open(source_path) as image:
    result = build_result(image.convert("RGB"), output_path, source_path.name)

print(f"Исходное изображение: {result['width']} × {result['height']}")
for part in result["parts"]:
    print(f"{part['label']}: {part['width']} × {part['height']} -> {part['image']}")
print(f"Гистограмм создано: {1 + len(result['parts'])}")
