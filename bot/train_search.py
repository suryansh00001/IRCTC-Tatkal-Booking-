# bot/train_search.py — IRCTC Train Search & Selection (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.logger import get_logger
from config.settings import BASE_URL

log = get_logger("TrainSearch")


class IRCTCServiceUnavailableError(Exception):
    """Raised when IRCTC displays a service unavailable, maintenance, or booking blocked notice."""
    pass


class TrainNotFoundError(Exception):
    """Raised when the requested train number/class cannot be found in search results."""
    pass


ERROR_KEYWORDS = [
    "service not available",
    "service is not available",
    "no direct trains found",
    "no direct train",
    "no trains found",
    "booking not allowed",
    "booking is not allowed",
    "train cancelled",
    "train is cancelled",
    "maintenance",
    "system is down",
    "technical error",
    "technical problem",
    "invalid station",
    "session expired",
    "tatkal booking will start at",
    "booking will open at",
    "please try again later",
    "quota not applicable",
    "invalid journey date",
    "outside the advance reservation period",
]

FROM_SELECTORS = [
    (By.CSS_SELECTOR, "input#origin, #origin input, app-jp-input input#origin"),
    (By.XPATH, "//input[@id='origin' or contains(@id,'origin')]"),
    (By.XPATH, "//p-autocomplete[@formcontrolname='origin']//input"),
    (By.XPATH, "//input[@placeholder='From' or @placeholder='FROM *']"),
]
TO_SELECTORS = [
    (By.CSS_SELECTOR, "input#destination, #destination input, app-jp-input input#destination"),
    (By.XPATH, "//input[@id='destination' or contains(@id,'destination')]"),
    (By.XPATH, "//p-autocomplete[@formcontrolname='destination']//input"),
    (By.XPATH, "//input[@placeholder='To' or @placeholder='TO *']"),
]
DATE_SELECTORS = [
    (By.CSS_SELECTOR, "input#jDate, #jDate input, input#journeyDate, #journeyDate input"),
    (By.XPATH, "//input[@id='jDate' or @id='journeyDate']"),
    (By.XPATH, "//p-calendar//input"),
    (By.XPATH, "//input[@placeholder='Date of Journey' or @placeholder='DD/MM/YYYY']"),
]
SEARCH_BTN_SELECTORS = [
    (By.CSS_SELECTOR, "app-jp-input button[type='submit'].search_btn"),
    (By.CSS_SELECTOR, "button.search_btn"),
    (By.XPATH, "//button[contains(text(),'Search') or normalize-space()='Search']"),
    (By.XPATH, "//button[@type='submit']"),
]


def _find(driver, selectors, timeout=10):
    for by, sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, sel))
            )
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None


def _scroll_to(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.3)


def handle_confirmation_dialogs(driver, preferred="English"):
    """Auto-accept any IRCTC pop-up confirmation / alert dialogs or language selector, returning any message dismissed."""
    from config.settings import IMPLICIT_WAIT
    driver.implicitly_wait(0)
    dismissed_text = None
    try:
        # Check if there is an active dialog with text before clicking
        for dlg_sel in ["p-confirmdialog", "p-dialog", ".ui-dialog"]:
            try:
                dlgs = driver.find_elements(By.CSS_SELECTOR, dlg_sel)
                for dlg in dlgs:
                    if dlg.is_displayed():
                        txt = dlg.text.strip()
                        if txt and "language" not in txt.lower():
                            log.info(f"IRCTC Dialog notice: '{txt}'")
                            dismissed_text = txt
            except Exception:
                pass

        popup_selectors = [
            f"//p-dialog//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{preferred.upper()}')]",
            f"//button[normalize-space()='{preferred}']",
            "button[aria-label*='Please select your preferred language']",
            "p-confirmdialog[key='tofrom'] .ui-confirmdialog-acceptbutton",
            ".ui-confirmdialog-acceptbutton",
            "p-confirmdialog .ui-button:not(.ui-confirmdialog-rejectbutton)",
            "p-dialog button[aria-label*='language']",
            "//p-confirmdialog//button[contains(.,'Yes') or contains(.,'OK') or contains(.,'Accept')]",
        ]
        for sel in popup_selectors:
            try:
                if sel.startswith("//"):
                    btns = driver.find_elements(By.XPATH, sel)
                else:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        log.info("Dismissing IRCTC dialog/prompt...")
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.5)
                        return dismissed_text or True
            except Exception:
                pass
    finally:
        driver.implicitly_wait(IMPLICIT_WAIT)
    return dismissed_text or False


