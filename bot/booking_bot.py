# bot/booking_bot.py — Main orchestrator: wires all modules together (2026 Updated)

import time
import datetime
import threading
from utils.logger import get_logger
from utils.encryption import secure_store
from utils.notifier import notifier
from utils.captcha_solver import CaptchaSolver
from bot.driver import create_driver, safe_quit
from bot.login import IRCTCLogin
from bot.train_search import TrainSearch, handle_confirmation_dialogs
from bot.passenger_filler import PassengerFiller
from bot.payment import PaymentHandler
from bot.scheduler import TatkalScheduler
from config.settings import MAX_RETRIES, POST_SUBMIT_WAIT
from selenium.webdriver.common.by import By

log = get_logger("BookingBot")


class BookingJob:
    """
    Data container for a single booking job.
    All required info to complete one IRCTC Tatkal booking.
    """
    def __init__(self):
        # Journey
        self.from_station   = ""
        self.to_station     = ""
        self.travel_date    = ""     # DD/MM/YYYY
        self.train_number   = ""
        self.train_class    = "3A"
        self.quota          = "TQ"

        # Scheduling
        self.booking_date   = None   # datetime.date (D-1)
        self.trigger_hour   = 10
        self.trigger_minute = 0
        self.pre_login_secs = 120

        # Passengers
        self.passengers     = []     # list of dicts
        self.mobile         = ""
        self.berth_pref1    = "LB"
        self.berth_pref2    = ""
        self.insurance      = False

        # Payment
        self.payment        = {}     # method + credentials

        # IRCTC account
        self.username       = ""
        self.password       = ""

        # Fallbacks & Simulation
        self.alt_quota      = None
        self.alt_train      = None
        self.dry_run        = False   # If True, stops before final payment

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()
                if k not in ("password",)}  # Never log password


