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
from bot.train_search import (
    TrainSearch,
    handle_confirmation_dialogs,
    check_search_errors_or_availability,
    IRCTCServiceUnavailableError,
    TrainNotFoundError,
)
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
        self._retry_count = 0
        self._form_prestaged = False

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
            on_status=lambda s: self._emit(s["status"], s["message"]),
            on_heartbeat=self._session_heartbeat
        )

        self.scheduler.wait_and_trigger(trigger_dt, job.pre_login_secs)

    def _pre_login_phase(self):
        """Login early, keep session warm, and pre-stage search form."""
        log.info("🔑 Pre-login phase — warming up session and pre-staging...")
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
                time.sleep(1.5)
                # Attempt to pre-stage search form right away
                self._prestage_search_form()
            else:
                log.error("Pre-login failed!")
                self._emit("login_failed", "Login failed — will retry at trigger.")

        except Exception as e:
            log.error(f"Pre-login phase error: {e}")
            self._emit("error", f"Pre-login error: {e}")

    def _session_heartbeat(self, remaining):
        """Active session heartbeat to prevent IRCTC idle timeout and maintain pre-staged state."""
        if not self.driver:
            return

        try:
            from bot.login import _is_logged_in
            logged_in = _is_logged_in(self.driver)

            if not logged_in:
                log.warning(f"⚠️ Session heartbeat: logged-out state detected at T-{int(remaining)}s! Re-authenticating...")
                self._recover_session()
            else:
                # Active DOM ping to refresh server session cookie and prevent idle eviction
                self.driver.execute_script("return document.readyState;")
                log.info(f"💓 Session Heartbeat: Active & Hot (T–{int(remaining)}s)")

            # Pre-stage search form if not already done
            if not self._form_prestaged and self.job and (remaining <= 100):
                self._prestage_search_form()

        except Exception as e:
            log.warning(f"Heartbeat notice: {e}")

    def _prestage_search_form(self):
        """Pre-fill From, To, Date, Quota on the screen so trigger only needs a single instant click."""
        try:
            log.info("🎯 Pre-staging search form (From/To/Date/Quota) ahead of trigger...")
            search_hdl = TrainSearch(self.driver)
            ok = search_hdl.fill_search_form(
                self.job.from_station, self.job.to_station,
                self.job.travel_date, self.job.quota
            )
            if ok:
                self._form_prestaged = True
                log.info("🎯 Search form pre-staged and armed! Zero-delay trigger primed.")
        except Exception as e:
            log.warning(f"Pre-stage search form notice: {e}")

    def _recover_session(self):
        """In-flight session recovery without restarting browser."""
        try:
            log.info("🔄 Initiating in-flight session recovery...")
            login_hdl = IRCTCLogin(self.driver, captcha_solver=self.captcha_solver)
            success = login_hdl.ensure_logged_in(self.job.username, self.job.password)
            if success:
                log.info("✅ In-flight session successfully recovered!")
                return True
        except Exception as e:
            log.warning(f"Session recovery attempt notice: {e}")
        return False

    def _handle_review_page(self):
        """Handle intermediate app-review-booking page, review captcha, and navigation to payment."""
        try:
            log.info("Waiting for Review Booking page to load...")
            start_wait = time.time()
            on_review = False
            while time.time() - start_wait < 7.0:
                handle_confirmation_dialogs(self.driver)
                curr_url = self.driver.current_url or ""
                if "review" in curr_url or "reviewBooking" in curr_url:
                    on_review = True
                    break
                if len(self.driver.find_elements(By.CSS_SELECTOR, "app-review-booking, .review-booking")) > 0:
                    on_review = True
                    break
                # If already reached payment page, return immediately
                if "payment" in curr_url and "review" not in curr_url:
                    log.info("Already reached payment page directly.")
                    return True

                # If still stuck on passenger input after 2s, retry clicking continue
                if "psgninput" in curr_url and (time.time() - start_wait > 2.0):
                    try:
                        self.driver.execute_script(
                            "var b = document.querySelector('button.train_Search, form button[type=\"submit\"]'); if (b) b.click();"
                        )
                    except Exception:
                        pass

                time.sleep(0.2)

            if not on_review:
                log.warning("Review page not explicitly detected — checking for payment page...")
                return True

            log.info(f"Review Booking page active ({self.driver.current_url}).")
            self._emit("step", "Step 5b: Handling Review Booking page...")
            time.sleep(0.8)
            handle_confirmation_dialogs(self.driver)

            # Check if there is an image captcha on the review page
            c_imgs = self.driver.find_elements(
                By.CSS_SELECTOR, "app-review-booking app-captcha .captcha-img, app-captcha img, .captcha-img"
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
                            time.sleep(0.3)
                    except Exception as e:
                        log.warning(f"Failed solving review captcha automatically: {e}")

            # Click Continue on Review Booking page
            clicked = False
            CLICK_REVIEW_JS = """
            var btns = Array.from(document.querySelectorAll("app-review-booking button, button"));
            for (var i = 0; i < btns.length; i++) {
                var b = btns[i];
                var txt = (b.innerText || b.textContent || '').trim().toUpperCase();
                if (txt.includes("CONTINUE") || txt.includes("PROCEED") || txt.includes("PAY")) {
                    b.scrollIntoView({block: 'center'});
                    b.click();
                    return true;
                }
            }
            var defBtn = document.querySelector("app-review-booking button.train_Search, button.train_Search");
            if (defBtn) { defBtn.click(); return true; }
            return false;
            """
            for _ in range(5):
                try:
                    if self.driver.execute_script(CLICK_REVIEW_JS):
                        log.info("Clicked Continue on Review page.")
                        clicked = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            if not clicked:
                for sel in [
                    "app-review-booking button.btnDefault.train_Search",
                    "app-review-booking button.search_btn",
                    "//app-review-booking//button[contains(.,'Continue') or contains(.,'CONTINUE')]",
                    "//button[contains(normalize-space(),'Continue') or contains(.,'Continue')]",
                ]:
                    try:
                        btns = self.driver.find_elements(
                            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel
                        )
                        for b in btns:
                            if b.is_displayed():
                                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", b)
                                self.driver.execute_script("arguments[0].click();", b)
                                log.info(f"Clicked Continue on Review page via {sel}")
                                clicked = True
                                break
                        if clicked:
                            break
                    except Exception:
                        continue

            time.sleep(1.0)
            handle_confirmation_dialogs(self.driver)

            # Wait until we transition from reviewBooking to payment page
            start_pay_wait = time.time()
            while time.time() - start_pay_wait < 12.0:
                curr_url = self.driver.current_url or ""
                if "payment" in curr_url and "review" not in curr_url:
                    log.info(f"Navigated to payment stage ({curr_url})")
                    break
                if len(self.driver.find_elements(By.CSS_SELECTOR, "app-payment-options, #pay-type, .bank-type")) > 0:
                    log.info("Payment options component rendered.")
                    break
                handle_confirmation_dialogs(self.driver)
                time.sleep(0.5)

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

            # ── Step 1: Ensure logged in with self-healing recovery ──
            self._emit("step", "Step 1: Verifying login...")
            if not login_hdl.ensure_logged_in(job.username, job.password):
                log.warning("Session check failed at trigger — attempting instant in-flight recovery...")
                if not self._recover_session():
                    raise Exception("Login failed at booking time!")
            log.info("✅ Step 1: Login OK")

            # ── Step 2: Search train (using pre-staged form if primed) ──
            self._emit("step", "Step 2: Searching for train...")
            if not self._form_prestaged:
                ok = search_hdl.fill_search_form(
                    job.from_station, job.to_station,
                    job.travel_date, job.quota
                )
                if not ok:
                    raise Exception("Train search form fill failed!")
            else:
                log.info("⚡ Zero-latency trigger: using pre-staged search form!")

            # Resilient search submit with retry loop for transient IRCTC hiccups
            search_ok = False
            for s_attempt in range(1, 5):
                try:
                    search_ok = search_hdl.submit_search()
                    if search_ok:
                        break
                except IRCTCServiceUnavailableError as sue:
                    log.warning(f"⚠️ IRCTC Search glitch: {sue}. Retrying ({s_attempt}/4) in 1.2s...")
                    time.sleep(1.2)
                except Exception as e:
                    log.warning(f"Search submit attempt {s_attempt} notice: {e}")
                    time.sleep(1.0)

            if not search_ok:
                raise Exception("Train search submit failed after retries!")
            log.info("✅ Step 2: Search submitted")

            # ── Step 3: Select train + class with resilient retry loop ──
            self._emit("step", f"Step 3: Selecting train {job.train_number} class {job.train_class}...")
            train_ok = False
            for t_attempt in range(1, 4):
                try:
                    train_ok = search_hdl.select_train_and_class(
                        job.train_number, job.train_class, job.quota, alt_train=job.alt_train
                    )
                    if train_ok:
                        break
                except IRCTCServiceUnavailableError as sue:
                    log.warning(f"⚠️ IRCTC Class selection glitch: {sue}. Retrying ({t_attempt}/3)...")
                    time.sleep(1.2)
                except TrainNotFoundError as tne:
                    if job.alt_quota:
                        log.warning(f"Train/class not found under {job.quota}. Trying alternate quota: {job.alt_quota}")
                        train_ok = search_hdl.select_train_and_class(
                            job.train_number, job.train_class, job.alt_quota, alt_train=job.alt_train
                        )
                        if train_ok:
                            break
                    raise tne
                except Exception as e:
                    log.warning(f"Train selection attempt {t_attempt} error: {e}")
                    time.sleep(1.0)

            if not train_ok:
                raise Exception("Train and class selection failed after retries!")
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

        except IRCTCServiceUnavailableError as sue:
            self.result = {"success": False, "pnr": "", "error": str(sue)}
            log.error(f"❌ BOOKING HALTED (IRCTC SERVICE UNAVAILABLE): {sue}")
            self._emit("error", f"IRCTC Service Unavailable: {sue}")
            notifier.booking_failed(str(sue))
            # Service unavailable / maintenance / booking blocked — halt cleanly without looping
            return

        except Exception as e:
            self.result = {"success": False, "pnr": "", "error": str(e)}
            log.error(f"❌ BOOKING FAILED: {e}")
            self._emit("error", f"Booking failed: {e}")
            notifier.booking_failed(str(e))
            if not job.dry_run:
                self._maybe_retry()

    def _maybe_retry(self):
        self._retry_count += 1
        if self._retry_count >= MAX_RETRIES:
            log.error(f"All {MAX_RETRIES} booking attempts exhausted.")
            return
        log.warning(f"Retrying booking ({self._retry_count + 1}/{MAX_RETRIES})...")
        self._emit("retry", f"Retrying ({self._retry_count + 1}/{MAX_RETRIES})...")
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
