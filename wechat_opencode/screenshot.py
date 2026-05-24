"""Screenshot utility — capture full desktop via PIL ImageGrab."""

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


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


def capture_webpage(url: str, output_path: Optional[str] = None) -> Optional[str]:
    """Capture a webpage screenshot via Playwright subprocess."""
    path = output_path or os.path.join(tempfile.gettempdir(), "webpage.png")
    import subprocess, sys

    code = f'''import os, sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={{"width": 1920, "height": 1080}})
        pg.goto("{url}", wait_until="networkidle", timeout=30000)
        pg.screenshot(path=r"{path}", full_page=True)
        b.close()
    print("OK: " + str(os.path.getsize(r"{path}")))
except Exception as e:
    print("ERROR: " + str(e))
    sys.exit(1)
'''

    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        output = result.stdout.strip()
        if output.startswith("OK:") and os.path.exists(path):
            return path
        logger.error("Webpage screenshot failed: %s", output or "unknown")
        return None
    except Exception as e:
        logger.error("Webpage screenshot error: %s", e)
        return None


    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if output.startswith("OK:") and os.path.exists(path):
            logger.info("Screenshot: %s (%s)", path, output[3:])
            return path
        logger.error("Screenshot failed: %s", output or result.stderr or "unknown")
        return None
    except Exception as e:
        logger.error("Screenshot error: %s", e)
        return None
