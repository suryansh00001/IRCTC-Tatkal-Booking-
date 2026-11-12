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
from bot.train_search import (
    IRCTCServiceUnavailableError,
    TrainNotFoundError,
    check_search_errors_or_availability,
)
from run_bot import load_job_from_file
from unittest.mock import MagicMock


class TestIRCTCPipeline(unittest.TestCase):

    def test_01_config_load(self):
        """Verify booking_config.json loads correctly with dry_run."""
        config_path = "booking_config.json"
        self.assertTrue(os.path.exists(config_path), "booking_config.json must exist")
        job = load_job_from_file(config_path)
        self.assertTrue(job.dry_run, "dry_run must be enabled by default")
        self.assertEqual(job.train_class, "3A")
        self.assertIn(job.quota, ["TQ", "GN"])
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

    def test_06_error_detection_service_unavailable(self):
        """Verify check_search_errors_or_availability detects error toast."""
        mock_driver = MagicMock()
        mock_driver.implicitly_wait = MagicMock()
        mock_driver.current_url = "https://www.irctc.co.in/nget/train-search"

        mock_el = MagicMock()
        mock_el.is_displayed.return_value = True
        mock_el.text = "Service is not available between NDLS and CSTM"
        mock_el.get_attribute.return_value = "ui-growl-message"

        mock_driver.find_elements.side_effect = lambda by, sel: [mock_el] if ".ui-growl-message" in sel else []

        err = check_search_errors_or_availability(mock_driver)
        self.assertIsNotNone(err)
        self.assertIn("Service is not available", err)

    def test_07_error_detection_no_trains(self):
        """Verify check_search_errors_or_availability detects no direct trains message."""
        mock_driver = MagicMock()
        mock_driver.implicitly_wait = MagicMock()
        mock_driver.current_url = "https://www.irctc.co.in/nget/train-list"

        mock_el = MagicMock()
        mock_el.is_displayed.return_value = True
        mock_el.text = "No direct trains found between selected stations"
        mock_el.get_attribute.return_value = "no-train-heading"

        def fake_find(by, sel):
            if ".no-train" in sel or "no-train" in sel:
                return [mock_el]
            return []

        mock_driver.find_elements.side_effect = fake_find

        err = check_search_errors_or_availability(mock_driver)
        self.assertIsNotNone(err)
        self.assertIn("No direct trains", err)

    def test_08_error_detection_clean_page(self):
        """Verify check_search_errors_or_availability returns None when no error exists."""
        mock_driver = MagicMock()
        mock_driver.implicitly_wait = MagicMock()
        mock_driver.current_url = "https://www.irctc.co.in/nget/train-list"
        mock_driver.find_elements.return_value = []

        err = check_search_errors_or_availability(mock_driver)
        self.assertIsNone(err)

    def test_09_custom_exceptions(self):
        """Verify custom search exceptions have proper inheritance."""
        self.assertTrue(issubclass(IRCTCServiceUnavailableError, Exception))
        self.assertTrue(issubclass(TrainNotFoundError, Exception))


if __name__ == "__main__":
    print("\n🧪 RUNNING AUTOMATED PIPELINE SELF-TESTS...\n" + "=" * 50)
    unittest.main(verbosity=2)

