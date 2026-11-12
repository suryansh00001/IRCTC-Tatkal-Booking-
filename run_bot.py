#!/usr/bin/env python3
# run_bot.py — CLI entry point for IRCTC Tatkal AutoBook Bot (2026 Updated)

import sys
import os
import datetime
import argparse
import json
import getpass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.booking_bot import IRCTCBookingBot, BookingJob
from bot.scheduler import TatkalScheduler
from utils.logger import get_logger
from utils.notifier import notifier
from config.settings import (
    IRCTC_USERNAME, IRCTC_PASSWORD, IRCTC_MOBILE
)

log = get_logger("CLI")

BANNER = """
╔══════════════════════════════════════════════════════════╗
║         🚄  IRCTC TATKAL AUTOBOOK PIPELINE  🚄           ║
║       High-Speed Automated Form & Booking Engine         ║
║                AI & PrimeNG Integration                  ║
╚══════════════════════════════════════════════════════════╝
"""

def print_banner():
    print(BANNER)


def interactive_setup() -> BookingJob:
    """Interactive CLI setup wizard."""
    print("\n📋 BOOKING SETUP WIZARD\n" + "─" * 40)
    job = BookingJob()

    # ── IRCTC Credentials ──
    print("\n🔐 IRCTC Account")
    job.username = input("   IRCTC Username: ").strip() or IRCTC_USERNAME
    job.password = getpass.getpass("   IRCTC Password: ") or IRCTC_PASSWORD
    job.mobile   = input("   Registered Mobile (+91XXXXXXXXXX): ").strip() or IRCTC_MOBILE

    # ── Journey Details ──
    print("\n🚄 Journey Details")
    job.from_station = input("   From Station Code (e.g. NDLS): ").strip().upper()
    job.to_station   = input("   To Station Code (e.g. CSTM): ").strip().upper()
    job.travel_date  = input("   Travel Date (DD/MM/YYYY): ").strip()
    job.train_number = input("   Train Number (e.g. 12301): ").strip()

    print("   Classes: 1A / 2A / 3A / 3E / SL / CC / 2S")
    job.train_class = input("   Class (default: 3A): ").strip().upper() or "3A"

    print("   Quotas: TQ=Tatkal / PT=Premium Tatkal / GN=General")
    job.quota = input("   Quota (default: TQ): ").strip().upper() or "TQ"

    # ── Scheduling ──
    print("\n⏰ Scheduling")
    booking_date_str = input("   Booking Date YYYY-MM-DD (default: today): ").strip()
    if booking_date_str:
        job.booking_date = datetime.date.fromisoformat(booking_date_str)
    else:
        job.booking_date = datetime.date.today()

    is_ac = job.train_class in {"1A", "2A", "3A", "3E", "CC"}
    default_hour = 10 if is_ac else 11
    hour_str = input(f"   Trigger Hour (default: {default_hour} for {'AC' if is_ac else 'Non-AC'}): ").strip()
    job.trigger_hour   = int(hour_str) if hour_str else default_hour
    job.trigger_minute = 0

    # ── Passengers ──
    print("\n👥 Passengers (max 4)")
    num_pax = int(input("   Number of passengers (1-4): ").strip() or "1")
    num_pax = max(1, min(4, num_pax))

    for i in range(num_pax):
        print(f"\n   Passenger {i+1}:")
        pax = {
            "name":       input(f"   Full Name: ").strip(),
            "age":        input(f"   Age: ").strip(),
            "gender":     input(f"   Gender (M/F/T): ").strip().upper() or "M",
            "berth_pref": input(f"   Berth Pref (LB/MB/UB/SL/SU): ").strip().upper() or "LB",
            "id_type":    input(f"   ID Type (AADHAAR/PAN/PASSPORT/VOTER/DRIVING): ").strip().upper() or "AADHAAR",
            "id_number":  input(f"   ID Number: ").strip(),
        }
        job.passengers.append(pax)

    # ── Payment ──
    print("\n💳 Payment")
    print("   Methods: upi / card / netbanking / wallet")
    method = input("   Method (default: upi): ").strip().lower() or "upi"
    payment = {"method": method}

    if method == "upi":
        payment["upi_id"] = input("   UPI ID (e.g. name@upi): ").strip()
    elif method == "card":
        payment["card_number"] = input("   Card Number: ").strip().replace(" ", "")
        payment["card_name"]   = input("   Cardholder Name: ").strip()
        payment["card_expiry"] = input("   Expiry (MM/YY): ").strip()
        payment["card_cvv"]    = getpass.getpass("   CVV: ")
    elif method in ("netbanking", "nb"):
        payment["bank"]    = input("   Bank Name (e.g. SBI): ").strip()
        payment["method"]  = "netbanking"

    job.payment = payment

    return job


def load_job_from_file(path: str) -> BookingJob:
    """Load booking job from JSON config file."""
    if not os.path.exists(path):
        print(f"\n❌ Error: Config file '{path}' not found!")
        print("   Run 'python run_bot.py --template' to generate one, or edit 'booking_config.json'.\n")
        sys.exit(1)

    with open(path, "r") as f:
        data = json.load(f)

    job = BookingJob()
    job.username      = data.get("username", IRCTC_USERNAME)
    job.password      = data.get("password", IRCTC_PASSWORD)
    job.mobile        = data.get("mobile", IRCTC_MOBILE)
    job.from_station  = data["from_station"]
    job.to_station    = data["to_station"]
    job.travel_date   = data["travel_date"]
    job.train_number  = data["train_number"]
    job.train_class   = data.get("train_class", "3A")
    job.quota         = data.get("quota", "TQ")
    job.passengers    = data["passengers"]
    job.payment       = data["payment"]
    job.insurance     = data.get("insurance", False)
    job.alt_quota     = data.get("alt_quota")
    job.dry_run       = data.get("dry_run", False)

    bd = data.get("booking_date", "")
    job.booking_date  = datetime.date.fromisoformat(bd) if bd else datetime.date.today()
    job.trigger_hour   = data.get("trigger_hour", 10)
    job.trigger_minute = data.get("trigger_minute", 0)
    job.pre_login_secs = data.get("pre_login_secs", 120)

    return job