def check_search_errors_or_availability(driver):
    """
    Inspects the DOM for IRCTC search error messages, service unavailability,
    maintenance notices, no-train alerts, or dialog warnings.
    Returns the error message string if an error is present, else None.
    """
    from config.settings import IMPLICIT_WAIT
    driver.implicitly_wait(0)
    try:
        # 1. Growl / Toast notifications (PrimeNG)
        growl_selectors = [
            ".ui-growl-message",
            "p-growl .ui-growl-item-container",
            "p-toast .p-toast-message",
            ".p-toast-detail",
            ".toast-message",
        ]
        for sel in growl_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                try:
                    if el.is_displayed():
                        txt = el.text.strip()
                        if not txt:
                            continue
                        low = txt.lower()
                        if any(kw in low for kw in ERROR_KEYWORDS):
                            return f"IRCTC Toast Alert: {txt}"
                        cls = (el.get_attribute("class") or "").lower()
                        if ("error" in cls or "warn" in cls) and len(txt) > 3:
                            return f"IRCTC Error Toast: {txt}"
                except Exception:
                    pass

        # 2. Message bars / alerts (.ui-messages-error, .alert-danger, no-train)
        msg_selectors = [
            ".ui-messages-error",
            "p-messages .ui-messages-error-detail",
            "p-messages .ui-messages-error-summary",
            ".alert-danger",
            ".alert-warning",
            "app-train-list .no-train",
            ".no-train-heading",
            ".no-train",
            ".train-not-found",
        ]
        for sel in msg_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                try:
                    if el.is_displayed():
                        txt = el.text.strip()
                        if txt:
                            return f"IRCTC Message: {txt}"
                except Exception:
                    pass

        # 3. Active Dialogs / Modals (p-dialog, p-confirmdialog)
        dlg_selectors = [
            "p-confirmdialog .ui-confirmdialog-message",
            "p-confirmdialog .ui-dialog-content",
            "p-dialog .ui-dialog-content",
            ".ui-dialog-content",
            ".modal-body",
        ]
        for sel in dlg_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                try:
                    if el.is_displayed():
                        txt = el.text.strip()
                        low = txt.lower()
                        # Ignore pure language prompt
                        if ("please select your preferred language" in low or 
                            ("hindi" in low and "english" in low and len(txt) < 40)):
                            continue
                        if any(kw in low for kw in ERROR_KEYWORDS) or len(txt) > 10:
                            return f"IRCTC Dialog Alert: {txt}"
                except Exception:
                    pass

        # 4. Body text fallback if search page loaded
        try:
            curr_url = driver.current_url or ""
            if "train-list" in curr_url or "train-search" in curr_url:
                body_el = driver.find_elements(By.TAG_NAME, "body")
                if body_el:
                    body_text = body_el[0].text.lower()
                    for kw in [
                        "service is not available",
                        "service not available",
                        "no direct trains found",
                        "system is down for maintenance",
                        "maintenance activity in progress",
                        "outside the advance reservation period",
                        "booking is not allowed",
                    ]:
                        if kw in body_text:
                            idx = body_text.find(kw)
                            snippet = body_text[max(0, idx - 10):min(len(body_text), idx + 80)].strip()
                            return f"IRCTC Notice: '{snippet}'"
        except Exception:
            pass

    finally:
        driver.implicitly_wait(IMPLICIT_WAIT)

    return None


