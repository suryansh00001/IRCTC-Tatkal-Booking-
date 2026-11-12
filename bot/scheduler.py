# bot/scheduler.py — Precision countdown timer and booking trigger

import time
import threading
import datetime
from utils.logger import get_logger
from utils.notifier import notifier
from config.settings import (
    TATKAL_AC_HOUR, TATKAL_AC_MINUTE,
    TATKAL_NON_AC_HOUR, TATKAL_NON_AC_MINUTE,
    PRE_LOGIN_BUFFER
)

log = get_logger("Scheduler")

# Classes that open at 10 AM (AC)
AC_CLASSES = {"1A", "2A", "3A", "3E", "CC"}
# Classes that open at 11 AM (Non-AC)
NON_AC_CLASSES = {"SL", "2S"}


class TatkalScheduler:
    """
    Precision scheduler that triggers booking at the exact
    Tatkal opening time (10:00:00 or 11:00:00 AM).
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._on_prelogin = None
        self._on_booking_trigger = None
        self.status_callback = None

    def set_callbacks(self, on_prelogin=None, on_trigger=None, on_status=None):
        """Register callbacks for scheduler events."""
        self._on_prelogin = on_prelogin
        self._on_booking_trigger = on_trigger
        self.status_callback = on_status

    def get_tatkal_open_time(self, train_class: str,
                              booking_date: datetime.date) -> datetime.datetime:
        """Get the exact datetime when Tatkal opens for a given class."""
        if train_class.upper() in AC_CLASSES:
            return datetime.datetime(
                booking_date.year, booking_date.month, booking_date.day,
                TATKAL_AC_HOUR, TATKAL_AC_MINUTE, 0
            )
        else:
            return datetime.datetime(
                booking_date.year, booking_date.month, booking_date.day,
                TATKAL_NON_AC_HOUR, TATKAL_NON_AC_MINUTE, 0
            )

    def get_seconds_until(self, target: datetime.datetime) -> float:
        """Get seconds until a target datetime."""
        delta = (target - datetime.datetime.now()).total_seconds()
        return max(0, delta)

    def wait_and_trigger(self, booking_datetime: datetime.datetime,
                          pre_login_buffer: int = PRE_LOGIN_BUFFER):
        """
        Block until booking_datetime and trigger the booking callback.
        Fires pre-login callback `pre_login_buffer` seconds before.
        """
        self._stop_event.clear()

        pre_login_time = booking_datetime - datetime.timedelta(seconds=pre_login_buffer)
        now = datetime.datetime.now()

        if booking_datetime <= now:
            log.warning("Booking time already passed — triggering immediately!")
            self._fire_trigger()
            return

        # ── Phase 1: Wait until pre-login time ──
        secs_to_prelogin = (pre_login_time - now).total_seconds()
        if secs_to_prelogin > 0:
            log.info(f"Waiting {secs_to_prelogin:.0f}s until pre-login phase "
                     f"({pre_login_time.strftime('%H:%M:%S')})...")
            self._countdown_sleep(secs_to_prelogin, booking_datetime)

        if self._stop_event.is_set():
            log.info("Scheduler stopped.")
            return

        # ── Phase 2: Pre-login ──
        log.info(f"⚡ PRE-LOGIN PHASE — T–{pre_login_buffer}s")
        self._notify_status("pre_login", f"Logging in (T-{pre_login_buffer}s)")
        if self._on_prelogin:
            try:
                self._on_prelogin()
            except Exception as e:
                log.error(f"Pre-login callback error: {e}")

        # ── Phase 3: Precision wait to booking second ──
        secs_to_booking = (booking_datetime - datetime.datetime.now()).total_seconds()
        log.info(f"Precision waiting {secs_to_booking:.3f}s to booking trigger...")

        if secs_to_booking > 0:
            # High-precision sleep using busy-wait in last 0.5s
            if secs_to_booking > 1:
                time.sleep(secs_to_booking - 0.5)

            # Busy-wait last 0.5 seconds for maximum precision
            while datetime.datetime.now() < booking_datetime:
                time.sleep(0.001)

        # ── Phase 4: TRIGGER ──
        actual_time = datetime.datetime.now()
        delta_ms = (actual_time - booking_datetime).total_seconds() * 1000
        log.info(f"🚀 BOOKING TRIGGER FIRED! Offset: {delta_ms:+.1f}ms")
        self._fire_trigger()

    def _countdown_sleep(self, total_seconds: float,
                          booking_time: datetime.datetime):
        """Sleep with countdown logging, checking for stop events."""
        start = time.time()
        last_log = 0

        while True:
            if self._stop_event.is_set():
                return

            elapsed = time.time() - start
            remaining = total_seconds - elapsed

            if remaining <= 0:
                break

            # Log at milestones
            r_int = int(remaining)
            if r_int != last_log:
                last_log = r_int
                notifier.countdown_alert(r_int)

                if r_int % 300 == 0 or r_int <= 60:
                    time_str = booking_time.strftime('%H:%M:%S')
                    log.info(f"⏳ T–{r_int}s until Tatkal opens at {time_str}")
                    self._notify_status("waiting", f"T-{r_int}s")

            # Sleep in small chunks to allow stop detection
            sleep_chunk = min(1.0, remaining)
            time.sleep(sleep_chunk)

    def _fire_trigger(self):
        """Fire the booking trigger callback."""
        self._notify_status("booking", "🚀 BOOKING NOW")
        notifier.beep(times=5, freq=1200, duration_ms=200)
        if self._on_booking_trigger:
            try:
                self._on_booking_trigger()
            except Exception as e:
                log.error(f"Booking trigger callback error: {e}")

    def _notify_status(self, status: str, message: str):
        if self.status_callback:
            try:
                self.status_callback({"status": status, "message": message,
                                       "time": datetime.datetime.now().isoformat()})
            except Exception:
                pass

    def stop(self):
        """Stop the scheduler."""
        self._stop_event.set()
        log.info("Scheduler stopped.")

    @staticmethod
    def get_booking_date_for_travel(travel_date: datetime.date) -> datetime.date:
        """Get the booking date (D-1) for a given travel date."""
        return travel_date - datetime.timedelta(days=1)

    @staticmethod
    def format_countdown(target: datetime.datetime) -> str:
        """Format remaining time as HH:MM:SS string."""
        delta = target - datetime.datetime.now()
        if delta.total_seconds() <= 0:
            return "00:00:00"
        total_secs = int(delta.total_seconds())
        h = total_secs // 3600
        m = (total_secs % 3600) // 60
        s = total_secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
