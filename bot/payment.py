# bot/payment.py — Handles IRCTC Payment Flow (2026 Updated)

import time
import re
from utils.logger import get_logger
from config.settings import PAYMENT_TIMEOUT

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

log = get_logger("Payment")


class PaymentHandler:
    """
    Handles IRCTC payment flow.
    Supports: UPI, Debit/Credit Card, Net Banking, IRCTC eWallet.
    Includes dry_run safe mode to test without deducting money.
    """

    def __init__(self, driver, payment_config: dict, dry_run: bool = False):
        self.driver = driver
        self.wait = WebDriverWait(driver, PAYMENT_TIMEOUT)
        self.short_wait = WebDriverWait(driver, 15)
        self.config = payment_config
        self.dry_run = dry_run

    def execute(self) -> bool:
        """Main payment execution. Returns True if payment initiated (or dry-run succeeded)."""
        method = self.config.get("method", "upi").lower()
        log.info(f"Initiating payment flow via: {method.upper()} (Dry Run: {self.dry_run})")

        try:
            self._wait_for_payment_page()

            if self.dry_run:
                log.info("🛡️ [DRY RUN ACTIVE] Opening payment gateway to load QR Code on screen...")
                self._select_modern_payment_category(method)
                self._select_provider(["BHIM", "PAYTM", "RAZORPAY", "PHONEPE", "IPAY", "AIRPAY"])
                self._click_pay_and_book_button()
                log.info("📱 QR Code / Payment Gateway loaded on screen!")
                log.info("🛡️ [DRY RUN] Gateway verified. To book, scan the QR with any UPI app; otherwise let it expire safely.")
                return True

            dispatch = {
                "upi":        self._pay_upi,
                "card":       self._pay_card,
                "netbanking": self._pay_netbanking,
                "nb":         self._pay_netbanking,
                "wallet":     self._pay_wallet,
            }

            handler = dispatch.get(method)
            if not handler:
                log.error(f"Unknown payment method: {method}")
                return False

            result = handler()
            if result:
                log.info("✅ Payment submission completed.")
            return result

        except Exception as e:
            log.error(f"Payment execution failed: {e}")
            return False

    def _select_modern_payment_category(self, method: str):
        """Select left payment category in app-payment-options (#pay-type .bank-type)."""
        category_map = {
            "upi": ["BHIM", "UPI", "USSD"],
            "card": ["Multiple Payment Service", "Payment Gateway", "Debit Card"],
            "netbanking": ["Netbanking", "Net Banking"],
            "nb": ["Netbanking", "Net Banking"],
            "wallet": ["IRCTC eWallet", "eWallet", "E-Wallet"],
        }
        keywords = category_map.get(method, ["BHIM", "UPI"])

        # Try modern #pay-type .bank-type first
        categories = self.driver.find_elements(
            By.CSS_SELECTOR, "#pay-type .bank-type, .bank-type, app-payment-options .bank-type"
        )
        for cat in categories:
            for kw in keywords:
                if kw.upper() in cat.text.upper():
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cat)
                    self.driver.execute_script("arguments[0].click();", cat)
                    log.info(f"Selected payment category: {cat.text.strip()}")
                    time.sleep(0.2)
                    return True

        # Fallback to general label search
        return self._click_payment_option(keywords)

    def _pay_upi(self) -> bool:
        upi_id = self.config.get("upi_id", "")
        self._select_modern_payment_category("upi")

        # Select provider (e.g. Paytm / Bhim / PayU)
        self._select_provider(["BHIM", "PAYTM", "RAZORPAY", "PHONEPE"])

        # Click 'Pay & Book' button
        if not self._click_pay_and_book_button():
            log.warning("Pay & Book button not clicked; trying standard submit.")

        if upi_id:
            try:
                # If redirected to a page asking for VPA/UPI ID
                upi_field = self.short_wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        "input[placeholder*='UPI'], input[name*='upi'], input[id*='upi'], input[placeholder*='vpa']"
                    ))
                )
                upi_field.clear()
                upi_field.send_keys(upi_id)
                time.sleep(0.5)
                self._click_button_by_text(["Verify", "Pay Now", "Proceed", "Submit"])
                log.info(f"UPI request dispatched to: {upi_id}")
            except Exception:
                log.info("Proceed with UPI on payment gateway screen.")

        log.info("⚠️ Please approve the UPI payment request on your phone!")
        return True

    def _pay_card(self) -> bool:
        cfg = self.config
        self._select_modern_payment_category("card")
        self._select_provider(["PAYTM", "HDFC", "ICICI", "RAZORPAY"])
        self._click_pay_and_book_button()

        # If card inputs are visible directly
        card_num = cfg.get("card_number", "").replace(" ", "").replace("-", "")
        if card_num:
            self._fill_field_by_attrs(["cardNumber", "card_number", "cardNo"], card_num)
            if cfg.get("card_expiry"):
                self._fill_field_by_attrs(["expiry", "expiryDate", "cardExpiry"], cfg["card_expiry"].replace("/", ""))
            if cfg.get("card_cvv"):
                self._fill_field_by_attrs(["cvv", "CVV", "cardCvv"], cfg["card_cvv"])
            self._click_button_by_text(["Pay Now", "Make Payment", "Proceed"])

        log.info("⚠️ Complete any 3D-Secure / OTP prompt on the gateway screen.")
        return True

    def _pay_netbanking(self) -> bool:
        self._select_modern_payment_category("netbanking")
        bank = self.config.get("bank", "SBI")
        self._select_provider([bank, "State Bank of India", "HDFC", "ICICI"])
        self._click_pay_and_book_button()
        log.info(f"Redirecting to Net Banking ({bank}). Complete authentication manually.")
        return True

    def _pay_wallet(self) -> bool:
        self._select_modern_payment_category("wallet")
        self._click_pay_and_book_button()

        # Confirm eWallet popup if shown
        for sel in [
            "app-ewallet-confirm button.search_btn",
            "//button[contains(text(),'CONFIRM') or contains(text(),'Confirm')]",
        ]:
            try:
                btn = self.driver.find_element(
                    By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                )
                if btn.is_displayed():
                    btn.click()
                    log.info("Confirmed eWallet modal.")
                    break
            except Exception:
                pass
        return True

    def _select_provider(self, preferred_keywords: list):
        """Select a bank or payment aggregator provider (#bank-type .bank-text)."""
        time.sleep(0.5)
        providers = self.driver.find_elements(
            By.CSS_SELECTOR, "#bank-type .bank-text, #bank-type .pay_tax_text, .bank-text"
        )
        for kw in preferred_keywords:
            for p in providers:
                if kw.upper() in p.text.upper():
                    try:
                        self.driver.execute_script("arguments[0].click();", p)
                        log.info(f"Selected provider: {p.text.strip()}")
                        time.sleep(0.5)
                        return True
                    except Exception:
                        pass
        return False

    def _click_pay_and_book_button(self) -> bool:
        """Click the final 'Pay & Book' button."""
        for sel in [
            "button.btn-primary.ng-star-inserted",
            "app-payment-options button.btn-primary",
            "//button[contains(text(),'Pay & Book') or contains(text(),'Pay and Book')]",
            "//button[contains(@class,'btn-primary') and contains(.,'Pay')]",
        ]:
            try:
                btn = self.driver.find_element(
                    By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                )
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    self.driver.execute_script("arguments[0].click();", btn)
                    log.info("Clicked 'Pay & Book' button.")
                    time.sleep(2)
                    return True
            except Exception:
                continue
        return False

    def wait_for_pnr(self, timeout: int = 180) -> str:
        """Wait for the booking confirmation page and extract 10-digit PNR."""
        log.info("Awaiting booking confirmation and PNR capture...")
        wait = WebDriverWait(self.driver, timeout)

        try:
            pnr_element = wait.until(
                EC.presence_of_element_located((By.XPATH,
                    "//*[contains(text(), 'PNR') or contains(@class, 'pnr')]"
                    "[string-length(normalize-space(text())) >= 10]"
                ))
            )
            text = pnr_element.text.strip()
            match = re.search(r'\b\d{10}\b', text)
            if match:
                pnr = match.group()
                log.info(f"🎉 PNR successfully captured: {pnr}")
                return pnr
            return text
        except TimeoutException:
            try:
                pnr_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".pnr-no, #pnrNo, [class*='pnr']"
                )
                return pnr_el.text.strip()
            except Exception:
                pass
            log.warning("PNR capture timed out. Please check IRCTC account manually.")
            return ""

    def _wait_for_payment_page(self):
        """Wait for payment options page to load reactively."""
        for _ in range(25):
            curr = self.driver.current_url or ""
            if "payment" in curr and "review" not in curr:
                break
            if len(self.driver.find_elements(By.CSS_SELECTOR, "app-payment-options, #pay-type, .bank-type")) > 0:
                break
            time.sleep(0.2)

    def _click_payment_option(self, labels: list):
        for label in labels:
            try:
                elements = self.driver.find_elements(
                    By.XPATH, f"//*[contains(translate(text(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{label.upper()}')]"
                )
                for el in elements:
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        log.info(f"Payment option selected: {label}")
                        time.sleep(0.5)
                        return True
            except Exception:
                continue
        return False

    def _click_button_by_text(self, labels: list):
        for label in labels:
            try:
                btns = self.driver.find_elements(
                    By.XPATH, f"//button[contains(text(),'{label}')]"
                )
                for btn in btns:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        return True
            except Exception:
                continue
        return False

    def _fill_field_by_attrs(self, names: list, val: str):
        for name in names:
            try:
                inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, f"input[name*='{name}'], input[id*='{name}']"
                )
                for inp in inputs:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(val)
                        return True
            except Exception:
                continue
        return False