def _type_station(driver, field, code):
    """Type station code and pick from modern PrimeNG autocomplete list."""
    _scroll_to(driver, field)
    driver.execute_script("arguments[0].click();", field)
    time.sleep(0.2)
    field.clear()
    driver.execute_script("arguments[0].value='';", field)

    for ch in code:
        field.send_keys(ch)
        time.sleep(0.08)

    # Trigger input event for Angular
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", field
    )
    time.sleep(1.2)

    # Pick matching suggestion (.ui-autocomplete-items li)
    for sel in [
        f"//ul[contains(@class,'ui-autocomplete-items')]//li[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{code.upper()}')]",
        ".ui-autocomplete-items li",
        "//ul[contains(@class,'ui-autocomplete-list')]//li[1]",
        "//li[contains(@class,'ui-autocomplete-list-item')][1]",
    ]:
        try:
            if sel.startswith("//"):
                suggs = driver.find_elements(By.XPATH, sel)
            else:
                suggs = driver.find_elements(By.CSS_SELECTOR, sel)

            if suggs:
                sugg = suggs[0]
                driver.execute_script("arguments[0].click();", sugg)
                log.info(f"Station selected: {code}")
                time.sleep(0.5)
                return
        except Exception:
            continue

    field.send_keys("\n")
    time.sleep(0.5)


