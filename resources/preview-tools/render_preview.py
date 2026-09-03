"""Deterministic preview thumbnail renderer for Qwen GIS.

Contract:
    python render_preview.py --input <absolute> --output <absolute.png> --max-side 1600

Emits exactly one JSON line to stdout:
    {"status": "ok", "kind": "image|tiff|pdf", "width": N, "height": M, "pageCount": K}
or
    {"status": "error", "message": "..."}

The renderer never modifies the source file.
"""

import argparse
import json
import os
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

from PIL import Image, ImageOps  # noqa: E402


MAX_DECODED_PIXELS = 80_000_000
MAX_SOURCE_BYTES = 256 * 1024 * 1024


def _result(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _percentile_bins(histogram, low=1.0, high=99.0):
    total = sum(histogram)
    if total == 0:
        return 0, 255
    target_lo = total * low / 100.0
    target_hi = total * high / 100.0
    cumulative = 0
    lower = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= target_lo:
            lower = value
            break
    cumulative = 0
    upper = len(histogram) - 1
    for value in range(len(histogram) - 1, -1, -1):
        cumulative += histogram[value]
        if cumulative >= target_hi:
            upper = value
            break
    return lower, upper


def _stretch_preview(image, max_side):
    working = _resize_longest(image, max_side)
    converted = working.convert("I")
    lower, upper = _percentile_bins(converted.histogram())
    span = upper - lower
    if span <= 0:
        span = 1
    scaled = Image.new("L", converted.size)
    scaled.putdata([
        max(0, min(255, ((value >> 8) - lower) * 255 // span))
        for value in converted.getdata()
    ])
    return scaled, lower, span


def _nodata_tag(image):
    try:
        tag = image.tag_v2.get(42113)
        if tag is None:
            return None
        raw = str(tag).strip().rstrip("*")
        return float(raw)
    except Exception:
        return None


def _resize_longest(image, max_side):
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    return image.resize((max(1, int(round(width * scale))), max(1, int(round(height * scale)))), Image.LANCZOS)


def _render_image(source, output, max_side):
    with Image.open(source) as opened:
        if opened.width * opened.height > MAX_DECODED_PIXELS:
            raise ValueError("Decoded image exceeds the 80 megapixel preview limit")
        if opened.format and opened.format.upper() == "TIFF":
            kind = "tiff"
            nodata = _nodata_tag(opened)
            resized, lower, span = _stretch_preview(opened, max_side)
            if nodata is not None and span > 0:
                scaled_nodata = int(max(0, min(255, ((int(nodata) >> 8) - lower) * 255 // span)))
                alpha = resized.point(lambda value: 0 if int(value) == scaled_nodata else 255, mode="L")
                resized = resized.convert("RGBA")
                resized.putalpha(alpha)
        else:
            kind = "image"
            resized = _resize_longest(opened.convert("RGB"), max_side)
    resized.save(output, format="PNG")
    width, height = resized.size
    return kind, width, height


def _render_pdf(source, output, max_side):
    import pypdfium2  # noqa: WPS433

    pdf = pypdfium2.PdfDocument(str(source))
    page_count = len(pdf)
    if page_count == 0:
        raise ValueError("PDF has no pages")
    page = pdf[0]
    width, height = page.get_size()
    longest = max(width, height)
    scale = max_side / longest if longest > max_side else 1.0
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil().convert("RGB")
    width, height = image.size
    image.save(output, format="PNG")
    pdf.close()
    return "pdf", width, height, page_count


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qwen GIS preview renderer")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-side", type=int, default=1600)
    args = parser.parse_args(argv)

    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if source == output:
        _result({"status": "error", "message": "Output path must differ from the source input"})
        return 2
    try:
        if not source.is_file():
            _result({"status": "error", "message": "Source input is not a file"})
            return 2
        size = source.stat().st_size
        if size <= 0:
            _result({"status": "error", "message": "Source input is empty"})
            return 2
        if size > MAX_SOURCE_BYTES:
            _result({"status": "error", "message": "Source input exceeds the 256 MiB preview limit"})
            return 2

        suffix = source.suffix.lower()
        if suffix == ".pdf":
            kind, width, height, page_count = _render_pdf(source, output, args.max_side)
            _result({"status": "ok", "kind": kind, "width": width, "height": height, "pageCount": page_count})
            return 0
        if suffix == ".svg":
            _result({"status": "error", "message": "SVG previews are sanitized and served by the main process"})
            return 2
        kind, width, height = _render_image(source, output, args.max_side)
        _result({"status": "ok", "kind": kind, "width": width, "height": height, "pageCount": 1})
        return 0
    except Exception as error:  # noqa: BLE001
        message = str(error) if str(error) else error.__class__.__name__
        _result({"status": "error", "message": message})
        return 1


if __name__ == "__main__":
    sys.exit(main())