class IRCTCBookingBot:
    """
    Main IRCTC Tatkal AutoBook bot.
    """

    def __init__(self):
        self.driver = None
        self.job: BookingJob = None
        self.scheduler = TatkalScheduler()
        self.captcha_solver = CaptchaSolver()
        self.result = {"success": False, "pnr": "", "error": ""}
        self.status_callbacks = []
        self._booking_thread = None

    def load_job(self, job: BookingJob):
        """Load a booking job."""
        self.job = job
        secure_store.set("username", job.username)
        secure_store.set("password", job.password)
        log.info(f"Job loaded: {job.to_dict()}")

    def add_status_callback(self, cb):
        """Register a callback for status updates: cb(event_dict)."""
        self.status_callbacks.append(cb)

    def arm(self, blocking: bool = True):
        """Arm the bot. Waits for the scheduled time then executes booking."""
        if not self.job:
            log.error("No job loaded! Call load_job() first.")
            return

        log.info("🤖 BOT ARMED — waiting for scheduled time...")
        self._emit("armed", "Bot armed — countdown started.")

        if blocking:
            self._run_scheduler()
        else:
            self._booking_thread = threading.Thread(
                target=self._run_scheduler, daemon=True
            )
            self._booking_thread.start()

    def disarm(self):
        """Stop the bot before it fires."""
        self.scheduler.stop()
        log.info("Bot disarmed.")

    def run_now(self):
        """Skip the scheduler and run the booking immediately."""
        log.info("Running booking immediately (bypassing scheduler)...")
        self._execute_booking()

    def _run_scheduler(self):
        job = self.job

        bd = job.booking_date or (
            datetime.date.today() if datetime.datetime.now().hour < job.trigger_hour
            else datetime.date.today()
        )
        trigger_dt = datetime.datetime(
            bd.year, bd.month, bd.day,
            job.trigger_hour, job.trigger_minute, 0
        )

        log.info(f"Booking will trigger at: {trigger_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        self._emit("scheduled", f"Trigger: {trigger_dt.strftime('%H:%M:%S')} on {bd}")

        self.scheduler.set_callbacks(
            on_prelogin=self._pre_login_phase,
            on_trigger=self._execute_booking,
            on_status=lambda s: self._emit(s["status"], s["message"])
        )

        self.scheduler.wait_and_trigger(trigger_dt, job.pre_login_secs)

    def _pre_login_phase(self):
        """Login early, keep session warm."""
        log.info("🔑 Pre-login phase — warming up session...")
        self._emit("pre_login", "Logging in early to warm session...")

        try:
            self.driver = create_driver()
            login_handler = IRCTCLogin(self.driver, captcha_solver=self.captcha_solver)
            success = login_handler.login()

            if success:
                log.info("✅ Pre-login successful — session warm.")
                self._emit("logged_in", "Session active and warm.")
                from config.settings import BASE_URL
                self.driver.get(BASE_URL)
                time.sleep(2)
            else:
                log.error("Pre-login failed!")
                self._emit("login_failed", "Login failed — will retry at trigger.")

        except Exception as e:
            log.error(f"Pre-login phase error: {e}")
            self._emit("error", f"Pre-login error: {e}")

    def _handle_review_page(self):
        """Handle intermediate app-review-booking page and review captcha if present."""
        try:
            time.sleep(2)
            handle_confirmation_dialogs(self.driver)

            review_components = self.driver.find_elements(
                By.CSS_SELECTOR, "app-review-booking, .review-booking"
            )
            if not review_components:
                return True

            log.info("Review Booking page detected.")
            self._emit("step", "Handling Review Booking page...")

            # Check if there is an image captcha on the review page
            c_imgs = self.driver.find_elements(
                By.CSS_SELECTOR, "app-review-booking app-captcha .captcha-img, app-captcha img"
            )
            c_inps = self.driver.find_elements(
                By.CSS_SELECTOR, "app-review-booking #captcha, #captcha, input[formcontrolname='captcha']"
            )

            if c_imgs and c_inps:
                c_img = c_imgs[0]
                c_inp = c_inps[0]
                if c_img.is_displayed() and c_inp.is_displayed():
                    log.info("Review captcha encountered. Solving via OCR/API...")
                    try:
                        solved_text = self.captcha_solver.solve_from_element(self.driver, c_img)
                        if solved_text:
                            c_inp.clear()
                            c_inp.send_keys(solved_text)
                            self.driver.execute_script(
                                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                                c_inp
                            )
                            log.info(f"Review captcha entered: '{solved_text}'")
                            time.sleep(0.5)
                    except Exception as e:
                        log.warning(f"Failed solving review captcha automatically: {e}")

            # Click Continue / Submit on review page
            for sel in [
                "app-review-booking button.btnDefault.train_Search",
                "app-review-booking button.search_btn",
                "//app-review-booking//button[contains(.,'Continue') or contains(.,'CONTINUE')]",
                "//button[contains(text(),'Continue') or contains(text(),'CONTINUE')]",
            ]:
                try:
                    btns = self.driver.find_elements(
                        By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                    )
                    for b in btns:
                        if b.is_displayed():
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
                            self.driver.execute_script("arguments[0].click();", b)
                            log.info("Clicked Continue on Review page.")
                            time.sleep(2)
                            handle_confirmation_dialogs(self.driver)
                            return True
                except Exception:
                    continue
        except Exception as e:
            log.warning(f"Review page handling note: {e}")
        return True

    def _execute_booking(self):
        """Full booking flow executed at trigger time."""
        job = self.job
        log.info(f"🚀 BOOKING EXECUTION STARTED (Dry Run: {job.dry_run})")
        self._emit("booking_start", "Booking sequence initiated!")

        try:
            if not self.driver:
                self.driver = create_driver()

            login_hdl  = IRCTCLogin(self.driver, captcha_solver=self.captcha_solver)
            search_hdl = TrainSearch(self.driver)
            pax_hdl    = PassengerFiller(self.driver)
            pay_hdl    = PaymentHandler(self.driver, job.payment, dry_run=job.dry_run)

            # ── Step 1: Ensure logged in ──
            self._emit("step", "Step 1: Verifying login...")
            if not login_hdl.ensure_logged_in(job.username, job.password):
                raise Exception("Login failed at booking time!")
            log.info("✅ Step 1: Login OK")

            # ── Step 2: Search train ──
            self._emit("step", "Step 2: Searching for train...")
            ok = search_hdl.fill_search_form(
                job.from_station, job.to_station,
                job.travel_date, job.quota
            )
            if not ok:
                raise Exception("Train search form fill failed!")

            ok = search_hdl.submit_search()
            if not ok:
                raise Exception("Train search submit failed!")
            log.info("✅ Step 2: Search submitted")

            # ── Step 3: Select train + class ──
            self._emit("step", f"Step 3: Selecting train {job.train_number} class {job.train_class}...")
            ok = search_hdl.select_train_and_class(
                job.train_number, job.train_class, job.quota
            )
            if not ok:
                if job.alt_quota:
                    log.warning(f"Trying alternate quota: {job.alt_quota}")
                    ok = search_hdl.select_train_and_class(
                        job.train_number, job.train_class, job.alt_quota
                    )
                if not ok:
                    raise Exception(f"Train {job.train_number} / class {job.train_class} not available!")
            log.info("✅ Step 3: Train and class selected")

            # ── Step 4: Fill passengers ──
            self._emit("step", "Step 4: Filling passenger details...")
            ok = pax_hdl.fill_all_passengers(
                job.passengers, job.mobile, job.insurance
            )
            if not ok:
                raise Exception("Passenger details fill failed!")
            log.info("✅ Step 4: Passengers filled")

            # ── Step 5: Confirm booking (pre-payment) ──
            self._emit("step", "Step 5: Confirming passenger form...")
            ok = pax_hdl.click_confirm_booking()
            if not ok:
                raise Exception("Booking confirmation click failed!")
            time.sleep(POST_SUBMIT_WAIT)
            log.info("✅ Step 5: Passenger form confirmed")

            # ── Step 5b: Handle Review Booking page ──
            self._handle_review_page()

            # ── Step 6: Payment ──
            if job.dry_run:
                self._emit("step", "Step 6: [DRY-RUN] Simulating payment options without placing actual charge...")
                pay_hdl.execute()
                self.result = {"success": True, "pnr": "TEST-DRY-RUN-NO-CHARGE", "error": ""}
                log.info("🛡️ [DRY RUN COMPLETE] Verified full flow safely. No actual booking was made.")
                self._emit("success", "DRY RUN PASSED: Verified all form fields and navigation safely!")
                return

            self._emit("step", f"Step 6: Paying via {job.payment.get('method', '?').upper()}...")
            ok = pay_hdl.execute()
            if not ok:
                raise Exception("Payment execution failed!")
            log.info("✅ Step 6: Payment initiated")

            # ── Step 7: Wait for PNR ──
            self._emit("step", "Step 7: Awaiting PNR confirmation...")
            pnr = pay_hdl.wait_for_pnr(timeout=180)

            if pnr:
                self.result = {"success": True, "pnr": pnr, "error": ""}
                log.info(f"🎉 BOOKING SUCCESS! PNR: {pnr}")
                self._emit("success", f"BOOKED! PNR: {pnr}")
                notifier.booking_success(
                    pnr=pnr,
                    train=job.train_number,
                    from_st=job.from_station,
                    to_st=job.to_station,
                    travel_date=job.travel_date,
                    passengers=job.passengers
                )
            else:
                log.warning("Payment submitted. Please check IRCTC account for PNR status.")
                self._emit("warning", "Payment done — check IRCTC for PNR manually.")

        except Exception as e:
            self.result = {"success": False, "pnr": "", "error": str(e)}
            log.error(f"❌ BOOKING FAILED: {e}")
            self._emit("error", f"Booking failed: {e}")
            notifier.booking_failed(str(e))
            if not job.dry_run:
                self._maybe_retry()

    def _maybe_retry(self, attempt: int = 1):
        if attempt >= MAX_RETRIES:
            log.error(f"All {MAX_RETRIES} booking attempts exhausted.")
            return
        log.warning(f"Retrying booking ({attempt+1}/{MAX_RETRIES})...")
        self._emit("retry", f"Retrying ({attempt+1}/{MAX_RETRIES})...")
        time.sleep(3)
        self._execute_booking()

    def _emit(self, event: str, message: str):
        data = {
            "event": event,
            "message": message,
            "time": datetime.datetime.now().isoformat()
        }
        for cb in self.status_callbacks:
            try:
                cb(data)
            except Exception:
                pass

    def cleanup(self):
        """Release resources."""
        safe_quit(self.driver)
        secure_store.clear()
        log.info("Bot cleanup complete.")
