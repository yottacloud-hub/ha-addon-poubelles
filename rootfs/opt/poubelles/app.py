#!/usr/bin/env python3
"""
Gestion Poubelles - Add-on Home Assistant
Gère les rappels de sortie des poubelles jaune et verte.
"""

import os
import json
import re
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from dateutil import parser as dateparser

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, send_from_directory
)
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    from pdf2image import convert_from_path
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB max upload

DATA_DIR = Path("/share/poubelles")
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CALENDAR_FILE = DATA_DIR / "calendar.json"
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
NOTIFICATION_SERVICE = os.environ.get("NOTIFICATION_SERVICE", "notify.notify")
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", 19))
REMINDER_MINUTE = int(os.environ.get("REMINDER_MINUTE", 0))
INGRESS_ENTRY = os.environ.get("INGRESS_ENTRY", "")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "pdf"}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("poubelles")

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def get_settings():
    defaults = {
        "reminder_hour": REMINDER_HOUR,
        "reminder_minute": REMINDER_MINUTE,
        "notification_service": NOTIFICATION_SERVICE,
        "reminder_enabled": True,
        "confirmation_timeout_minutes": 120,
    }
    saved = load_json(SETTINGS_FILE, {})
    defaults.update(saved)
    return defaults


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def get_calendar():
    """Returns {date_str: [bin_type, ...]}"""
    return load_json(CALENDAR_FILE, {})


def save_calendar(cal):
    save_json(CALENDAR_FILE, cal)


def get_history():
    """Returns {date_str: {bin_type: status}}"""
    return load_json(HISTORY_FILE, {})


def save_history(hist):
    save_json(HISTORY_FILE, hist)


# ---------------------------------------------------------------------------
# OCR / Calendar parsing
# ---------------------------------------------------------------------------

MONTH_MAP_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def extract_text_from_image(filepath: str) -> str:
    if not HAS_OCR:
        return ""
    img = Image.open(filepath)
    text = pytesseract.image_to_string(img, lang="fra")
    return text


def extract_text_from_pdf(filepath: str) -> str:
    if not HAS_PDF or not HAS_OCR:
        return ""
    images = convert_from_path(filepath, dpi=300)
    full_text = ""
    for img in images:
        full_text += pytesseract.image_to_string(img, lang="fra") + "\n"
    return full_text


def parse_calendar_text(raw_text: str, year: int = None) -> dict:
    """
    Attempt to parse dates and bin types from OCR text.
    Returns {date_str: [bin_types]}
    """
    if year is None:
        year = datetime.now().year

    calendar = {}
    lines = raw_text.split("\n")

    current_month = None

    # Patterns for French dates
    date_pattern = re.compile(
        r'(\d{1,2})\s*(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)',
        re.IGNORECASE
    )
    day_only_pattern = re.compile(r'\b(\d{1,2})\b')

    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower:
            continue

        # Detect month headers
        for month_name, month_num in MONTH_MAP_FR.items():
            if month_name in line_lower:
                # Check if it's a header (month name alone or with year)
                words = line_lower.split()
                if len(words) <= 3:
                    current_month = month_num
                    # Check for year
                    for w in words:
                        if w.isdigit() and len(w) == 4:
                            year = int(w)
                break

        # Detect bin type keywords
        bin_types = []
        if any(kw in line_lower for kw in ["jaune", "recyclable", "recyclage", "tri", "emballage"]):
            bin_types.append("jaune")
        if any(kw in line_lower for kw in ["vert", "verte", "ordure", "ménag", "menag", "résidu", "residu"]):
            bin_types.append("verte")

        if not bin_types:
            # Try color codes or other hints
            if "🟡" in line or "yellow" in line_lower:
                bin_types.append("jaune")
            if "🟢" in line or "green" in line_lower:
                bin_types.append("verte")

        # Extract dates from line
        matches = date_pattern.findall(line_lower)
        if matches:
            for day_str, month_str in matches:
                month_num = MONTH_MAP_FR.get(month_str)
                if month_num:
                    try:
                        d = date(year, month_num, int(day_str))
                        ds = d.isoformat()
                        if ds not in calendar:
                            calendar[ds] = []
                        if bin_types:
                            calendar[ds].extend(bin_types)
                        else:
                            # If no type detected, mark both
                            calendar[ds].extend(["jaune", "verte"])
                        calendar[ds] = list(set(calendar[ds]))
                    except ValueError:
                        pass
        elif current_month and bin_types:
            # Try extracting standalone day numbers
            days = day_only_pattern.findall(line_lower)
            for d_str in days:
                d_int = int(d_str)
                if 1 <= d_int <= 31:
                    try:
                        d = date(year, current_month, d_int)
                        ds = d.isoformat()
                        if ds not in calendar:
                            calendar[ds] = []
                        calendar[ds].extend(bin_types)
                        calendar[ds] = list(set(calendar[ds]))
                    except ValueError:
                        pass

    return calendar


