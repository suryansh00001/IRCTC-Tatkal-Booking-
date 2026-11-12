# utils/captcha_solver.py — Solves IRCTC CAPTCHA via RapidOCR, 2Captcha API, or local OCR

import os
import time
import base64
import requests
import numpy as np
from io import BytesIO
from PIL import Image, ImageFilter, ImageEnhance
from utils.logger import get_logger
from config.settings import CAPTCHA_API_KEY, USE_LOCAL_OCR

log = get_logger("CaptchaSolver")

try:
    from rapidocr_onnxruntime import RapidOCR
    RAPID_OCR = RapidOCR()
    RAPID_OCR_AVAILABLE = True
    log.info("RapidOCR initialized successfully.")
except Exception as e:
    RAPID_OCR_AVAILABLE = False
    log.warning(f"RapidOCR not available: {e}")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


class CaptchaSolver:
    """
    Multi-strategy CAPTCHA solver:
    1. RapidOCR (Local ONNX AI model, fast, free, high accuracy)
    2. 2Captcha API (if configured in .env)
    3. Tesseract OCR (fallback)
    4. Safe manual / browser entry
    """

    def __init__(self, api_key: str = CAPTCHA_API_KEY):
        self.api_key = api_key
        self.use_local = USE_LOCAL_OCR or not api_key
        mode_name = "2Captcha API" if (not self.use_local and self.api_key) else ("RapidOCR AI" if RAPID_OCR_AVAILABLE else "Tesseract")
        log.info(f"CaptchaSolver initialized — mode: {mode_name}")

    def solve(self, image_source) -> str:
        """Solve CAPTCHA and return clean alphanumeric text."""
        img = self._load_image(image_source)

        if not self.use_local and self.api_key:
            result = self._solve_2captcha(img)
        elif RAPID_OCR_AVAILABLE:
            result = self._solve_rapidocr(img)
        elif TESSERACT_AVAILABLE:
            result = self._solve_ocr(img)
        else:
            result = ""

        import re
        result = re.sub(r'[^a-zA-Z0-9]', '', result).strip()
        log.info(f"CAPTCHA text resolved: '{result}'")
        return result

    def solve_from_element(self, driver, captcha_element) -> str:
        """Solve CAPTCHA directly from a Selenium WebElement (screenshot)."""
        try:
            png = captcha_element.screenshot_as_png
            img = Image.open(BytesIO(png))
            return self.solve(img)
        except Exception as e:
            log.warning(f"Error taking screenshot of captcha: {e}")
            return ""

    solve_image_captcha = solve_from_element

    def _solve_rapidocr(self, img: Image.Image) -> str:
        """Solve using RapidOCR (ONNX Runtime)."""
        try:
            np_arr = np.array(img.convert("RGB"))
            res, _ = RAPID_OCR(np_arr)
            if res:
                text = "".join([item[1] for item in res])
                return text
        except Exception as e:
            log.warning(f"RapidOCR solve failed: {e}")
        return ""

    def _solve_2captcha(self, img: Image.Image) -> str:
        log.info("Sending CAPTCHA to 2Captcha API...")
        try:
            b64 = self._img_to_base64(img)
            submit_resp = requests.post("http://2captcha.com/in.php", data={
                "key":    self.api_key,
                "method": "base64",
                "body":   b64,
                "json":   1
            }, timeout=30)

            if submit_resp.json().get("status") != 1:
                log.error(f"2Captcha submit failed: {submit_resp.text}")
                return self._solve_rapidocr(img) if RAPID_OCR_AVAILABLE else ""

            captcha_id = submit_resp.json()["request"]
            res_url = f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}&json=1"

            time.sleep(5)
            for _ in range(24):
                time.sleep(2)
                r = requests.get(res_url, timeout=10)
                d = r.json()
                if d.get("status") == 1:
                    return d["request"]
                if d.get("request") != "CAPCHA_NOT_READY":
                    break
        except Exception as e:
            log.warning(f"2Captcha API error: {e}")

        return self._solve_rapidocr(img) if RAPID_OCR_AVAILABLE else ""

    def _solve_ocr(self, img: Image.Image) -> str:
        if not TESSERACT_AVAILABLE:
            return ""
        try:
            return pytesseract.image_to_string(img, config="--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
        except Exception:
            return ""

    def _load_image(self, source) -> Image.Image:
        if isinstance(source, Image.Image):
            return source
        if isinstance(source, bytes):
            return Image.open(BytesIO(source))
        if isinstance(source, str):
            if os.path.exists(source):
                return Image.open(source)
            if source.startswith("data:image"):
                source = source.split(",", 1)[1]
            return Image.open(BytesIO(base64.b64decode(source)))
        raise ValueError("Unsupported image source.")

    def _img_to_base64(self, img: Image.Image) -> str:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
