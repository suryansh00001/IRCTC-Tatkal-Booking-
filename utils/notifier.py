# utils/notifier.py — SMS + sound notifications

import os
from utils.logger import get_logger
from config.settings import TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, NOTIFY_TO

log = get_logger("Notifier")

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    log.warning("Twilio not installed — SMS notifications disabled.")

try:
    import winsound
    SOUND_AVAILABLE = "windows"
except ImportError:
    SOUND_AVAILABLE = "unix"  # will use os.system beep on Unix


class Notifier:
    def __init__(self):
        self.twilio = None
        if TWILIO_AVAILABLE and TWILIO_SID and TWILIO_TOKEN:
            try:
                self.twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
                log.info("Twilio SMS notifier initialized.")
            except Exception as e:
                log.error(f"Twilio init failed: {e}")

    def sms(self, message: str, to: str = NOTIFY_TO):
        """Send SMS via Twilio."""
        if not self.twilio:
            log.warning(f"[SMS DISABLED] Would send: {message}")
            return False
        try:
            msg = self.twilio.messages.create(body=message, from_=TWILIO_FROM, to=to)
            log.info(f"SMS sent to {to}: SID={msg.sid}")
            return True
        except Exception as e:
            log.error(f"SMS failed: {e}")
            return False

    def booking_success(self, pnr: str, train: str, from_st: str, to_st: str,
                        travel_date: str, passengers: list):
        """Send booking success SMS."""
        names = ", ".join(p.get("name", "?") for p in passengers)
        msg = (
            f"✅ IRCTC TATKAL BOOKED!\n"
            f"PNR: {pnr}\n"
            f"Train: {train}\n"
            f"Route: {from_st} → {to_st}\n"
            f"Date: {travel_date}\n"
            f"Passengers: {names}\n"
            f"Check irctc.co.in for full details."
        )
        self.sms(msg)
        log.info(f"Booking success notification sent. PNR: {pnr}")

    def booking_failed(self, reason: str):
        """Send booking failure SMS."""
        msg = f"❌ IRCTC AutoBook FAILED\nReason: {reason}\nPlease book manually at irctc.co.in"
        self.sms(msg)

    def beep(self, times: int = 3, freq: int = 880, duration_ms: int = 300):
        """Play alert beep sound."""
        try:
            if SOUND_AVAILABLE == "windows":
                import winsound
                for _ in range(times):
                    winsound.Beep(freq, duration_ms)
            elif SOUND_AVAILABLE == "unix":
                import subprocess
                for _ in range(times):
                    subprocess.run(["beep", "-f", str(freq), "-l", str(duration_ms)],
                                   capture_output=True)
        except Exception as e:
            log.debug(f"Beep failed (non-critical): {e}")

    def countdown_alert(self, seconds_remaining: int):
        """Beep at key countdown moments."""
        if seconds_remaining in (60, 30, 10, 5, 3, 2, 1):
            log.info(f"⏱ T–{seconds_remaining}s to Tatkal window!")
            if seconds_remaining <= 10:
                self.beep(times=1, freq=1000 if seconds_remaining <= 5 else 800)


notifier = Notifier()
