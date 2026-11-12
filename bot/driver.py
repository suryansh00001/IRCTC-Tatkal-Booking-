import os
import shutil
import tempfile
from utils.logger import get_logger
from config.settings import IMPLICIT_WAIT, PAGE_LOAD_TIMEOUT, BROWSER_PROFILE

log = get_logger("Driver")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

try:
    from webdriver_manager.chrome import ChromeDriverManager
    HAVE_WDM = True
except ImportError:
    HAVE_WDM = False


def _clean_profile_locks(profile_dir: str):
    """Clean up stale Chrome lock files that prevent Chrome from launching."""
    lock_files = [
        os.path.join(profile_dir, "lockfile"),
        os.path.join(profile_dir, "Default", "LOCK"),
    ]
    for lf in lock_files:
        try:
            if os.path.exists(lf):
                os.remove(lf)
                log.info(f"Removed stale Chrome lock: {lf}")
        except Exception:
            pass


def _build_options(profile_dir: str = None) -> Options:
    options = Options()
    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")

    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    return options


def create_driver() -> webdriver.Chrome:
    profile_dir = os.path.abspath(BROWSER_PROFILE)
    os.makedirs(profile_dir, exist_ok=True)
    _clean_profile_locks(profile_dir)

    log.info("Starting Chrome...")

    # Attempt 1: Standard launch with configured profile
    try:
        options = _build_options(profile_dir)
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        driver.implicitly_wait(IMPLICIT_WAIT)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        log.info("Chrome started successfully.")
        return driver
    except Exception as e1:
        log.warning(f"Profile launch failed ({e1}) — retrying with fresh isolated profile...")

    # Attempt 2: Isolated temporary profile
    try:
        temp_dir = tempfile.mkdtemp(prefix="irctc_session_")
        options = _build_options(temp_dir)
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        driver.implicitly_wait(IMPLICIT_WAIT)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        log.info("Chrome started successfully with isolated session.")
        return driver
    except Exception as e2:
        log.warning(f"Temp profile launch failed ({e2}) — retrying with standard clean options...")

    # Attempt 3: Clean fallback with minimal options
    fallback_opts = Options()
    fallback_opts.add_argument("--start-maximized")
    fallback_opts.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=fallback_opts)
    driver.implicitly_wait(IMPLICIT_WAIT)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    log.info("Chrome started via fallback.")
    return driver


def safe_quit(driver):
    try:
        if driver:
            driver.quit()
            log.info("Browser closed.")
    except Exception as e:
        log.debug(f"Driver quit error: {e}")
