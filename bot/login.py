# bot/login.py — Precision IRCTC Login Automation (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.logger import get_logger
from config.settings import BASE_URL

log = get_logger("Login")


def _is_logged_in(driver):
    """Check if session is already logged in."""
    try:
        src = driver.page_source
        return any(x in src for x in ['logout', 'LOGOUT', 'My Account', 'myAccount', 'hi,'])
    except Exception:
        return False


def _do_login(driver, username, password, captcha_solver=None):
    """
    Executes IRCTC login matching exact Angular / PrimeNG component hierarchy:
    1. app-header a.loginText
    2. app-login
    3. app-login input[formcontrolname='userid']
    4. app-login input[formcontrolname='password']
    5. app-login app-captcha .captcha-img -> RapidOCR
    6. app-login #captcha
    7. app-login button[type='submit']
    8. Wait for app-login to disappear
    """
    for attempt in range(1, 4):
        try:
            log.info(f"Login attempt {attempt}/3 for user: {username}")
            driver.get(BASE_URL)
            time.sleep(2)

            if _is_logged_in(driver):
                log.info("Already logged in.")
                return True

            # 1. Click header LOGIN button (app-header a.loginText)
            log.info("Opening login modal via header button...")
            login_btn = None
            for sel in [
                "app-header a.loginText",
                "a.loginText",
                ".loginText",
                "//a[contains(text(),'LOGIN')]",
            ]:
                try:
                    if sel.startswith("//"):
                        login_btn = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, sel))
                        )
                    else:
                        login_btn = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                        )
                    if login_btn and login_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", login_btn)
                        log.info("Clicked header login button.")
                        break
                except Exception:
                    continue

            # 2. Wait for app-login component to be visible in DOM
            log.info("Waiting for app-login modal to appear...")
            login_modal = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "app-login"))
            )
            time.sleep(0.5)

            # 3. Locate username and password inputs inside app-login
            usr_input = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, "app-login input[formcontrolname='userid']")
                )
            )
            pwd_input = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, "app-login input[formcontrolname='password']")
                )
            )

            # 4. Fill username with real send_keys so Angular reactive form updates
            usr_input.click()
            time.sleep(0.1)
            usr_input.clear()
            usr_input.send_keys(username)
            log.info(f"Entered username: {username}")

            # 5. Fill password with real send_keys
            pwd_input.click()
            time.sleep(0.1)
            pwd_input.clear()
            pwd_input.send_keys(password)
            log.info("Entered password.")

            time.sleep(0.3)

            # 6. Locate captcha image and input inside app-login
            captcha_img = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "app-login app-captcha .captcha-img, app-login app-captcha img, app-captcha img")
                )
            )
            captcha_input = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, "app-login #captcha, app-captcha #captcha, app-login input[formcontrolname='captcha']")
                )
            )

            # Allow captcha image decoding
            time.sleep(0.6)

            solved_text = ""
            if captcha_solver:
                log.info("Solving login CAPTCHA with RapidOCR AI...")
                solved_text = captcha_solver.solve_from_element(driver, captcha_img)

            if solved_text:
                captcha_input.click()
                time.sleep(0.1)
                captcha_input.clear()
                captcha_input.send_keys(solved_text)
                log.info(f"Entered solved CAPTCHA: '{solved_text}'")
            else:
                log.info("Awaiting CAPTCHA (you can also type it directly in the open Chrome window)...")
                for _ in range(16):  # max 8 seconds
                    val = captcha_input.get_attribute("value") or ""
                    if len(val.strip()) >= 4:
                        log.info(f"CAPTCHA detected: '{val.strip()}'")
                        break
                    time.sleep(0.5)

            time.sleep(0.3)

            # 7. Submit: Click button[type='submit'] inside app-login
            sign_in_btn = login_modal.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", sign_in_btn)
            log.info("⚡ Clicked SIGN IN button.")

            # 8. Wait for app-login modal to disappear (signifying successful login)
            try:
                WebDriverWait(driver, 10).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "app-login"))
                )
                log.info("🎉 app-login modal disappeared — Login successful!")
                time.sleep(1)
                return True
            except Exception:
                pass

            time.sleep(2)
            if _is_logged_in(driver):
                log.info("🎉 Login successful! Session is active.")
                return True

            src = driver.page_source
            if "invalid" in src.lower() or "incorrect" in src.lower() or "bad credentials" in src.lower():
                log.error("Wrong credentials or invalid captcha — retrying...")
                time.sleep(2)
                continue

            log.warning(f"Attempt {attempt} did not complete login, retrying...")
            time.sleep(2)

        except Exception as e:
            log.warning(f"Login attempt {attempt} error: {e}")
            time.sleep(2)

    log.error("All login attempts failed.")
    return False


class IRCTCLogin:
    def __init__(self, driver, captcha_solver=None):
        self.driver = driver
        self.captcha_solver = captcha_solver
        self._username = ""
        self._password = ""

    def login(self, username="", password=""):
        u = username or self._username
        p = password or self._password
        return _do_login(self.driver, u, p, self.captcha_solver)

    def ensure_logged_in(self, username, password):
        self._username = username
        self._password = password
        if _is_logged_in(self.driver):
            log.info("Session already active — skipping login.")
            return True
        return _do_login(self.driver, username, password, self.captcha_solver)

    def is_logged_in(self):
        return _is_logged_in(self.driver)