def save_job_template():
    """Save a sample job JSON template."""
    template = {
        "username":     "your_irctc_id",
        "password":     "your_irctc_password",
        "mobile":       "9XXXXXXXXX",
        "from_station": "NDLS",
        "to_station":   "CSTM",
        "travel_date":  "25/12/2026",
        "train_number": "12951",
        "train_class":  "3A",
        "quota":        "TQ",
        "booking_date": "2026-12-24",
        "trigger_hour": 10,
        "trigger_minute": 0,
        "pre_login_secs": 120,
        "insurance":    False,
        "alt_quota":    "GN",
        "dry_run":      True,
        "passengers": [
            {
                "name":       "Test Passenger",
                "age":        "28",
                "gender":     "M",
                "berth_pref": "LB",
                "id_type":    "AADHAAR",
                "id_number":  "XXXX XXXX XXXX"
            }
        ],
        "payment": {
            "method":   "upi",
            "upi_id":   "testuser@upi"
        }
    }
    path = "booking_config.json"
    with open(path, "w") as f:
        json.dump(template, f, indent=2)
    print(f"✅ Template saved to: {path}")
    print("   Edit it and run: python run_bot.py --config booking_config.json --dry-run")


def main():
    print_banner()

    parser = argparse.ArgumentParser(description="IRCTC Tatkal AutoBook Bot")
    parser.add_argument("--config",    help="Path to JSON booking config file")
    parser.add_argument("--template",  action="store_true", help="Generate a booking config template")
    parser.add_argument("--now",       action="store_true", help="Run booking immediately (skip scheduler)")
    parser.add_argument("--dry-run", "--test", dest="dry_run", action="store_true",
                        help="Safe test mode: fill all forms and stop before actual payment")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm and bypass interactive prompt")
    parser.add_argument("--dashboard", action="store_true", help="Launch web dashboard instead")
    args = parser.parse_args()

    if args.template:
        save_job_template()
        return

    if args.dashboard:
        print("🌐 Starting web dashboard...")
        os.chdir(os.path.join(os.path.dirname(__file__), "ui"))
        from ui.app import socketio, app
        from config.settings import FLASK_HOST, FLASK_PORT
        print(f"   Open: http://{FLASK_HOST}:{FLASK_PORT}")
        socketio.run(app, host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)
        return

    # ── Build job ──
    if args.config:
        print(f"📂 Loading config from: {args.config}")
        job = load_job_from_file(args.config)
    else:
        job = interactive_setup()

    if args.dry_run:
        job.dry_run = True

    # ── Confirm ──
    print("\n" + "─" * 40)
    print("📋 BOOKING SUMMARY")
    print("─" * 40)
    print(f"  Account  : {job.username}")
    print(f"  Route    : {job.from_station} → {job.to_station}")
    print(f"  Train    : {job.train_number} | {job.train_class} | {job.quota}")
    print(f"  Date     : {job.travel_date}")
    print(f"  Trigger  : {job.booking_date} at {job.trigger_hour:02d}:{job.trigger_minute:02d}:00")
    print(f"  Pax      : {len(job.passengers)}")
    print(f"  Payment  : {job.payment.get('method', '?').upper()}")
    print(f"  Mode     : {'🛡️ SAFE TEST (DRY RUN - No money deducted)' if job.dry_run else '🚀 LIVE BOOKING'}")
    print("─" * 40)

    if not args.yes:
        prompt_text = "\n🚀 Run Safe DRY-RUN test? (yes/no): " if job.dry_run else "\n🚀 ARM the bot? (yes/no): "
        confirm = input(prompt_text).strip().lower()
        if confirm not in ("yes", "y"):
            print("Aborted.")
            return

    # ── Run ──
    bot = IRCTCBookingBot()
    bot.load_job(job)

    def print_event(ev):
        emoji_map = {
            "armed": "🔒", "pre_login": "🔑", "logged_in": "✅",
            "booking_start": "🚀", "step": "▶️", "success": "🎉",
            "error": "❌", "warning": "⚠️", "retry": "🔄"
        }
        emoji = emoji_map.get(ev["event"], "ℹ️")
        print(f"  {emoji} [{ev['time'][11:19]}] {ev['message']}")

    bot.add_status_callback(print_event)

    try:
        if args.now or job.dry_run:
            log.info("Starting booking execution...")
            bot.run_now()
        else:
            bot.arm(blocking=True)

        # Print result
        if bot.result["success"]:
            print(f"\n{'='*40}")
            if job.dry_run:
                print("🎉 SAFE DRY-RUN COMPLETED SUCCESSFULLY!")
                print("   All forms, trains, and passenger inputs verified.")
                print("   No ticket booked. No payment deducted.")
            else:
                print("🎉 BOOKING SUCCESSFUL!")
                print(f"   PNR: {bot.result['pnr']}")
            print(f"{'='*40}")
        else:
            print(f"\n❌ FAILED: {bot.result.get('error', 'Unknown error')}")
            print("   Please check IRCTC website manually.")

    except KeyboardInterrupt:
        print("\n\n⚠️ Bot stopped by user.")
        bot.disarm()
    finally:
        bot.cleanup()


if __name__ == "__main__":
    main()
