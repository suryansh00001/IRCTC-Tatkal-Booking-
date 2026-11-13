# bot/passenger_filler.py — IRCTC Passenger Form Filler (2026 Updated)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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


def _wait_for_passenger_page(driver, timeout=12):
    """Wait until we're on the passenger details page reactively."""
    log.info(f"Waiting for passenger page... Current: {driver.current_url}")
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: "psgninput" in (d.current_url or "") or
                      len(d.find_elements(By.CSS_SELECTOR, "app-passenger-input, app-passenger, #mobileNumber")) > 0
        )
        log.info("Passenger form active and ready.")
        return True
    except Exception:
        if "train-list" in (driver.current_url or ""):
            raise Exception(f"Cannot fill passenger details — still on train-list search page ({driver.current_url})")
        return False


BATCH_PASSENGER_JS = """
var passengers = arguments[0] || [];
var mobile = arguments[1] || '';
var insurance = arguments[2] || false;

function setAngularVal(el, val) {
    if (!el) return false;
    el.focus();
    try {
        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(el, String(val));
    } catch(e) {
        el.value = String(val);
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, data: String(val) }));
    el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
}

function setSelectVal(el, val) {
    if (!el) return false;
    val = String(val || '').toUpperCase().trim();
    if (!val) return false;
    for (var i = 0; i < el.options.length; i++) {
        var optVal = (el.options[i].value || '').toUpperCase();
        var optTxt = (el.options[i].text || '').toUpperCase();
        if (optVal === val || optTxt === val || optTxt.includes(val) ||
            (val === 'LB' && optTxt.includes('LOWER')) ||
            (val === 'MB' && optTxt.includes('MIDDLE')) ||
            (val === 'UB' && optTxt.includes('UPPER')) ||
            (val === 'SL' && optTxt.includes('SIDE LOWER')) ||
            (val === 'SU' && optTxt.includes('SIDE UPPER')) ||
            (val === 'M' && optTxt.includes('MALE')) ||
            (val === 'F' && optTxt.includes('FEMALE')) ||
            (val === 'IN' && (optVal === 'IN' || optTxt.includes('INDIA')))) {
            el.selectedIndex = i;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
    }
    return false;
}

// 1. Ensure enough passenger rows exist for all passengers
for (var k = 1; k < passengers.length; k++) {
    var curRows = document.querySelectorAll('app-passenger, div.passenger-detail');
    if (curRows.length <= k) {
        var addBtn = document.querySelector("a.prenext, app-passenger-input p-panel .prenext, a[href*='addPassenger']");
        if (!addBtn) {
            var links = document.querySelectorAll("a, span, button");
            for (var l = 0; l < links.length; l++) {
                if (links[l].textContent.includes("Add Passenger")) {
                    addBtn = links[l];
                    break;
                }
            }
        }
        if (addBtn) addBtn.click();
    }
}

var rows = document.querySelectorAll('app-passenger, div.passenger-detail');
var filled = 0;

for (var i = 0; i < passengers.length; i++) {
    var p = passengers[i];
    var row = rows[i] || rows[0];
    if (!row) break;

    var nameIn = row.querySelector("p-autocomplete input, input[formcontrolname='passengerName'], input[placeholder*='Name'], input[type='text']");
    var ageIn = row.querySelector("input[formcontrolname='passengerAge'], input[placeholder*='Age'], input[type='number']");
    var genderSel = row.querySelector("select[formcontrolname='passengerGender']");
    var berthSel = row.querySelector("select[formcontrolname='passengerBerthChoice']");
    var nationalitySel = row.querySelector("select[formcontrolname='passengerNationality']");

    if (nameIn) setAngularVal(nameIn, p.name);
    if (ageIn) setAngularVal(ageIn, p.age);
    if (genderSel) setSelectVal(genderSel, p.gender);
    if (berthSel) setSelectVal(berthSel, p.berth_pref);
    if (nationalitySel) setSelectVal(nationalitySel, 'IN');
    filled++;
}

// 2. Mobile number
if (mobile) {
    var mobIn = document.querySelector("#mobileNumber, input[formcontrolname='mobileNumber'], input[placeholder*='Mobile']");
    setAngularVal(mobIn, mobile);
}

// 3. Auto Upgrade checkbox
var upg = document.querySelector("#autoUpgradation, input[formcontrolname='autoUpgradation']");
if (upg) {
    if (!upg.checked) upg.click();
} else {
    var upgBox = document.querySelector("p-checkbox[formcontrolname='autoUpgradation'] .ui-chkbox-box, p-checkbox[formcontrolname='autoUpgradation']");
    if (upgBox) upgBox.click();
}

// 4. Confirm Berths checkbox
var cb = document.querySelector("#confirmberths, input[formcontrolname='confirmberths']");
if (cb) {
    if (!cb.checked) cb.click();
} else {
    var cbBox = document.querySelector("p-checkbox[formcontrolname='confirmberths'] .ui-chkbox-box, p-checkbox[formcontrolname='confirmberths']");
    if (cbBox) cbBox.click();
}

// 5. Travel Insurance
var insRadios = document.querySelectorAll("input[type='radio'][name*='travelInsurance']");
if (insRadios.length > 1) {
    (insurance ? insRadios[0] : insRadios[1]).click();
}

// 6. Payment Mode radio on passenger form
var payMethod = arguments[3] || 'upi';
var payRadios = document.querySelectorAll("p-radiobutton[name='paymentType'], input[name='paymentType'], p-radiobutton[formcontrolname='paymentType']");
if (payRadios.length >= 2) {
    if (payMethod.toLowerCase().includes('upi')) {
        var upiBox = payRadios[1].querySelector(".ui-radiobutton-box") || payRadios[1];
        upiBox.click();
    } else {
        var cardBox = payRadios[0].querySelector(".ui-radiobutton-box") || payRadios[0];
        cardBox.click();
    }
}

return { success: true, count: filled };
"""


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

        # 1. Add extra passenger rows if needed
        for i in range(1, len(passengers)):
            self._add_passenger_row(i)

        # 2. Rapidly populate each passenger row with verified modern selectors
        rows = self.driver.find_elements(By.CSS_SELECTOR, "app-passenger")
        if not rows:
            rows = self.driver.find_elements(By.CSS_SELECTOR, "div.passenger-detail, div.Layer_7")

        for i, pax in enumerate(passengers):
            row = rows[i] if len(rows) > i else rows[0]
            name = pax.get('name', '')
            age = str(pax.get('age', ''))
            gender = pax.get('gender', 'M').upper()
            berth = pax.get('berth_pref', 'LB').upper()

            log.info(f"Filling passenger {i+1}: {name} ({age}, {gender}, {berth})")

            # NAME (Directly inside p-autocomplete — keystrokes commit to PrimeNG model)
            try:
                name_in = row.find_element(
                    By.CSS_SELECTOR,
                    "p-autocomplete[formcontrolname='passengerName'] input, input[formcontrolname='passengerName'], input[placeholder*='Full Name']"
                )
                name_in.click()
                name_in.clear()
                name_in.send_keys(name)
                name_in.send_keys(Keys.TAB)
            except Exception as e:
                log.warning(f"Pax {i+1} Name field error: {e}")

            # AGE
            try:
                age_in = row.find_element(
                    By.CSS_SELECTOR,
                    "input[formcontrolname='passengerAge'], input[placeholder='Age']"
                )
                age_in.click()
                age_in.clear()
                age_in.send_keys(age)
                age_in.send_keys(Keys.TAB)
            except Exception as e:
                log.warning(f"Pax {i+1} Age field error: {e}")

            # GENDER
            try:
                gender_sel = row.find_element(
                    By.CSS_SELECTOR,
                    "select[formcontrolname='passengerGender']"
                )
                Select(gender_sel).select_by_value(gender)
            except Exception as e:
                log.warning(f"Pax {i+1} Gender field error: {e}")

            # BERTH PREFERENCE (Explicitly passengerBerthChoice — leaving passengerNationality untouched!)
            try:
                berth_sel = row.find_element(
                    By.CSS_SELECTOR,
                    "select[formcontrolname='passengerBerthChoice']"
                )
                Select(berth_sel).select_by_value(berth)
            except Exception as e:
                log.warning(f"Pax {i+1} Berth field error: {e}")

        # 3. Mobile Number
        if mobile:
            try:
                mob_in = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "#mobileNumber, input[formcontrolname='mobileNumber']"
                )
                mob_in.click()
                mob_in.clear()
                mob_in.send_keys(str(mobile))
                mob_in.send_keys(Keys.TAB)
                log.info(f"Mobile number entered: {mobile}")
            except Exception as e:
                log.warning(f"Mobile field error: {e}")

        # 4. Checkboxes & Preferences via Fast Script (<5ms)
        PREFERENCES_JS = """
        var insurance = arguments[0] || false;
        // Auto Upgrade
        var upg = document.querySelector("#autoUpgradation, input[formcontrolname='autoUpgradation']");
        if (upg && !upg.checked) upg.click();
        var upgBox = document.querySelector("p-checkbox[formcontrolname='autoUpgradation'] .ui-chkbox-box");
        if (upgBox && !upgBox.classList.contains('ui-state-active')) upgBox.click();

        // Confirm Berths
        var cb = document.querySelector("#confirmberths, input[formcontrolname='confirmberths']");
        if (cb && !cb.checked) cb.click();
        var cbBox = document.querySelector("p-checkbox[formcontrolname='confirmberths'] .ui-chkbox-box");
        if (cbBox && !cbBox.classList.contains('ui-state-active')) cbBox.click();

        // Travel Insurance (0 = Yes, 1 = No)
        var insRadios = document.querySelectorAll("input[type='radio'][name*='travelInsurance']");
        if (insRadios.length > 1) {
            (insurance ? insRadios[0] : insRadios[1]).click();
        }
        """
        try:
            self.driver.execute_script(PREFERENCES_JS, bool(insurance))
        except Exception:
            pass

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
        """Click Continue button on the passenger page with resilient polling and scrolling."""
        log.info("Attempting to click Continue/Confirm button...")

        # 1. Scroll to the bottom of the page where the Continue button is located
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.3)

        # 2. Resilient JS button search (matching Continue, Proceed, Next, Confirm)
        CLICK_CONTINUE_JS = """
        // Try finding by button text content
        var btns = Array.from(document.querySelectorAll("button, a.btnDefault, input[type='submit']"));
        for (var i = 0; i < btns.length; i++) {
            var b = btns[i];
            var txt = (b.innerText || b.textContent || b.value || '').trim().toUpperCase();
            if (txt.includes("CONTINUE") || txt.includes("PROCEED") || txt.includes("CONFIRM") || txt.includes("NEXT")) {
                b.scrollIntoView({block: 'center'});
                b.click();
                return { success: true, text: txt, selector: 'text-match' };
            }
        }
        // Try standard form submit or train_Search button
        var submitBtn = document.querySelector("button.train_Search.btnDefault, button.train_Search, form button[type='submit']");
        if (submitBtn) {
            submitBtn.scrollIntoView({block: 'center'});
            submitBtn.click();
            return { success: true, text: 'Submit/train_Search', selector: 'class-match' };
        }
        return { success: false };
        """

        start_time = time.time()
        while time.time() - start_time < 6.0:
            try:
                res = self.driver.execute_script(CLICK_CONTINUE_JS)
                if res and res.get("success"):
                    log.info(f"Passenger form submitted via Continue button ({res})")
                    time.sleep(1.0)
                    from bot.train_search import handle_confirmation_dialogs
                    handle_confirmation_dialogs(self.driver)
                    return True
            except Exception as e:
                log.warning(f"JS Continue button click notice: {e}")

            # Fallback XPath / CSS selectors
            for sel in [
                "//button[contains(normalize-space(),'Continue') or contains(.,'Continue') or contains(.,'CONTINUE')]",
                "button.btnDefault.train_Search",
                "button.train_Search",
                "app-passenger-input button[type='submit']",
                "form button[type='submit']",
                "//button[contains(.,'Confirm') or contains(.,'Proceed') or contains(.,'Next')]",
            ]:
                try:
                    btns = self.driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                    for btn in btns:
                        if btn.is_displayed():
                            _scroll_to(self.driver, btn)
                            self.driver.execute_script("arguments[0].click();", btn)
                            log.info(f"Passenger form submitted via fallback selector: {sel}")
                            time.sleep(1.0)
                            from bot.train_search import handle_confirmation_dialogs
                            handle_confirmation_dialogs(self.driver)
                            return True
                except Exception:
                    continue

            time.sleep(0.4)

        log.warning("Continue button not found on passenger page after retrying.")
        return False
