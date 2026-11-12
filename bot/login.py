# bot/login.py — Precision IRCTC Login Automation (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.logger import get_logger
from config.settings import BASE_URL

log = get_logger("Login")


def _is_logged_in(driver):
    """Check if session is genuinely logged in via visible header elements."""
    try:
        # 1. If the header LOGIN button is visible, user is definitely NOT logged in
        for sel in [
            "a.loginText",
            "app-header a.loginText",
            "//app-header//a[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'LOGIN')]",
        ]:
            try:
                btns = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                if any(b.is_displayed() for b in btns):
                    return False
            except Exception:
                pass

        # 2. If a LOGOUT button is visible in the header, user IS logged in
        for sel in [
            "a.logoutText",
            "app-header a.logoutText",
            "app-header a[title='Logout']",
            "//app-header//a[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'LOGOUT')]",
            "//app-header//span[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'LOGOUT')]",
        ]:
            try:
                btns = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                if any(b.is_displayed() for b in btns):
                    return True
            except Exception:
                pass

    except Exception:
        pass

    return False


def _dismiss_initial_dialogs(driver, preferred="English"):
    """Auto-dismiss initial language prompt or welcome overlay."""
    for sel in [
        f"//p-dialog//button[normalize-space()='{preferred}' or contains(.,'{preferred}')]",
        "//p-dialog//button[normalize-space()='English' or contains(.,'English')]",
        "//p-dialog//button[normalize-space()='हिंदी' or contains(.,'हिंदी')]",
        "//button[normalize-space()='English']",
        "button[aria-label*='language']",
        "p-confirmdialog .ui-confirmdialog-acceptbutton",
        ".ui-confirmdialog-acceptbutton",
    ]:
        try:
            btns = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for b in btns:
                if b.is_displayed():
                    log.info("Dismissing initial language/welcome prompt...")
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(1)
                    return True
        except Exception:
            pass
    return False


def _do_login(driver, username, password, captcha_solver=None):
    """
    Executes IRCTC login matching exact Angular / PrimeNG component hierarchy:
    1. Dismiss language prompt if present
    2. app-header a.loginText
    3. app-login modal
    4. app-login input[formcontrolname='userid']
    5. app-login input[formcontrolname='password']
    6. Conditionally solve captcha if rendered
    7. app-login button[type='submit']
    8. Wait for app-login to disappear / session verified
    """
    for attempt in range(1, 4):
        try:
            log.info(f"Login attempt {attempt}/3 for user: {username}")
            driver.get(BASE_URL)
            time.sleep(2.5)

            if _is_logged_in(driver):
                log.info("Already logged in.")
                return True

            # 1. Dismiss initial language or welcome dialog
            _dismiss_initial_dialogs(driver)

            # 2. Click header LOGIN button (app-header a.loginText)
            log.info("Opening login modal via header button...")
            login_btn = None
            for sel in [
                "a.loginText",
                "app-header a.loginText",
                ".loginText",
                "//a[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'LOGIN')]",
            ]:
                try:
                    btns = driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                    for b in btns:
                        if b.is_displayed():
                            login_btn = b
                            break
                    if login_btn:
                        driver.execute_script("arguments[0].click();", login_btn)
                        log.info("Clicked header login button.")
                        break
                except Exception:
                    continue

            # 3. Wait for app-login component to be visible in DOM
            log.info("Waiting for app-login modal to appear...")
            login_modal = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "app-login"))
            )
            time.sleep(0.5)

            # 4. Locate username and password inputs inside app-login
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

            # Fill username with native send_keys and trigger Angular input events
            usr_input.click()
            time.sleep(0.1)
            usr_input.clear()
            usr_input.send_keys(username)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", usr_input
            )
            log.info(f"Entered username: {username}")

            # Fill password
            pwd_input.click()
            time.sleep(0.1)
            pwd_input.clear()
            pwd_input.send_keys(password)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", pwd_input
            )
            log.info("Entered password.")

            time.sleep(0.4)

            # 5. Conditionally check if captcha is present on this login form
            captcha_imgs = login_modal.find_elements(
                By.CSS_SELECTOR, "app-captcha .captcha-img, app-captcha img, .captcha-img"
            )
            captcha_inps = login_modal.find_elements(
                By.CSS_SELECTOR, "#captcha, input[formcontrolname='captcha']"
            )

            if captcha_imgs and captcha_inps and captcha_imgs[0].is_displayed():
                c_img = captcha_imgs[0]
                c_inp = captcha_inps[0]
                solved_text = ""
                if captcha_solver:
                    log.info("Solving login CAPTCHA with RapidOCR AI...")
                    solved_text = captcha_solver.solve_from_element(driver, c_img)

                if solved_text:
                    c_inp.click()
                    time.sleep(0.1)
                    c_inp.clear()
                    c_inp.send_keys(solved_text)
                    driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", c_inp
                    )
                    log.info(f"Entered solved CAPTCHA: '{solved_text}'")
                else:
                    log.info("Awaiting CAPTCHA input...")
                    for _ in range(16):
                        val = c_inp.get_attribute("value") or ""
                        if len(val.strip()) >= 4:
                            log.info(f"CAPTCHA detected: '{val.strip()}'")
                            break
                        time.sleep(0.5)

            time.sleep(0.3)

            # 6. Submit: Click button[type='submit'] inside app-login
            sign_in_btn = login_modal.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", sign_in_btn)
            log.info("⚡ Clicked SIGN IN button.")

            # 7. Wait for app-login modal to disappear (signifying successful login)
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

            # Check for visible error message inside app-login
            try:
                err_els = login_modal.find_elements(
                    By.CSS_SELECTOR, ".loginError, .alert-danger, .error, .ui-messages-error"
                )
                for ed in err_els:
                    if ed.is_displayed() and ed.text.strip():
                        log.error(f"IRCTC Login Error: {ed.text.strip()}")
            except Exception:
                pass

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
            log.info("Session already verified active — skipping login.")
            return True
        log.info("No active session detected — starting login...")
        return _do_login(self.driver, username, password, self.captcha_solver)

    def is_logged_in(self):
        return _is_logged_in(self.driver)