class TrainSearch:
    def __init__(self, driver):
        self.driver = driver

    def fill_search_form(self, from_station, to_station, travel_date, quota="TQ"):
        log.info(f"Filling search: {from_station} -> {to_station} | {travel_date} | {quota}")

        if "train-search" not in self.driver.current_url:
            self.driver.get(BASE_URL)
            time.sleep(3)

        handle_confirmation_dialogs(self.driver)

        # Scroll to top first
        self.driver.execute_script("window.scrollTo(0,0);")
        time.sleep(0.5)

        # FROM
        f = _find(self.driver, FROM_SELECTORS, timeout=15)
        if not f:
            raise Exception("From station field not found")
        _type_station(self.driver, f, from_station)
        time.sleep(0.5)

        # TO
        t = _find(self.driver, TO_SELECTORS, timeout=10)
        if not t:
            raise Exception("To station field not found")
        _type_station(self.driver, t, to_station)
        time.sleep(0.5)

        # DATE
        d = _find(self.driver, DATE_SELECTORS, timeout=10)
        if d:
            _scroll_to(self.driver, d)
            self.driver.execute_script("arguments[0].click();", d)
            time.sleep(0.2)
            d.clear()
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                d, travel_date
            )
            time.sleep(0.3)
            self.driver.execute_script("document.body.click();")
            log.info(f"Date set: {travel_date}")

        # QUOTA
        try:
            quota_names = {
                "TQ": "TATKAL",
                "PT": "PREMIUM TATKAL",
                "GN": "GENERAL",
                "LD": "LADIES",
                "SS": "LOWER BERTH/SR.CITIZEN",
            }
            target_q = quota_names.get(quota.upper(), quota.upper())

            q_el = None
            for q_sel in ["#journeyQuota>div", "#journeyQuota", "p-dropdown[formcontrolname='journeyQuota']"]:
                try:
                    q_el = self.driver.find_element(By.CSS_SELECTOR, q_sel)
                    if q_el.is_displayed():
                        break
                except Exception:
                    pass

            if q_el:
                _scroll_to(self.driver, q_el)
                self.driver.execute_script("arguments[0].click();", q_el)
                time.sleep(0.6)

                items = self.driver.find_elements(
                    By.CSS_SELECTOR, "#journeyQuota p-dropdownitem span, .ui-dropdown-items li"
                )
                for item in items:
                    txt = item.text.strip().upper()
                    if target_q in txt or quota.upper() in txt:
                        self.driver.execute_script("arguments[0].click();", item)
                        log.info(f"Quota set: {target_q}")
                        break
        except Exception as e:
            log.warning(f"Quota selection skipped/default: {e}")

        return True

    def submit_search(self):
        time.sleep(0.5)
        btn = _find(self.driver, SEARCH_BTN_SELECTORS, timeout=10)
        if btn:
            _scroll_to(self.driver, btn)
            self.driver.execute_script("arguments[0].click();", btn)
            log.info("Search submitted")
            time.sleep(5)
            handle_confirmation_dialogs(self.driver)
            return True
        raise Exception("Search button not found")

    def select_train_and_class(self, train_number, travel_class, quota="TQ"):
        log.info(f"Selecting train {train_number}, class {travel_class}")

        # Wait for results page
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "app-train-avl-enq, app-train-list, .train-heading")
            )
        )
        time.sleep(1.5)
        handle_confirmation_dialogs(self.driver)

        # Locate train card by number
        train_cards = self.driver.find_elements(By.CSS_SELECTOR, "app-train-avl-enq")
        target_card = None

        for card in train_cards:
            try:
                heading = card.find_element(By.CSS_SELECTOR, ".train-heading").text
                if train_number in heading:
                    target_card = card
                    _scroll_to(self.driver, card)
                    log.info(f"Train {train_number} found: {heading.strip()}")
                    break
            except Exception:
                if train_number in card.text:
                    target_card = card
                    _scroll_to(self.driver, card)
                    log.info(f"Train {train_number} found via card text")
                    break

        if not target_card and train_cards:
            log.warning(f"Train {train_number} not matched exactly — using first visible train")
            target_card = train_cards[0]
            _scroll_to(self.driver, target_card)

        if not target_card:
            raise Exception("No train cards rendered on results page.")

        time.sleep(0.5)

        # Click accommodation class (.pre-avl)
        class_elements = target_card.find_elements(
            By.CSS_SELECTOR, ".pre-avl, p-tabmenu li[role='tab']"
        )
        clicked_class = False

        for el in class_elements:
            try:
                if travel_class.upper() in el.text.upper():
                    _scroll_to(self.driver, el)
                    self.driver.execute_script("arguments[0].click();", el)
                    log.info(f"Class {travel_class} clicked")
                    clicked_class = True
                    time.sleep(1.5)
                    break
            except Exception:
                continue

        if not clicked_class:
            raise Exception(f"Class {travel_class} button not found on train {train_number}")

        handle_confirmation_dialogs(self.driver)

        # Click Book Now button
        for sel in [
            "button.btnDefault.train_Search",
            "button.btnDefault",
            "//button[contains(text(),'Book Now') or normalize-space()='Book Now']",
            "//button[contains(.,'Book Now') and not(contains(@class,'disable-book'))]",
        ]:
            try:
                if sel.startswith("//"):
                    btns = self.driver.find_elements(By.XPATH, sel)
                else:
                    btns = self.driver.find_elements(By.CSS_SELECTOR, sel)

                for btn in btns:
                    if btn.is_displayed():
                        _scroll_to(self.driver, btn)
                        self.driver.execute_script("arguments[0].click();", btn)
                        log.info("Book Now clicked")
                        time.sleep(2)
                        handle_confirmation_dialogs(self.driver)

                        # Wait for transition to passenger page
                        try:
                            WebDriverWait(self.driver, 15).until(
                                lambda d: "train-list" not in d.current_url or
                                          len(d.find_elements(By.CSS_SELECTOR, "app-passenger-input, app-passenger")) > 0
                            )
                            log.info("Navigated to passenger details stage")
                        except Exception:
                            log.warning("Waiting for passenger form...")
                        return True
            except Exception:
                continue

        log.warning("Book Now button click attempted; proceeding.")
        return True
