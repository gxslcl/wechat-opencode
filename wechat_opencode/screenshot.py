"""Screenshot and screen OCR — capture desktop, extract text via OCR."""

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    """Lazy-init EasyOCR reader (only loaded on first use)."""
    global _reader
    if _reader is None:
        import easyocr
        logger.info("Loading EasyOCR reader (first use)...")
        _reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        logger.info("EasyOCR reader ready")
    return _reader


def capture_desktop(output_path: Optional[str] = None) -> Optional[str]:
    """Capture the full desktop screen using PIL ImageGrab."""
    path = output_path or os.path.join(tempfile.gettempdir(), "screenshot.png")

    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        img.save(path, "PNG")
        size = os.path.getsize(path)
        logger.info("Screenshot: %s (%d bytes, %dx%d)", path, size, *img.size)
        return path
    except Exception as e:
        logger.error("Screenshot failed: %s", e)
        return None


def ocr_screen(image_path: Optional[str] = None) -> str:
    """Take a screenshot (or use existing image) and extract text via OCR.

    Args:
        image_path: Path to existing image. If None, takes a new screenshot.

    Returns:
        Extracted text from the image, or empty string on failure.
    """
    path = image_path or capture_desktop()
    if not path:
        return ""

    try:
        reader = _get_reader()
        results = reader.readtext(path, detail=1, paragraph=False)

        if not results:
            return "(屏幕上未检测到文字)"

        # Group by approximate y-coordinate (rows)
        rows: list[list[tuple[str, float]]] = []
        current_row: list[tuple[str, float]] = []
        last_y = -100

        for bbox, text, conf in results:
            y_center = (bbox[0][1] + bbox[2][1]) / 2
            if current_row and abs(y_center - last_y) > 30:
                rows.append(current_row)
                current_row = []
            current_row.append((text, conf))
            last_y = y_center

        if current_row:
            rows.append(current_row)

        # Format output
        lines: list[str] = []
        for row in rows:
            row_text = " ".join(t for t, _ in row)
            lines.append(row_text)

        return "\n".join(lines)

    except Exception as e:
        logger.error("OCR failed: %s", e)
        return f"(OCR 识别失败: {e})"


def describe_screen(image_path: Optional[str] = None) -> str:
    """Take a screenshot and return OCR text with metadata.

    Returns a formatted string suitable for LLM consumption.
    """
    from PIL import Image

    path = image_path or capture_desktop()
    if not path:
        return "截图失败"

    try:
        img = Image.open(path)
        w, h = img.size
        text = ocr_screen(path)
        return (
            f"[屏幕信息]\n"
            f"分辨率: {w}x{h}\n"
            f"识别文字:\n{text}"
        )
    except Exception as e:
        return f"截图分析失败: {e}"