# ---------------------------------------------------------------------------
# Home Assistant API helpers
# ---------------------------------------------------------------------------

def ha_api(method: str, endpoint: str, data: dict = None):
    """Call the Home Assistant Supervisor API."""
    if not SUPERVISOR_TOKEN:
        logger.warning("No SUPERVISOR_TOKEN, cannot call HA API")
        return None
    url = f"http://supervisor/core/api/{endpoint}"
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.request(method, url, json=data, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except Exception as e:
        logger.error(f"HA API error: {e}")
        return None


def send_notification(title: str, message: str, data: dict = None):
    """Send a notification via Home Assistant."""
    settings = get_settings()
    service = settings.get("notification_service", NOTIFICATION_SERVICE)
    # service format: notify.notify -> services/notify/notify
    parts = service.split(".")
    if len(parts) == 2:
        endpoint = f"services/{parts[0]}/{parts[1]}"
    else:
        endpoint = f"services/notify/notify"

    payload = {"title": title, "message": message}
    if data:
        payload["data"] = data

    result = ha_api("POST", endpoint, payload)
    logger.info(f"Notification sent: {title} -> {result}")
    return result


def send_reminder_for_tomorrow():
    """Check if there are bins to put out tomorrow and send a reminder."""
    settings = get_settings()
    if not settings.get("reminder_enabled", True):
        return

    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    calendar = get_calendar()

    if tomorrow in calendar:
        bins = calendar[tomorrow]
        bin_names = []
        for b in bins:
            if b == "jaune":
                bin_names.append("🟡 Poubelle Jaune (recyclables)")
            elif b == "verte":
                bin_names.append("🟢 Poubelle Verte (ordures)")

        if bin_names:
            bin_list = "\n".join(bin_names)
            message = f"Demain c'est jour de collecte !\n\n{bin_list}\n\nPensez à sortir vos poubelles ce soir."

            # Send notification with actionable buttons
            send_notification(
                title="🗑️ Rappel Poubelles",
                message=message,
                data={
                    "actions": [
                        {
                            "action": "BINS_DONE",
                            "title": "✅ C'est fait !",
                        },
                        {
                            "action": "BINS_SNOOZE",
                            "title": "⏰ Rappeler dans 1h",
                        },
                    ],
                    "tag": f"poubelles_{tomorrow}",
                    "persistent": True,
                },
            )
            logger.info(f"Reminder sent for {tomorrow}: {bins}")


def send_snooze_reminder():
    """Send a follow-up reminder after snooze."""
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    calendar = get_calendar()
    if tomorrow in calendar:
        send_notification(
            title="🗑️ Rappel Poubelles (relance)",
            message="N'oubliez pas de sortir vos poubelles !",
            data={
                "actions": [
                    {"action": "BINS_DONE", "title": "✅ C'est fait !"},
                    {"action": "BINS_LATER", "title": "⏰ Plus tard"},
                ],
                "tag": f"poubelles_{tomorrow}",
                "persistent": True,
            },
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler()


def setup_scheduler():
    settings = get_settings()
    hour = settings.get("reminder_hour", REMINDER_HOUR)
    minute = settings.get("reminder_minute", REMINDER_MINUTE)

    # Remove existing jobs
    scheduler.remove_all_jobs()

    # Daily reminder
    scheduler.add_job(
        send_reminder_for_tomorrow,
        "cron",
        hour=hour,
        minute=minute,
        id="daily_reminder",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
    logger.info(f"Scheduler configured: reminder at {hour:02d}:{minute:02d}")


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    calendar = get_calendar()
    history = get_history()
    settings = get_settings()

    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    # Next collections
    future_dates = sorted(
        [d for d in calendar.keys() if d >= today_str],
        key=lambda x: x
    )[:10]

    next_collections = []
    for d in future_dates:
        bins = calendar[d]
        status = history.get(d, {})
        next_collections.append({
            "date": d,
            "date_formatted": format_date_fr(d),
            "bins": bins,
            "status": status,
            "is_tomorrow": d == tomorrow,
            "is_today": d == today_str,
        })

    # Stats
    total_scheduled = len(calendar)
    total_confirmed = sum(
        1 for d, s in history.items()
        if any(v == "done" for v in s.values())
    )
    total_missed = sum(
        1 for d, s in history.items()
        if any(v == "missed" for v in s.values())
    )

    return render_template(
        "index.html",
        next_collections=next_collections,
        settings=settings,
        stats={
            "total": total_scheduled,
            "confirmed": total_confirmed,
            "missed": total_missed,
        },
        ingress_entry=INGRESS_ENTRY,
        has_ocr=HAS_OCR,
    )


@app.route("/api/upload-calendar", methods=["POST"])
def upload_calendar():
    """Upload and OCR a calendar image or PDF."""
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier envoyé"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nom de fichier vide"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Extension .{ext} non supportée"}), 400

    filename = secure_filename(file.filename)
    filepath = str(UPLOAD_DIR / filename)
    file.save(filepath)

    # Extract text
    if ext == "pdf":
        raw_text = extract_text_from_pdf(filepath)
    else:
        raw_text = extract_text_from_image(filepath)

    if not raw_text.strip():
        return jsonify({
            "error": "Impossible d'extraire le texte. Essayez avec une image plus nette ou saisissez les dates manuellement.",
            "raw_text": "",
        }), 422

    # Parse dates
    year = request.form.get("year", datetime.now().year, type=int)
    parsed = parse_calendar_text(raw_text, year)

    # Merge with existing calendar
    existing = get_calendar()
    for d, bins in parsed.items():
        if d in existing:
            existing[d] = list(set(existing[d] + bins))
        else:
            existing[d] = bins
    save_calendar(existing)

    return jsonify({
        "success": True,
        "raw_text": raw_text,
        "dates_found": len(parsed),
        "parsed": parsed,
        "total_calendar": len(existing),
    })


@app.route("/api/calendar", methods=["GET"])
def api_get_calendar():
    return jsonify(get_calendar())


@app.route("/api/calendar", methods=["POST"])
def api_set_calendar():
    """Add or update dates manually."""
    data = request.get_json()
    calendar = get_calendar()

    if "dates" in data:
        # Batch update: {"dates": {"2025-03-15": ["jaune"], ...}}
        for d, bins in data["dates"].items():
            calendar[d] = bins
    elif "date" in data and "bins" in data:
        # Single update
        calendar[data["date"]] = data["bins"]

    save_calendar(calendar)
    return jsonify({"success": True, "total": len(calendar)})


@app.route("/api/calendar/delete", methods=["POST"])
def api_delete_date():
    data = request.get_json()
    calendar = get_calendar()
    d = data.get("date")
    if d and d in calendar:
        del calendar[d]
        save_calendar(calendar)
    return jsonify({"success": True})


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    """Confirm that bins have been put out."""
    data = request.get_json()
    d = data.get("date")
    bin_type = data.get("bin_type")
    status = data.get("status", "done")  # done / missed

    if not d or not bin_type:
        return jsonify({"error": "date et bin_type requis"}), 400

    history = get_history()
    if d not in history:
        history[d] = {}
    history[d][bin_type] = status
    save_history(history)

    return jsonify({"success": True})


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(get_settings())


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json()
    settings = get_settings()
    settings.update(data)
    save_settings(settings)

    # Reconfigure scheduler
    setup_scheduler()

    return jsonify({"success": True, "settings": settings})


@app.route("/api/test-notification", methods=["POST"])
def api_test_notification():
    """Send a test notification."""
    send_notification(
        title="🗑️ Test - Poubelles",
        message="Ceci est un test du système de rappel poubelles !",
    )
    return jsonify({"success": True})


@app.route("/api/history", methods=["GET"])
def api_get_history():
    return jsonify(get_history())


@app.route("/api/next-collection", methods=["GET"])
def api_next_collection():
    """Get the next collection date and type."""
    calendar = get_calendar()
    today_str = date.today().isoformat()
    future = sorted([d for d in calendar.keys() if d >= today_str])
    if future:
        next_date = future[0]
        return jsonify({
            "date": next_date,
            "date_formatted": format_date_fr(next_date),
            "bins": calendar[next_date],
        })
    return jsonify({"date": None, "bins": []})


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
]


def format_date_fr(date_str: str) -> str:
    try:
        d = date.fromisoformat(date_str)
        jour = JOURS_FR[d.weekday()]
        mois = MOIS_FR[d.month]
        return f"{jour} {d.day} {mois} {d.year}"
    except Exception:
        return date_str


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup_scheduler()
    port = int(os.environ.get("INGRESS_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
