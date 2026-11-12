# ui/app.py — Flask + SocketIO web dashboard for the bot

import os
import sys
import datetime
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from bot.booking_bot import IRCTCBookingBot, BookingJob
from bot.scheduler import TatkalScheduler
from utils.logger import get_logger
from utils.encryption import secure_store
from config.settings import FLASK_HOST, FLASK_PORT, FLASK_DEBUG

log = get_logger("Dashboard")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.urandom(32)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global bot instance
bot: IRCTCBookingBot = None
bot_thread = None


# ─────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────

@app.route("/")
def index():
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(ui_dir, "dashboard.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    global bot
    if bot is None:
        return jsonify({"status": "idle", "result": {}})
    return jsonify({
        "status": "running" if bot_thread and bot_thread.is_alive() else "idle",
        "result": bot.result
    })


@app.route("/api/arm", methods=["POST"])
def arm_bot():
    """Receive booking config and arm the bot."""
    global bot, bot_thread

    data = request.json
    log.info(f"ARM request received: {data}")

    try:
        job = _build_job(data)
        bot = IRCTCBookingBot()
        bot.load_job(job)

        # Wire SocketIO events
        def on_event(event_data):
            socketio.emit("bot_event", event_data)
            log.debug(f"Emitted: {event_data}")

        bot.add_status_callback(on_event)

        # Run bot in background thread
        bot_thread = threading.Thread(target=bot.arm, kwargs={"blocking": True}, daemon=True)
        bot_thread.start()

        return jsonify({"success": True, "message": "Bot armed successfully!"})

    except Exception as e:
        log.error(f"Arm failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/disarm", methods=["POST"])
def disarm_bot():
    global bot
    if bot:
        bot.disarm()
        return jsonify({"success": True, "message": "Bot disarmed."})
    return jsonify({"success": False, "error": "No active bot."})


@app.route("/api/run_now", methods=["POST"])
def run_now():
    """Run booking immediately (for testing)."""
    global bot, bot_thread
    data = request.json

    try:
        job = _build_job(data)
        bot = IRCTCBookingBot()
        bot.load_job(job)

        def on_event(event_data):
            socketio.emit("bot_event", event_data)

        bot.add_status_callback(on_event)

        bot_thread = threading.Thread(target=bot.run_now, daemon=True)
        bot_thread.start()

        return jsonify({"success": True, "message": "Booking started immediately!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/countdown", methods=["GET"])
def countdown():
    """Get seconds until next Tatkal window."""
    train_class = request.args.get("class", "3A")
    booking_date_str = request.args.get("date", "")

    try:
        if booking_date_str:
            bd = datetime.date.fromisoformat(booking_date_str)
        else:
            bd = datetime.date.today()

        scheduler = TatkalScheduler()
        target = scheduler.get_tatkal_open_time(train_class, bd)
        secs = scheduler.get_seconds_until(target)
        formatted = TatkalScheduler.format_countdown(target)

        return jsonify({
            "target": target.isoformat(),
            "seconds_remaining": secs,
            "formatted": formatted,
            "train_class": train_class
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Return last 100 lines of the log file."""
    try:
        with open("logs/irctc_bot.log", "r", encoding="utf-8") as f:
            lines = f.readlines()
        return jsonify({"logs": lines[-100:]})
    except FileNotFoundError:
        return jsonify({"logs": []})


# ─────────────────────────────────────────────────────
#  SocketIO events
# ─────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    log.info(f"Dashboard client connected: {request.sid}")
    emit("connected", {"message": "Connected to RailFast bot server."})


@socketio.on("disconnect")
def on_disconnect():
    log.info(f"Dashboard client disconnected: {request.sid}")


@socketio.on("ping_bot")
def ping_bot(data):
    emit("pong_bot", {"status": "alive", "time": datetime.datetime.now().isoformat()})


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _build_job(data: dict) -> BookingJob:
    """Build a BookingJob from raw API request data."""
    job = BookingJob()

    # Account
    job.username = data.get("username", "")
    job.password = data.get("password", "")
    job.mobile   = data.get("mobile", "")

    if not job.username or not job.password:
        raise ValueError("IRCTC username and password are required.")

    # Journey
    job.from_station = data.get("from_station", "")
    job.to_station   = data.get("to_station", "")
    job.travel_date  = data.get("travel_date", "")
    job.train_number = data.get("train_number", "")
    job.train_class  = data.get("train_class", "3A")
    job.quota        = data.get("quota", "TQ")

    # Scheduling
    booking_date_str = data.get("booking_date", "")
    if booking_date_str:
        job.booking_date = datetime.date.fromisoformat(booking_date_str)
    else:
        job.booking_date = datetime.date.today()

    job.trigger_hour   = int(data.get("trigger_hour", 10))
    job.trigger_minute = int(data.get("trigger_minute", 0))
    job.pre_login_secs = int(data.get("pre_login_secs", 120))

    # Passengers
    job.passengers = data.get("passengers", [])
    if not job.passengers:
        raise ValueError("At least one passenger is required.")

    job.insurance = data.get("insurance", False)

    # Payment
    job.payment = data.get("payment", {})
    if not job.payment.get("method"):
        raise ValueError("Payment method is required.")

    # Fallbacks
    job.alt_quota = data.get("alt_quota")
    job.alt_train = data.get("alt_train")
    job.dry_run   = data.get("dry_run", False)

    return job


# ─────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"🚀 RailFast Dashboard starting at http://{FLASK_HOST}:{FLASK_PORT}")
    socketio.run(
        app,
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=FLASK_DEBUG,
        use_reloader=False
    )
