# bot/passenger_filler.py — IRCTC Passenger Form Filler (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from utils.logger import get_logger

log = get_logger("PassengerFiller")


def _scroll_to(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.2)
    except Exception:
        pass


def _wait_for_passenger_page(driver):
    """Wait until we're on the passenger details page."""
    log.info(f"Waiting for passenger page... Current: {driver.current_url}")

    for _ in range(20):
        if "train-list" not in driver.current_url:
            break
        time.sleep(1)

    time.sleep(2)

    for sel in [
        "app-passenger-input",
        "app-passenger",
        "input[formcontrolname='passengerAge']",
        "input#mobileNumber",
        "//app-passenger",
        "//*[contains(@formcontrolname,'passenger')]",
    ]:
        try:
            if sel.startswith("//"):
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, sel))
                )
            else:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
            log.info(f"Passenger form confirmed via: {sel}")
            time.sleep(1)
            return True
        except Exception:
            continue

    log.warning("Passenger form element check timed out — proceeding anyway")
    return True


def _js_set(driver, el, value):
    """Set input value via JS and dispatch standard Angular events."""
    driver.execute_script(
        "arguments[0].focus();"
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        el, str(value)
    )


def _fill_input(driver, selectors, value):
    """Try multiple CSS/XPath selectors to fill an input field."""
    for sel in selectors:
        try:
            if sel.startswith("//") or sel.startswith("("):
                els = driver.find_elements(By.XPATH, sel)
            else:
                els = driver.find_elements(By.CSS_SELECTOR, sel)

            for el in els:
                if el.is_displayed():
                    _scroll_to(driver, el)
                    try:
                        el.clear()
                        el.send_keys(str(value))
                        _js_set(driver, el, value)
                        return True
                    except Exception:
                        _js_set(driver, el, value)
                        return True
        except Exception:
            continue
    return False


def _fill_select(driver, selectors, value):
    """Try multiple CSS/XPath selectors to select a dropdown value."""
    for sel in selectors:
        try:
            if sel.startswith("//") or sel.startswith("("):
                els = driver.find_elements(By.XPATH, sel)
            else:
                els = driver.find_elements(By.CSS_SELECTOR, sel)

            for el in els:
                if el.is_displayed():
                    _scroll_to(driver, el)
                    try:
                        Select(el).select_by_value(value)
                        return True
                    except Exception:
                        pass
                    try:
                        Select(el).select_by_visible_text(value)
                        return True
                    except Exception:
                        pass
                    # JS fallback
                    driver.execute_script(
                        "var s=arguments[0],v=arguments[1];"
                        "for(var i=0;i<s.options.length;i++){"
                        "  if(s.options[i].value==v || s.options[i].text.toUpperCase().indexOf(v.toUpperCase())>=0){"
                        "    s.selectedIndex=i;"
                        "    s.dispatchEvent(new Event('change',{bubbles:true}));"
                        "    break;"
                        "  }"
                        "}", el, value
                    )
                    return True
        except Exception:
            continue
    return False


