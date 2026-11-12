# ============================================================
#  IRCTC TATKAL AUTOBOOK ENGINE — CONFIG
#  Fast Automated Tatkal Ticket Booking & Form Automation
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── IRCTC Credentials (stored in .env, never hardcoded) ──
IRCTC_USERNAME   = os.getenv("IRCTC_USERNAME", "")
IRCTC_PASSWORD   = os.getenv("IRCTC_PASSWORD", "")
IRCTC_MOBILE     = os.getenv("IRCTC_MOBILE", "")

# ── CAPTCHA Service (2Captcha API) ──
CAPTCHA_API_KEY  = os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_SERVICE  = "2captcha"          # or "anticaptcha" / "local_ocr"
USE_LOCAL_OCR    = False               # Set True to use Tesseract locally

# ── IRCTC URLs ──
BASE_URL         = "https://www.irctc.co.in/nget/train-search"
LOGIN_URL        = "https://www.irctc.co.in/nget/train-search"
BOOK_URL         = "https://www.irctc.co.in/nget/train-search"

# ── Browser Settings ──
BROWSER          = "chrome"            # chrome / firefox
HEADLESS         = False               # False = visible browser (recommended)
BROWSER_PROFILE  = "irctc_profile"    # Reuse session to avoid re-login
IMPLICIT_WAIT    = 1                   # seconds (low for high-speed fallback checks)
PAGE_LOAD_TIMEOUT= 30

# ── Timing (seconds) ──
PRE_LOGIN_BUFFER     = 120   # Login this many seconds before Tatkal opens
TATKAL_AC_HOUR       = 10    # AC classes: 10:00 AM
TATKAL_AC_MINUTE     = 0
TATKAL_NON_AC_HOUR   = 11   # Non-AC: 11:00 AM
TATKAL_NON_AC_MINUTE = 0
FORM_FILL_DELAY      = 0.05  # Delay between keystrokes (seconds)
CLICK_DELAY          = 0.1
POST_SUBMIT_WAIT     = 8

# ── Retry Settings ──
MAX_RETRIES          = 3
RETRY_DELAY          = 2
PAYMENT_TIMEOUT      = 300   # 5 min for payment

# ── Notification (Twilio SMS) ──
TWILIO_SID       = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN     = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM      = os.getenv("TWILIO_FROM", "")
NOTIFY_TO        = os.getenv("NOTIFY_TO", "")

# ── Logging ──
LOG_DIR          = "logs"
LOG_LEVEL        = "DEBUG"
LOG_FILE         = "logs/irctc_bot.log"

# ── Encryption (for storing sensitive data) ──
ENCRYPTION_KEY   = os.getenv("ENCRYPTION_KEY", "")

# ── Flask Dashboard ──
FLASK_HOST       = "127.0.0.1"
FLASK_PORT       = 5000
FLASK_DEBUG      = True
