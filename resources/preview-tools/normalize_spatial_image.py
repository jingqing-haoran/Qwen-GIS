"""Normalize presentation layout of spatial-analysis images for delivery.

Contract:
    python normalize_spatial_image.py --input source.png --output normalized.png
        --min-fill 0.72 --padding 0.025

Emits exactly one JSON line to stdout:
    {"status": "ok", "changed": true|false, "sourceSize": {"width": N, "height": M},
     "outputSize": {"width": N, "height": M}, "contentFill": 0.93}
or
    {"status": "error", "message": "..."}

The tool never overwrites its input and deletes a partial output on error.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def _bootstrap_vendor():
    script_dir = Path(__file__).resolve().parent
    vendor = script_dir / "vendor"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))


_bootstrap_vendor()

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image, ImageChops  # noqa: E402


MIN_FILL_DEFAULT = 0.72
PADDING_DEFAULT = 0.025
TOLERANCE = 8


def corner_median(image):
    """Median RGB color sampled from the four corner patches."""
    patch = 16
    pixels = []
    positions = (
        (0, 0),
        (image.width - patch, 0),
        (0, image.height - patch),
        (image.width - patch, image.height - patch),
    )
    for x, y in positions:
        region = image.crop((x, y, x + patch, y + patch)).convert("RGB")
        data = region.load()
        pixels.extend(
            data[px, py]
            for py in range(region.height)
            for px in range(region.width)
        )
    channels = list(zip(*pixels))
    return tuple(sorted(channel)[len(channel) // 2] for channel in channels)


def difference_mask(image, background, tolerance=TOLERANCE):
    rgb = image.convert("RGB")
    background_image = Image.new("RGB", rgb.size, background)
    diff = ImageChops.difference(rgb, background_image).convert("L")
    return diff.point(lambda value: 255 if value > tolerance else 0)


def content_fill(image, background):
    box = difference_mask(image, background).getbbox()
    if box is None:
        return 0.0
    return ((box[2] - box[0]) * (box[3] - box[1])) / (image.width * image.height)


def padded_box(box, size, padding):
    left, top, right, bottom = box
    pad_x = max(1, int(round((right - left) * padding)))
    pad_y = max(1, int(round((bottom - top) * padding)))
    width, height = size
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def result(changed, source_size, output_size, fill):
    return {
        "status": "ok",
        "changed": changed,
        "sourceSize": {"width": source_size[0], "height": source_size[1]},
        "outputSize": {"width": output_size[0], "height": output_size[1]},
        "contentFill": round(fill, 4),
    }


def normalize_image(source, output, *, min_fill=MIN_FILL_DEFAULT, padding=PADDING_DEFAULT):
    """Crop connected blank margins around the visible map content."""
    source = Path(source)
    output = Path(output)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        background = corner_median(image)
        mask = difference_mask(image, background)
        box = mask.getbbox()
        if box is None:
            raise ValueError("no visible map content")
        fill = ((box[2] - box[0]) * (box[3] - box[1])) / (image.width * image.height)
        if fill >= min_fill:
            shutil.copyfile(source, output)
            return result(False, image.size, image.size, fill)
        crop_box = padded_box(box, image.size, padding)
        cropped = image.crop(crop_box)
        cropped.save(output, format="PNG")
        return result(True, image.size, cropped.size, content_fill(cropped, background))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qwen GIS spatial image layout normalizer")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-fill", type=float, default=MIN_FILL_DEFAULT)
    parser.add_argument("--padding", type=float, default=PADDING_DEFAULT)
    args = parser.parse_args(argv)

    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if source == output:
        print(json.dumps({"status": "error", "message": "Output path must differ from the source input"}, ensure_ascii=False))
        return 2
    try:
        if not source.is_file():
            raise ValueError("Source input is not a file")
        normalized = normalize_image(
            source,
            output,
            min_fill=args.min_fill,
            padding=args.padding,
        )
        print(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001
        if output.exists():
            try:
                output.unlink()
            except OSError:
                pass
        message = str(error) if str(error) else error.__class__.__name__
        print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
