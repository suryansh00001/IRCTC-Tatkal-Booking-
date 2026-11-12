# tests/test_pipeline.py — Automated Self-Test Suite

import sys
import os
import unittest
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.booking_bot import BookingJob, IRCTCBookingBot
from bot.scheduler import TatkalScheduler
from bot.passenger_filler import PassengerFiller
from bot.payment import PaymentHandler
from run_bot import load_job_from_file


class TestIRCTCPipeline(unittest.TestCase):

    def test_01_config_load(self):
        """Verify booking_config.json loads correctly with dry_run."""
        config_path = "booking_config.json"
        self.assertTrue(os.path.exists(config_path), "booking_config.json must exist")
        job = load_job_from_file(config_path)
        self.assertTrue(job.dry_run, "dry_run must be enabled by default")
        self.assertEqual(job.train_class, "3A")
        self.assertEqual(job.quota, "TQ")
        self.assertTrue(len(job.passengers) >= 1)

    def test_02_scheduler_math(self):
        """Verify Tatkal window calculation (10:00 for AC, 11:00 for Non-AC)."""
        sched = TatkalScheduler()
        today = datetime.date.today()
        ac_time = sched.get_tatkal_open_time("3A", today)
        self.assertEqual(ac_time.hour, 10)
        self.assertEqual(ac_time.minute, 0)

        sl_time = sched.get_tatkal_open_time("SL", today)
        self.assertEqual(sl_time.hour, 11)
        self.assertEqual(sl_time.minute, 0)

    def test_03_job_data_integrity(self):
        """Ensure password is never exposed in to_dict()."""
        job = BookingJob()
        job.username = "test_user"
        job.password = "secret_pass"
        d = job.to_dict()
        self.assertNotIn("password", d)
        self.assertEqual(d["username"], "test_user")

    def test_04_payment_dry_run_safety(self):
        """Verify payment handler respects dry_run flag."""
        pay_cfg = {"method": "upi", "upi_id": "test@upi"}
        handler = PaymentHandler(driver=None, payment_config=pay_cfg, dry_run=True)
        self.assertTrue(handler.dry_run)

    def test_05_passenger_data_structure(self):
        """Verify passenger validation format."""
        job = load_job_from_file("booking_config.json")
        pax = job.passengers[0]
        self.assertIn("name", pax)
        self.assertIn("age", pax)
        self.assertIn("gender", pax)
        self.assertIn("berth_pref", pax)


if __name__ == "__main__":
    print("\n🧪 RUNNING AUTOMATED PIPELINE SELF-TESTS...\n" + "=" * 50)
    unittest.main(verbosity=2)

