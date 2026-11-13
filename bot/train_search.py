# bot/train_search.py — IRCTC Train Search & Selection (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
    """Type station code and pick from modern PrimeNG autocomplete list rapidly."""
    _scroll_to(driver, field)
    driver.execute_script("arguments[0].click();", field)
    field.clear()
    driver.execute_script("arguments[0].value='';", field)

    field.send_keys(code)

    # Trigger input event for Angular
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", field
    )

    # Reactively wait for autocomplete suggestions to render (typically 100-300ms)
    try:
        WebDriverWait(driver, 2.5).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".ui-autocomplete-items li, .ui-autocomplete-list li, li.ui-autocomplete-list-item")) > 0
        )
    except Exception:
        pass

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
                time.sleep(0.2)
                return
        except Exception:
            continue

    field.send_keys("\n")
    time.sleep(0.2)


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
            d.click()
            time.sleep(0.1)
            d.send_keys(Keys.CONTROL + "a")
            d.send_keys(Keys.BACKSPACE)
            time.sleep(0.1)
            d.send_keys(travel_date)
            d.send_keys(Keys.TAB)
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
        if not btn:
            raise Exception("Search button not found")

        _scroll_to(self.driver, btn)
        self.driver.execute_script("arguments[0].click();", btn)
        log.info("Search submitted — awaiting response...")

        # Responsive check: poll up to 5s for early error toast / dialog vs successful navigation
        for _ in range(10):  # 10 x 0.5s = 5 seconds
            time.sleep(0.5)

            # Check if an error banner or dialog appeared
            err = check_search_errors_or_availability(self.driver)
            if err:
                log.error(f"❌ IRCTC Search Error: {err}")
                handle_confirmation_dialogs(self.driver)
                raise IRCTCServiceUnavailableError(err)

            # Check if results or list page is already reached
            if "train-list" in self.driver.current_url:
                break
            if self.driver.find_elements(By.CSS_SELECTOR, "app-train-avl-enq, app-train-list"):
                break

        handle_confirmation_dialogs(self.driver)
        return True

    def select_train_and_class(self, train_number, travel_class, quota="TQ", alt_train=None):
        log.info(f"Selecting train {train_number}, class {travel_class} (Quota: {quota})")

        # 1. Wait for results page or error detection (responsive polling)
        train_cards = []
        start_time = time.time()
        timeout = 25

        while time.time() - start_time < timeout:
            # Check for error banners / dialogs first
            err = check_search_errors_or_availability(self.driver)
            if err:
                log.error(f"❌ IRCTC Service/Search Error: {err}")
                handle_confirmation_dialogs(self.driver)
                raise IRCTCServiceUnavailableError(err)

            cards = self.driver.find_elements(By.CSS_SELECTOR, "app-train-avl-enq")
            if cards and any(c.is_displayed() for c in cards):
                train_cards = [c for c in cards if c.is_displayed()]
                break

            time.sleep(0.5)

        if not train_cards:
            # Check once more if an error occurred before raising timeout
            err = check_search_errors_or_availability(self.driver)
            if err:
                raise IRCTCServiceUnavailableError(err)
            raise TrainNotFoundError("No train cards rendered on search page.")

        time.sleep(0.5)
        handle_confirmation_dialogs(self.driver)

        # 2. Locate target train card
        target_card = None
        available_trains = []

        for card in train_cards:
            try:
                card_text = card.text
                heading_el = card.find_elements(By.CSS_SELECTOR, ".train-heading")
                heading = heading_el[0].text.strip() if heading_el else card_text.split("\n")[0]
                available_trains.append(heading)

                if not train_number or str(train_number).upper() == "ANY" or str(train_number) in heading or str(train_number) in card_text:
                    target_card = card
                    _scroll_to(self.driver, card)
                    log.info(f"Train {train_number or 'ANY'} matched: {heading}")
                    break
            except Exception:
                continue

        # If primary train not found, check alt_train if provided
        if not target_card and alt_train:
            log.warning(f"Train {train_number} not found. Checking alternate train {alt_train}...")
            for card in train_cards:
                try:
                    if alt_train in card.text:
                        target_card = card
                        _scroll_to(self.driver, card)
                        log.info(f"Alternate train {alt_train} found!")
                        break
                except Exception:
                    continue

        if not target_card:
            trains_summary = " | ".join(available_trains[:6]) if available_trains else "None"
            log.error(f"❌ Train {train_number} not found in search results. Available trains: {trains_summary}")
            raise TrainNotFoundError(
                f"Train {train_number} was not found among {len(train_cards)} trains listed on this route. "
                f"Available trains: [{trains_summary}]"
            )

        time.sleep(0.5)

        # 3. Click accommodation class button (outside availability table)
        class_elements = target_card.find_elements(
            By.CSS_SELECTOR, ":not(table) > .pre-avl, .white-back .pre-avl, app-train-avl-enq > div > div .pre-avl, p-tabmenu li"
        )
        clicked_class = False

        for el in class_elements:
            try:
                txt = el.text.upper()
                if travel_class.upper() in txt or (travel_class.upper() == "3A" and "3 TIER" in txt):
                    _scroll_to(self.driver, el)
                    self.driver.execute_script("arguments[0].click();", el)
                    log.info(f"Class {travel_class} clicked")
                    clicked_class = True
                    break
            except Exception:
                continue

        if not clicked_class:
            raise Exception(f"Class {travel_class} button not found on train {train_number}")

        # 1. Wait for IRCTC availability XHR to fetch and render the table
        time.sleep(1.2)
        try:
            WebDriverWait(self.driver, 8).until(
                lambda d: len(target_card.find_elements(By.CSS_SELECTOR, "table td.link.ng-star-inserted, table td.link")) > 0
            )
        except Exception:
            pass

        handle_confirmation_dialogs(self.driver)

        # 2. Select availability date slot
        slots = target_card.find_elements(
            By.CSS_SELECTOR, "table td.link.ng-star-inserted, table td.link"
        )
        target_slot = None
        for s in slots:
            txt = s.text.strip().replace("\n", " ")
            if txt and "NOT AVAILABLE" not in txt.upper() and "TRAIN CANCELLED" not in txt.upper():
                target_slot = s
                log.info(f"Target availability slot: {txt}")
                break

        if not target_slot and slots:
            target_slot = slots[0]
            log.info(f"Target fallback slot: {target_slot.text.strip().replace(chr(10), ' ')}")

        if not target_slot:
            err = check_search_errors_or_availability(self.driver)
            if err:
                raise IRCTCServiceUnavailableError(err)
            raise Exception(f"No availability date slot found for class {travel_class} on train {train_number}")

        _scroll_to(self.driver, target_slot)
        try:
            target_slot.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", target_slot)
        log.info("Clicked availability slot.")

        # 3. Wait reactively for Book Now button to be enabled (disable-book removed by Angular)
        book_btn = None
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            btns = target_card.find_elements(
                By.CSS_SELECTOR, "button.train_Search, button.btnDefault.train_Search, button.btnDefault"
            )
            for b in btns:
                classes = b.get_attribute("class") or ""
                if "disable-book" not in classes and b.is_displayed():
                    book_btn = b
                    log.info(f"Book Now button active and ready (class: '{classes}')")
                    break
            if book_btn:
                break
            time.sleep(0.2)
            # Re-click slot if still disabled after 1.5s
            if not book_btn and target_slot and (time.time() - start_wait > 1.5):
                try:
                    self.driver.execute_script("arguments[0].click();", target_slot)
                except Exception:
                    pass

        # 4. Click Book Now button
        book_now_clicked = False
        if book_btn:
            _scroll_to(self.driver, book_btn)
            try:
                book_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", book_btn)
            book_now_clicked = True
            log.info("Book Now button clicked!")
            time.sleep(0.8)
            handle_confirmation_dialogs(self.driver)
        else:
            # Direct JS fallback: remove disable-book class and click
            log.warning("Book Now button still in disable-book state — attempting force JS click...")
            for b in target_card.find_elements(By.CSS_SELECTOR, "button.train_Search, button.btnDefault"):
                if b.is_displayed():
                    self.driver.execute_script("arguments[0].classList.remove('disable-book'); arguments[0].click();", b)
                    book_now_clicked = True
                    log.info("Force clicked Book Now button via JS.")
                    time.sleep(0.8)
                    handle_confirmation_dialogs(self.driver)
                    break

        if not book_now_clicked:
            raise Exception("Book Now button could not be clicked.")

        # 5. Verify navigation to passenger page reactively
        navigated = False
        start_nav = time.time()
        while time.time() - start_nav < 12.0:
            curr_url = self.driver.current_url or ""
            if "psgninput" in curr_url or "passenger" in curr_url:
                navigated = True
                break
            if len(self.driver.find_elements(By.CSS_SELECTOR, "app-passenger-input, app-passenger, #mobileNumber")) > 0:
                navigated = True
                break
            # Dismiss any popup confirmation dialogs (e.g. station change prompt, senior citizen warning)
            handle_confirmation_dialogs(self.driver)
            time.sleep(0.4)

        if not navigated:
            err = check_search_errors_or_availability(self.driver)
            if err:
                raise IRCTCServiceUnavailableError(err)
            raise Exception(f"Failed to navigate to passenger details page (Current URL: {self.driver.current_url})")

        log.info(f"Navigated to passenger details stage ({self.driver.current_url})")
        return True
