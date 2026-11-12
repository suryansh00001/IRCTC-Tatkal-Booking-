# 🚄 IRCTC Tatkal AutoBook Bot
### | Python + Selenium

A fully automated IRCTC Tatkal ticket booking bot that:
- Logs into IRCTC automatically
- Solves CAPTCHA using AI (2Captcha API or local Tesseract OCR)
- Waits for the exact Tatkal window (10:00 AM / 11:00 AM)
- Fills all passenger details in under 2 seconds
- Completes payment automatically (UPI / Card / Net Banking / Wallet)
- Sends SMS notification with PNR on success

---

## 📁 Project Structure

```
irctc_tatkal_bot/
├── run_bot.py                  ← Main CLI entry point
├── booking_config.sample.json  ← Sample booking config
├── requirements.txt
├── .env.example                ← Copy to .env and fill
│
├── bot/
│   ├── booking_bot.py          ← Main orchestrator
│   ├── driver.py               ← Undetected Chrome driver
│   ├── login.py                ← IRCTC login + CAPTCHA
│   ├── train_search.py         ← Train search & selection
│   ├── passenger_filler.py     ← Passenger form automation
│   ├── payment.py              ← Payment automation
│   └── scheduler.py            ← Precision countdown timer
│
├── utils/
│   ├── captcha_solver.py       ← 2Captcha API + local OCR
│   ├── encryption.py           ← AES-256 credential encryption
│   ├── logger.py               ← Colored console + file logger
│   └── notifier.py             ← SMS (Twilio) + sound alerts
│
├── config/
│   └── settings.py             ← All configuration
│
├── ui/
│   └── app.py                  ← Flask + SocketIO web dashboard
│
└── logs/
    └── irctc_bot.log           ← Auto-created on first run
```

---

## ⚙️ Setup

### 1. Install Python 3.9+
Download from https://python.org

### 2. Install Google Chrome
Download from https://google.com/chrome

### 3. Clone / Download project
```bash
cd irctc_tatkal_bot
```

### 4. Install dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure credentials
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 6. (Optional) Install Tesseract OCR for local CAPTCHA
- **Windows**: https://github.com/UB-Mannheim/tesseract/wiki
- **Ubuntu**: `sudo apt install tesseract-ocr`
- **Mac**: `brew install tesseract`

### 7. (Optional) Get 2Captcha API key
Register at https://2captcha.com and add key to `.env`
> 2Captcha is recommended — much higher accuracy than local OCR.

---

## 🚀 Usage

### Option A — Interactive CLI Wizard
```bash
python run_bot.py
```
The wizard will ask for all details step by step.

### Option B — JSON Config File (Recommended)
```bash
# Generate template
python run_bot.py --template

# Edit booking_config.json with your details

# Run bot
python run_bot.py --config booking_config.json
```

### Option C — Safe Dry-Run (Test Without Booking)
```bash
# Tests login, train search, and passenger autofill, stopping safely before payment:
python run_bot.py --config booking_config.json --dry-run
```

### Option D — Run Live Booking Immediately (Bypass Scheduler)
```bash
python run_bot.py --config booking_config.json --now
```

### Option E — Web Dashboard
```bash
python run_bot.py --dashboard
# Open: http://127.0.0.1:5000
```

---

## 📋 Booking Config Reference

| Field | Description | Example |
|---|---|---|
| `username` | IRCTC user ID | `"john123"` |
| `password` | IRCTC password | `"MyPass@1"` |
| `mobile` | Registered mobile | `"9876543210"` |
| `from_station` | Source station code | `"NDLS"` |
| `to_station` | Destination code | `"CSTM"` |
| `travel_date` | DD/MM/YYYY | `"25/12/2025"` |
| `train_number` | Train number | `"12951"` |
| `train_class` | Class code | `"3A"` |
| `quota` | Booking quota | `"TQ"` |
| `booking_date` | Date to book (D-1) | `"2025-12-24"` |
| `trigger_hour` | Trigger hour (24h) | `10` |
| `trigger_minute` | Trigger minute | `0` |
| `pre_login_secs` | Pre-login buffer | `120` |
| `insurance` | Travel insurance | `false` |
| `alt_quota` | Fallback quota | `"GN"` |

### Passenger fields
| Field | Values |
|---|---|
| `name` | Full name as in ID |
| `age` | Integer string |
| `gender` | `"M"` / `"F"` / `"T"` |
| `berth_pref` | `"LB"` / `"MB"` / `"UB"` / `"SL"` / `"SU"` |
| `id_type` | `"AADHAAR"` / `"PAN"` / `"PASSPORT"` / `"VOTER"` / `"DRIVING"` |
| `id_number` | ID number string |

### Payment methods
```json
// UPI
{ "method": "upi", "upi_id": "name@upi" }

// Debit/Credit Card
{ "method": "card", "card_number": "4111111111111111",
  "card_name": "Full Name", "card_expiry": "12/26", "card_cvv": "123" }

// Net Banking
{ "method": "netbanking", "bank": "SBI" }

// IRCTC Wallet
{ "method": "wallet" }
```

---

## 🕐 Tatkal Timing Reference

| Class | Opens |
|---|---|
| 1A, 2A, 3A, 3E, CC | **10:00 AM** (D-1) |
| SL, 2S | **11:00 AM** (D-1) |

The bot pre-logs in 2 minutes before the window opens to keep the session warm.

---

## ⚠️ Important Notes

1. **Keep the browser window OPEN** — do not close Chrome while the bot is running
2. **UPI payments** require you to approve the payment on your phone
3. **Card payments** may require OTP — keep your phone nearby
4. **Net Banking** may redirect to bank's page for 2FA
5. IRCTC's UI changes frequently — if the bot fails, selectors in `bot/` files may need updating
6. Run on a **stable internet connection** — slow net = missed Tatkal window

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| `ChromeDriver version mismatch` | Update Chrome to latest, run `pip install -U webdriver-manager` |
| `Login CAPTCHA fails` | Add 2Captcha API key to `.env` |
| `Train not found` | Verify train number on irctc.co.in first |
| `Payment page not loading` | IRCTC gateway may be slow — increase `PAYMENT_TIMEOUT` in settings |
| `Session expired` | Enable `relogin` in settings |

---

## 📊 Tech Stack

- **Python 3.9+**
- **Selenium 4** + **undetected-chromedriver** (bot detection bypass)
- **2Captcha API** / **Tesseract OCR** (CAPTCHA solving)
- **Flask + SocketIO** (web dashboard)
- **Twilio** (SMS notifications)
- **cryptography (Fernet/AES-256)** (credential encryption)

---

*For research and educational purposes only. Use with authorization.*