class PassengerFiller:
    def __init__(self, driver):
        self.driver = driver

    def fill_all_passengers(self, passengers, mobile, insurance=False):
        log.info(f"Filling details for {len(passengers)} passenger(s)...")

        _wait_for_passenger_page(self.driver)

        for i, pax in enumerate(passengers):
            # If passenger index > 0, make sure an extra passenger row exists
            if i > 0:
                self._add_passenger_row(i)

            log.info(f"Filling passenger {i+1}: {pax.get('name','')}")
            self._fill_passenger(i, pax)
            time.sleep(0.3)

        self._fill_mobile(mobile)
        self._handle_auto_upgrade()      # Auto Upgrade
        self._handle_confirm_berths()    # Book only if confirm berths
        self._handle_insurance(opt_in=insurance)

        log.info("All passenger and journey preferences filled.")
        return True

    def _add_passenger_row(self, idx):
        """Click '+ Add Passenger' to create an additional row."""
        try:
            existing_rows = self.driver.find_elements(
                By.CSS_SELECTOR, "app-passenger, div.passenger-detail"
            )
            if len(existing_rows) > idx:
                return  # Row already present

            for sel in [
                "app-passenger-input p-panel .prenext",
                "//a[contains(.,'+ Add Passenger') or contains(.,'Add Passenger')]",
                "//span[contains(text(),'+ Add Passenger')]/parent::a",
            ]:
                try:
                    if sel.startswith("//"):
                        btn = self.driver.find_element(By.XPATH, sel)
                    else:
                        btn = self.driver.find_element(By.CSS_SELECTOR, sel)

                    _scroll_to(self.driver, btn)
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.5)
                    log.info(f"Added passenger row {idx+1}")
                    break
                except Exception:
                    continue
        except Exception as e:
            log.warning(f"Could not click add passenger row: {e}")

    def _fill_passenger(self, idx, pax):
        name    = pax.get('name', '')
        age     = str(pax.get('age', ''))
        gender  = pax.get('gender', 'M')
        berth   = pax.get('berth_pref', 'LB')
        id_type = pax.get('id_type', 'AADHAAR')
        id_num  = pax.get('id_number', '')

        n = idx + 1  # 1-based index

        # NAME
        filled = _fill_input(self.driver, [
            f"(//app-passenger)[{n}]//p-autocomplete//input",
            f"(//app-passenger)[{n}]//input[contains(@formcontrolname,'passengerName')]",
            f"(//input[contains(@formcontrolname,'passengerName')])[{n}]",
            f"(//input[@placeholder='Name' or @placeholder='Passenger Name'])[{n}]",
            f"(//app-passenger)[{n}]//input[@type='text'][1]",
        ], name)
        if not filled:
            log.warning(f"PAX {n}: Name field not found")

        time.sleep(0.15)

        # AGE
        filled = _fill_input(self.driver, [
            f"(//app-passenger)[{n}]//input[contains(@formcontrolname,'passengerAge')]",
            f"(//input[contains(@formcontrolname,'passengerAge')])[{n}]",
            f"(//app-passenger)[{n}]//input[@type='number']",
            f"(//input[@placeholder='Age'])[{n}]",
        ], age)
        if not filled:
            log.warning(f"PAX {n}: Age field not found")

        time.sleep(0.15)

        # GENDER
        _fill_select(self.driver, [
            f"(//app-passenger)[{n}]//select[contains(@formcontrolname,'passengerGender')]",
            f"(//select[contains(@formcontrolname,'passengerGender')])[{n}]",
            f"(//app-passenger)[{n}]//select[1]",
        ], gender)

        time.sleep(0.15)

        # BERTH PREFERENCE
        _fill_select(self.driver, [
            f"(//app-passenger)[{n}]//select[contains(@formcontrolname,'passengerBerthChoice')]",
            f"(//select[contains(@formcontrolname,'passengerBerthChoice')])[{n}]",
            f"(//app-passenger)[{n}]//select[2]",
        ], berth)

        time.sleep(0.15)

        # FOOD CHOICE (optional)
        if pax.get('food_choice'):
            _fill_select(self.driver, [
                f"(//app-passenger)[{n}]//select[contains(@formcontrolname,'passengerFoodChoice')]",
                f"(//select[contains(@formcontrolname,'passengerFoodChoice')])[{n}]",
            ], pax.get('food_choice'))

        # ID TYPE & NUMBER (if required)
        if id_num:
            _fill_select(self.driver, [
                f"(//app-passenger)[{n}]//select[contains(@formcontrolname,'passengerCardType')]",
                f"(//select[contains(@formcontrolname,'CardType')])[{n}]",
            ], id_type)

            _fill_input(self.driver, [
                f"(//app-passenger)[{n}]//input[contains(@formcontrolname,'passengerCardNumber')]",
                f"(//input[contains(@formcontrolname,'cardNumber')])[{n}]",
            ], id_num)

        log.info(f"Passenger {n} filled.")

    def _fill_mobile(self, mobile):
        if not mobile:
            return
        # Use direct ID #mobileNumber as top priority
        filled = _fill_input(self.driver, [
            "#mobileNumber",
            "//input[@id='mobileNumber']",
            "input[formcontrolname='mobileNumber']",
            "//input[@formcontrolname='mobileNumber']",
            "//input[@placeholder='Mobile Number' or @placeholder='Enter Mobile No.']",
        ], mobile)
        if filled:
            log.info(f"Mobile filled: {mobile}")
        else:
            log.warning("Mobile field not found")

    def _handle_auto_upgrade(self):
        """Tick 'Consider for Auto Upgrade' checkbox using PrimeNG & modern IRCTC selectors."""
        for sel in [
            "#autoUpgradation",
            "//input[@id='autoUpgradation']",
            "input[formcontrolname='autoUpgradation']",
            "p-checkbox[formcontrolname='autoUpgradation']",
            "p-checkbox[formcontrolname='autoUpgradation'] .ui-chkbox-box",
            "//p-checkbox[contains(.,'Auto Upgrade') or contains(.,'auto upgrade')]",
            "//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'auto upgrade')]/..",
            "//input[@type='checkbox'][contains(@formcontrolname,'autoUpgrade')]",
        ]:
            try:
                el = self.driver.find_element(
                    By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                )
                if el.is_displayed():
                    _scroll_to(self.driver, el)
                    self.driver.execute_script("arguments[0].click();", el)
                    log.info("Auto Upgrade checkbox ticked")
                    return True
            except Exception:
                continue
        log.warning("Auto Upgrade checkbox not found")
        return False

    def _handle_confirm_berths(self):
        """Tick 'Book only if confirm berths are allocated' using PrimeNG & modern IRCTC selectors."""
        for sel in [
            "#confirmberths",
            "//input[@id='confirmberths']",
            "input[formcontrolname='confirmberths']",
            "p-checkbox[formcontrolname='confirmberths']",
            "p-checkbox[formcontrolname='confirmberths'] .ui-chkbox-box",
            "//p-checkbox[contains(.,'confirm berth') or contains(.,'Confirm berth') or contains(.,'confirm berths')]",
            "//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm berth')]/..",
            "//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm berth')]/preceding-sibling::div",
            "//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm berth')]/..//input",
            "//input[@type='checkbox'][contains(@formcontrolname,'confirmBerth') or contains(@formcontrolname,'confirmberth')]",
        ]:
            try:
                el = self.driver.find_element(
                    By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                )
                if el.is_displayed():
                    _scroll_to(self.driver, el)
                    self.driver.execute_script("arguments[0].click();", el)
                    log.info("Confirm Berths preference selected")
                    return True
            except Exception:
                continue
        log.warning("Confirm Berths preference not available for this booking (normal for waitlisted/certain quotas)")
        return False

    def _handle_insurance(self, opt_in=False):
        """Handle travel insurance radio buttons."""
        try:
            radios = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='radio'][name='travelInsuranceOpted-0'], input[name*='travelInsurance']"
            )
            # Typically 2 radios: 0 is Yes, 1 is No
            target_idx = 0 if opt_in else 1
            if len(radios) > target_idx:
                self.driver.execute_script("arguments[0].click();", radios[target_idx])
                log.info(f"Travel insurance set to: {'Yes' if opt_in else 'No'}")
        except Exception:
            pass

    def click_confirm_booking(self):
        """Click Continue button on the passenger page."""
        for sel in [
            "app-passenger-input button.btnDefault.train_Search",
            "app-passenger-input button.search_btn",
            "//button[contains(text(),'Continue') or contains(text(),'CONTINUE')]",
            "//button[contains(text(),'Confirm') or contains(text(),'Next')]",
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
                        log.info("Passenger details submitted via Continue button")
                        time.sleep(3)
                        return True
            except Exception:
                continue

        log.warning("Continue button not found on passenger page")
        return False
