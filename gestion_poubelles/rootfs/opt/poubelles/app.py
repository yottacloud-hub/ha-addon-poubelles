#!/usr/bin/env python3
"""
Gestion Poubelles - Add-on Home Assistant
Gère les rappels de sortie des poubelles jaune et verte.
"""

import os
import sys
import json
import re
import logging
import calendar as cal_module
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
        "reminder_repeat_minutes": 30,
        "reminder_repeat_max": 5,
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
# Color-based calendar parsing (grid-style calendars like Toulouse Métropole)
# ---------------------------------------------------------------------------

def classify_cell_color(r, g, b):
    """Classify a cell background color as a bin type.

    Returns 'jaune' for yellow/gold (recyclables),
    'verte' for gray (ordures ménagères), or None.
    """
    # White or very light = no collection
    # Use min channel to catch near-white cells (e.g. 235, 240, 238)
    if min(r, g, b) > 205:
        return None

    # Yellow/gold: R and G are high, B is distinctly lower
    if r > 170 and g > 140 and b < 160 and (r - b) > 35:
        return "jaune"

    # Gray (neutral, possibly with slight warm/green tint)
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    if max_c - min_c < 55 and 110 < max_c < 205:
        return "verte"

    return None


def parse_calendar_by_color(filepath, year=None):
    """Parse a grid-style waste calendar by detecting cell background colors.

    Works with calendars where:
    - Columns represent months
    - Rows represent days (1-31)
    - Gray background = ordures ménagères (verte)
    - Yellow/gold background = emballages recyclables (jaune)
    """
    if not HAS_OCR:
        logger.warning("Color parser: OCR not available")
        return {}

    try:
        # Load image
        if filepath.lower().endswith('.pdf'):
            if not HAS_PDF:
                return {}
            pages = convert_from_path(filepath, dpi=200)
            img = pages[0]
        else:
            img = Image.open(filepath)

        img_rgb = img.convert('RGB')
        w, h = img_rgb.size
        logger.info(f"Color parser: image size {w}x{h}")

        # Run OCR with bounding boxes
        ocr = pytesseract.image_to_data(
            img, lang='fra', output_type=pytesseract.Output.DICT
        )
        n = len(ocr['text'])

        # --- Find year ---
        if year is None:
            year = datetime.now().year
            for i in range(n):
                t = ocr['text'][i].strip()
                if len(t) == 4 and t.isdigit():
                    v = int(t)
                    if 2024 <= v <= 2040:
                        year = v
                        break
        logger.info(f"Color parser: year={year}")

        # --- Find month headers ---
        MONTH_LOOKUP = {
            'JANVIER': 1, 'FEVRIER': 2, 'MARS': 3,
            'AVRIL': 4, 'MAI': 5, 'JUIN': 6, 'JUILLET': 7,
            'AOUT': 8, 'SEPTEMBRE': 9, 'OCTOBRE': 10,
            'NOVEMBRE': 11, 'DECEMBRE': 12,
        }

        def normalize_upper(s):
            return (s.upper()
                    .replace('É', 'E').replace('È', 'E')
                    .replace('Û', 'U').replace('Ô', 'O')
                    .replace('Ê', 'E').replace('Â', 'A'))

        month_headers = []  # (month_num, center_x, bottom_y)
        for i in range(n):
            txt = normalize_upper(ocr['text'][i].strip())
            if txt in MONTH_LOOKUP and ocr['width'][i] > 15:
                m = MONTH_LOOKUP[txt]
                cx = ocr['left'][i] + ocr['width'][i] // 2
                by = ocr['top'][i] + ocr['height'][i]
                month_headers.append((m, cx, by))

        if not month_headers:
            logger.info("Color parser: no month headers found")
            return {}

        month_headers.sort(key=lambda x: x[1])
        logger.info(f"Color parser: found months {[m for m, _, _ in month_headers]}")

        # --- Column boundaries ---
        cols = []
        for idx, (m, cx, by) in enumerate(month_headers):
            if idx == 0:
                gap = (month_headers[1][1] - cx) if len(month_headers) > 1 else cx
                xl = max(0, cx - gap // 2)
            else:
                xl = (month_headers[idx - 1][1] + cx) // 2

            if idx == len(month_headers) - 1:
                gap = (cx - month_headers[idx - 1][1]) if idx > 0 else (w - cx)
                xr = min(w, cx + gap // 2)
            else:
                xr = (cx + month_headers[idx + 1][1]) // 2

            cols.append((m, xl, xr))

        # --- Find day numbers to determine row grid ---
        header_bottom = max(by for _, _, by in month_headers) + 5

        day_positions = []  # (day_num, x, y_center)
        for i in range(n):
            txt = ocr['text'][i].strip()
            if not txt.isdigit():
                continue
            d = int(txt)
            if d < 1 or d > 31:
                continue
            y_top = ocr['top'][i]
            if y_top < header_bottom:
                continue
            yc = y_top + ocr['height'][i] // 2
            x = ocr['left'][i]
            day_positions.append((d, x, yc))

        if not day_positions:
            logger.info("Color parser: no day numbers found below headers")
            return {}

        # Assign days to columns
        col_days = {m: [] for m, _, _ in cols}
        for d, x, yc in day_positions:
            for m, xl, xr in cols:
                if xl - 20 <= x <= xr + 20:
                    col_days[m].append((d, yc))
                    break

        # Find column with most days for row height calculation
        best_col = max(col_days, key=lambda m: len(col_days[m]))
        if not col_days[best_col]:
            return {}

        # Deduplicate and sort
        seen = set()
        unique = []
        for d, y in sorted(col_days[best_col], key=lambda x: x[1]):
            if d not in seen:
                seen.add(d)
                unique.append((d, y))
        unique.sort(key=lambda x: x[0])

        if len(unique) < 2:
            logger.info("Color parser: not enough day positions")
            return {}

        # Calculate average row height
        heights = []
        for j in range(1, len(unique)):
            d1, y1 = unique[j - 1]
            d2, y2 = unique[j]
            if d2 > d1 and y2 > y1:
                rh = (y2 - y1) / (d2 - d1)
                if rh > 3:
                    heights.append(rh)

        if not heights:
            logger.info("Color parser: could not compute row height")
            return {}

        row_h = sum(heights) / len(heights)

        # Find day-1 Y position
        day1_y = None
        for d, y in unique:
            if d == 1:
                day1_y = y
                break
        if day1_y is None:
            d0, y0 = unique[0]
            day1_y = y0 - (d0 - 1) * row_h

        logger.info(f"Color parser: row_height={row_h:.1f}, day1_y={day1_y:.1f}")

        # --- Sample colors for each cell ---
        result = {}

        for month, xl, xr in cols:
            col_cx = (xl + xr) // 2
            max_day = cal_module.monthrange(year, month)[1]

            for day in range(1, max_day + 1):
                cell_y = int(day1_y + (day - 1) * row_h)

                # Sample background pixels across the cell
                samples = []
                sx_range = int((xr - xl) * 0.25)
                sy_range = max(2, int(row_h * 0.25))

                step_x = max(1, sx_range // 5)
                step_y = max(1, sy_range // 3)

                for dx in range(-sx_range, sx_range + 1, step_x):
                    for dy in range(-sy_range, sy_range + 1, step_y):
                        sx = max(0, min(col_cx + dx, w - 1))
                        sy = max(0, min(cell_y + dy, h - 1))
                        px = img_rgb.getpixel((sx, sy))
                        # Skip very dark pixels (text, grid lines)
                        if max(px) > 100:
                            samples.append(px)

                if len(samples) < 3:
                    continue

                # Take brighter half of samples (background, not text)
                samples.sort(key=lambda p: sum(p), reverse=True)
                bg = samples[:max(3, len(samples) // 2)]

                avg_r = sum(p[0] for p in bg) / len(bg)
                avg_g = sum(p[1] for p in bg) / len(bg)
                avg_b = sum(p[2] for p in bg) / len(bg)

                bt = classify_cell_color(avg_r, avg_g, avg_b)
                if bt:
                    try:
                        ds = date(year, month, day).isoformat()
                        result[ds] = [bt]
                    except ValueError:
                        pass

        logger.info(f"Color parser: found {len(result)} collection dates")
        return result

    except Exception as e:
        logger.error(f"Color parser error: {e}", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Home Assistant API helpers
# ---------------------------------------------------------------------------

def ha_api(method: str, endpoint: str, data: dict = None):
    """Call the Home Assistant Supervisor API."""
    if not SUPERVISOR_TOKEN:
        logger.warning("No SUPERVISOR_TOKEN set - cannot call HA API. "
                       "Check that homeassistant_api: true is in config.yaml")
        return None
    url = f"http://supervisor/core/api/{endpoint}"
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    logger.info(f"HA API call: {method} {url}")
    try:
        resp = requests.request(method, url, json=data, headers=headers, timeout=10)
        logger.info(f"HA API response: {resp.status_code} {resp.text[:200] if resp.text else '(empty)'}")
        resp.raise_for_status()
        try:
            return resp.json() if resp.text else {}
        except ValueError:
            return {"raw": resp.text}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"HA API connection error (is Supervisor reachable?): {e}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HA API HTTP error: {e} - Response: {resp.text[:500] if resp.text else '(empty)'}")
        return None
    except Exception as e:
        logger.error(f"HA API unexpected error: {e}", exc_info=True)
        return None


def get_notify_services():
    """Fetch available mobile notification services from Home Assistant."""
    result = ha_api("GET", "services")
    services = []
    if result and isinstance(result, list):
        for domain_info in result:
            if domain_info.get("domain") == "notify":
                for svc_name in domain_info.get("services", {}):
                    # Only keep mobile_app services (actual phone devices)
                    if "mobile_app" in svc_name:
                        services.append(f"notify.{svc_name}")
    services.sort()
    return services


def send_notification(title: str, message: str, data: dict = None):
    """Send a notification to all configured devices via Home Assistant."""
    settings = get_settings()
    devices = settings.get("notification_devices", [])

    # Backward compat: fall back to single service if no devices configured
    if not devices:
        old_service = settings.get("notification_service", NOTIFICATION_SERVICE)
        if old_service:
            devices = [old_service]

    if not devices:
        logger.warning("No notification devices configured")
        return None

    payload = {"title": title, "message": message}
    if data:
        payload["data"] = data

    results = []
    for service in devices:
        parts = service.split(".")
        if len(parts) == 2:
            endpoint = f"services/{parts[0]}/{parts[1]}"
        else:
            endpoint = f"services/notify/{service}"

        logger.info(f"Sending notification to {service}: {title}")
        result = ha_api("POST", endpoint, payload)
        results.append({"service": service, "result": result})

    logger.info(f"Notification results: {results}")
    return results


def _bins_confirmed_for(date_str):
    """Check if all bins for a date have been confirmed."""
    history = get_history()
    cal = get_calendar()
    if date_str not in cal:
        return True  # No bins = nothing to confirm
    bins = cal[date_str]
    statuses = history.get(date_str, {})
    return all(statuses.get(b) in ("done", "missed") for b in bins)


def _build_reminder_message(bins, is_followup=False):
    """Build notification message and data for a reminder."""
    bin_names = []
    for b in bins:
        if b == "jaune":
            bin_names.append("🟡 Poubelle Jaune (recyclables)")
        elif b == "verte":
            bin_names.append("🟢 Poubelle Verte (ordures)")

    bin_list = "\n".join(bin_names)
    prefix = "RAPPEL : " if is_followup else ""
    message = f"{prefix}Demain c'est jour de collecte !\n\n{bin_list}\n\nPensez à sortir vos poubelles ce soir."

    # Add tap action to open the addon panel + actionable confirm/miss buttons
    ingress = INGRESS_ENTRY or "/"
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    bin_label = " + ".join("Jaune" if b == "jaune" else "Verte" for b in bins)
    notif_data = {
        "url": ingress,           # iOS companion app
        "clickAction": ingress,   # Android companion app
        "tag": "poubelles_reminder",
        "actions": [
            {
                "action": f"POUBELLES_DONE_{tomorrow}",
                "title": f"✅ Sortie ({bin_label})",
            },
            {
                "action": f"POUBELLES_MISSED_{tomorrow}",
                "title": "❌ Pas sortie",
            },
            {
                "action": "URI",
                "title": "📋 Ouvrir",
                "uri": ingress,
            },
        ],
    }

    title = "🗑️ Rappel Poubelles" if not is_followup else "🗑️ Rappel Poubelles (relance)"
    return title, message, notif_data


def send_reminder_for_tomorrow():
    """Check if there are bins to put out tomorrow and send a reminder."""
    settings = get_settings()
    if not settings.get("reminder_enabled", True):
        return

    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    calendar = get_calendar()

    if tomorrow not in calendar:
        return

    bins = calendar[tomorrow]
    if not bins:
        return

    # Check if already confirmed
    if _bins_confirmed_for(tomorrow):
        logger.info(f"Bins for {tomorrow} already confirmed, skipping reminder")
        return

    title, message, data = _build_reminder_message(bins, is_followup=False)
    send_notification(title=title, message=message, data=data)
    logger.info(f"Reminder sent for {tomorrow}: {bins}")

    # Schedule follow-up reminders
    repeat_minutes = settings.get("reminder_repeat_minutes", 30)
    repeat_max = settings.get("reminder_repeat_max", 5)

    if repeat_minutes > 0 and repeat_max > 0:
        for i in range(1, repeat_max + 1):
            run_time = datetime.now() + timedelta(minutes=repeat_minutes * i)
            scheduler.add_job(
                send_followup_reminder,
                "date",
                run_date=run_time,
                args=[tomorrow, i],
                id=f"followup_{tomorrow}_{i}",
                replace_existing=True,
            )
        logger.info(f"Scheduled {repeat_max} follow-ups every {repeat_minutes}min for {tomorrow}")


def send_followup_reminder(date_str, attempt):
    """Send a follow-up reminder if not yet confirmed."""
    if _bins_confirmed_for(date_str):
        logger.info(f"Follow-up #{attempt} for {date_str}: already confirmed, cancelling remaining")
        # Cancel remaining follow-ups
        settings = get_settings()
        repeat_max = settings.get("reminder_repeat_max", 5)
        for j in range(attempt, repeat_max + 1):
            try:
                scheduler.remove_job(f"followup_{date_str}_{j}")
            except Exception:
                pass
        return

    calendar = get_calendar()
    bins = calendar.get(date_str, [])
    if not bins:
        return

    title, message, data = _build_reminder_message(bins, is_followup=True)
    send_notification(title=title, message=message, data=data)
    logger.info(f"Follow-up #{attempt} sent for {date_str}")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler()


def setup_scheduler():
    settings = get_settings()
    hour = settings.get("reminder_hour", REMINDER_HOUR)
    minute = settings.get("reminder_minute", REMINDER_MINUTE)

    # Remove only the daily reminder job (keep any active follow-ups)
    try:
        scheduler.remove_job("daily_reminder")
    except Exception:
        pass

    # Daily reminder
    scheduler.add_job(
        send_reminder_for_tomorrow,
        "cron",
        hour=hour,
        minute=minute,
        id="daily_reminder",
        replace_existing=True,
    )

    # Periodic sensor update (every 5 min)
    try:
        scheduler.remove_job("sensor_update")
    except Exception:
        pass
    scheduler.add_job(
        update_ha_sensors,
        "interval",
        minutes=5,
        id="sensor_update",
        replace_existing=True,
    )

    # Poll command sensor every 3 seconds for card confirmations
    try:
        scheduler.remove_job("command_poll")
    except Exception:
        pass
    scheduler.add_job(
        poll_command_sensor,
        "interval",
        seconds=3,
        id="command_poll",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
    logger.info(f"Scheduler configured: reminder at {hour:02d}:{minute:02d}")


# ---------------------------------------------------------------------------
# HA sensor entities + card auto-install
# ---------------------------------------------------------------------------

def update_ha_sensors():
    """Create/update HA sensor entities so dashboard cards can display data."""
    if not SUPERVISOR_TOKEN:
        return

    calendar_data = get_calendar()
    history = get_history()
    today = date.today()
    today_str = today.isoformat()
    tomorrow_str = (today + timedelta(days=1)).isoformat()

    future = sorted([d for d in calendar_data.keys() if d >= today_str])[:10]

    upcoming = []
    for d in future:
        bins = calendar_data[d]
        status = history.get(d, {})
        upcoming.append({
            "date": d,
            "date_formatted": format_date_fr(d),
            "bins": bins,
            "status": {b: status.get(b, "") for b in bins},
            "is_tomorrow": d == tomorrow_str,
            "is_today": d == today_str,
        })

    next_date = future[0] if future else None
    next_bins = calendar_data.get(next_date, []) if next_date else []

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        requests.post(
            "http://supervisor/core/api/states/sensor.poubelles_prochaine_collecte",
            headers=headers,
            json={
                "state": format_date_fr(next_date) if next_date else "Aucune",
                "attributes": {
                    "friendly_name": "Prochaine collecte poubelles",
                    "icon": "mdi:delete-variant",
                    "next_date": next_date or "",
                    "next_bins": next_bins,
                    "is_tomorrow": next_date == tomorrow_str if next_date else False,
                    "is_today": next_date == today_str if next_date else False,
                    "upcoming": upcoming,
                    "ingress_entry": INGRESS_ENTRY,
                    "addon_slug": "local_gestion_poubelles",
                    "total_scheduled": len(calendar_data),
                }
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"Failed to update HA sensor: {e}")


def install_lovelace_card():
    """Copy poubelles-card.js to /config/www/ for Lovelace dashboard use."""
    config_www = Path("/config/www")
    try:
        config_www.mkdir(parents=True, exist_ok=True)
        card_src = Path(__file__).parent / "static" / "poubelles-card.js"
        card_dst = config_www / "poubelles-card.js"
        if card_src.exists():
            import shutil
            shutil.copy2(card_src, card_dst)
            logger.info(f"Lovelace card installed: {card_dst}")
        else:
            logger.warning(f"Card source not found: {card_src}")
    except Exception as e:
        logger.warning(f"Failed to install Lovelace card: {e}")


def install_notification_automations():
    """Create HA package with automations to handle notification confirm/miss buttons."""
    if not SUPERVISOR_TOKEN:
        return

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available, skipping notification automation setup")
        return

    try:
        # 1. Write supervisor token to secrets.yaml (for rest_command auth)
        secrets_file = Path("/config/secrets.yaml")
        secrets = {}
        if secrets_file.exists():
            content = secrets_file.read_text()
            if content.strip():
                secrets = yaml.safe_load(content) or {}
        secrets["poubelles_supervisor_token"] = f"Bearer {SUPERVISOR_TOKEN}"
        secrets_file.write_text(yaml.dump(secrets, default_flow_style=False, allow_unicode=True))
        logger.info("Supervisor token written to secrets.yaml")

        # 2. Write package file manually (avoid yaml.dump quoting issues with Jinja templates)
        packages_dir = Path("/config/packages")
        packages_dir.mkdir(parents=True, exist_ok=True)

        pkg_file = packages_dir / "poubelles.yaml"
        pkg_content = f"""# Auto-generated by Gestion Poubelles addon - do not edit manually
rest_command:
  poubelles_set_command:
    url: "http://supervisor/core/api/states/sensor.poubelles_command"
    method: POST
    headers:
      Authorization: !secret poubelles_supervisor_token
      Content-Type: "application/json"
    payload: >-
      {{"state": "{{{{ status }}}}:{{{{ date }}}}:{{{{ bin_type }}}}:{{{{ as_timestamp(now()) | int }}}}",
       "attributes": {{"friendly_name": "Poubelles Command", "icon": "mdi:delete-check",
       "action": "{{{{ status }}}}", "date": "{{{{ date }}}}", "bin_type": "{{{{ bin_type }}}}",
       "timestamp": {{{{ as_timestamp(now()) | int }}}}}}}}

automation:
  - id: poubelles_notif_done
    alias: "Poubelles - Done via notification"
    description: "Cree automatiquement par l addon Poubelles"
    trigger:
      - platform: event
        event_type: mobile_app_notification_action
    condition:
      - condition: template
        value_template: >-
          {{{{ trigger.event.data.action is defined and
          trigger.event.data.action.startswith("POUBELLES_DONE_") }}}}
    action:
      - service: rest_command.poubelles_set_command
        data:
          status: "done"
          date: >-
            {{{{ trigger.event.data.action.replace("POUBELLES_DONE_", "") }}}}
          bin_type: "all"
    mode: queued

  - id: poubelles_notif_missed
    alias: "Poubelles - Missed via notification"
    description: "Cree automatiquement par l addon Poubelles"
    trigger:
      - platform: event
        event_type: mobile_app_notification_action
    condition:
      - condition: template
        value_template: >-
          {{{{ trigger.event.data.action is defined and
          trigger.event.data.action.startswith("POUBELLES_MISSED_") }}}}
    action:
      - service: rest_command.poubelles_set_command
        data:
          status: "missed"
          date: >-
            {{{{ trigger.event.data.action.replace("POUBELLES_MISSED_", "") }}}}
          bin_type: "all"
    mode: queued
"""
        pkg_file.write_text(pkg_content)
        logger.info(f"Package written to {pkg_file}")

        # 3. Ensure packages include in configuration.yaml
        config_file = Path("/config/configuration.yaml")
        if config_file.exists():
            config_content = config_file.read_text()
            if "packages:" not in config_content and "packages :" not in config_content:
                # Add packages include
                if "homeassistant:" in config_content:
                    config_content = config_content.replace(
                        "homeassistant:",
                        "homeassistant:\n  packages: !include_dir_named packages",
                        1,
                    )
                else:
                    config_content += "\nhomeassistant:\n  packages: !include_dir_named packages\n"
                config_file.write_text(config_content)
                logger.info("Added packages include to configuration.yaml")

        # 4. Reload automations and rest_commands
        requests.post(
            "http://supervisor/core/api/services/automation/reload",
            headers=headers, timeout=10,
        )
        logger.info("Notification automations installed and reloaded")

    except Exception as e:
        logger.warning(f"Failed to install notification automations: {e}")


def poll_command_sensor():
    """Poll sensor.poubelles_command for confirm/miss actions from the card."""
    if not SUPERVISOR_TOKEN:
        return
    try:
        resp = requests.get(
            "http://supervisor/core/api/states/sensor.poubelles_command",
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return
        data = resp.json()
        state = data.get("state", "")
        if not state or state == "idle" or state == "unknown":
            return

        attrs = data.get("attributes", {})
        action = attrs.get("action", "")
        cmd_date = attrs.get("date", "")
        bin_type = attrs.get("bin_type", "")
        ts = attrs.get("timestamp", 0)

        if not action or not cmd_date or not bin_type:
            return

        # Check we haven't already processed this command (by timestamp)
        last_ts = getattr(poll_command_sensor, "_last_ts", 0)
        if ts <= last_ts:
            return
        poll_command_sensor._last_ts = ts

        # Execute the confirmation
        logger.info(f"Card command: {action} {cmd_date} {bin_type}")
        history = get_history()
        calendar_data = get_calendar()
        if cmd_date not in history:
            history[cmd_date] = {}

        # "all" means confirm all bins for that date (from notification actions)
        if bin_type == "all":
            bins_for_date = calendar_data.get(cmd_date, [])
            for b in bins_for_date:
                history[cmd_date][b] = action
        else:
            history[cmd_date][bin_type] = action
        save_history(history)

        # Cancel follow-ups if all confirmed
        if _bins_confirmed_for(cmd_date):
            settings = get_settings()
            repeat_max = settings.get("reminder_repeat_max", 5)
            for i in range(1, repeat_max + 1):
                try:
                    scheduler.remove_job(f"followup_{cmd_date}_{i}")
                except Exception:
                    pass
            logger.info(f"All bins confirmed for {cmd_date} via card")

        # Update sensors with new data
        update_ha_sensors()

        # Reset command sensor to idle
        requests.post(
            "http://supervisor/core/api/states/sensor.poubelles_command",
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "state": "idle",
                "attributes": {
                    "friendly_name": "Poubelles Command",
                    "icon": "mdi:delete-check",
                },
            },
            timeout=5,
        )
    except Exception as e:
        logger.debug(f"Command poll error: {e}")


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
        now_year=datetime.now().year,
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

    year = request.form.get("year", datetime.now().year, type=int)

    # Try color-based grid detection first (works with Toulouse Métropole style)
    logger.info(f"Attempting color-based calendar parsing for {filepath}")
    parsed = parse_calendar_by_color(filepath, year)
    raw_text = ""

    if parsed:
        raw_text = f"Détection par couleur : {len(parsed)} dates de collecte trouvées."
        logger.info(f"Color parser succeeded: {len(parsed)} dates")
    else:
        # Fall back to text-based OCR parsing
        logger.info("Color parser found nothing, falling back to text OCR")
        if ext == "pdf":
            raw_text = extract_text_from_pdf(filepath)
        else:
            raw_text = extract_text_from_image(filepath)

        if not raw_text.strip():
            return jsonify({
                "error": "Impossible d'extraire le texte ou les couleurs. Essayez avec une image plus nette ou saisissez les dates manuellement.",
                "raw_text": "",
            }), 422

        parsed = parse_calendar_text(raw_text, year)

    if not parsed:
        return jsonify({
            "error": "Aucune date de collecte détectée. Essayez de saisir les dates manuellement.",
            "raw_text": raw_text,
        }), 422

    # Merge with existing calendar
    existing = get_calendar()
    for d, bins in parsed.items():
        if d in existing:
            existing[d] = list(set(existing[d] + bins))
        else:
            existing[d] = bins
    save_calendar(existing)
    update_ha_sensors()

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
            if bins:  # Only add non-empty entries
                calendar[d] = bins
    elif "date" in data and "bins" in data:
        # Single update
        calendar[data["date"]] = data["bins"]

    save_calendar(calendar)
    update_ha_sensors()
    return jsonify({"success": True, "total": len(calendar)})


@app.route("/api/calendar/clear", methods=["POST"])
def api_clear_calendar():
    """Clear all dates from the calendar."""
    save_calendar({})
    save_history({})
    update_ha_sensors()
    return jsonify({"success": True})


@app.route("/api/calendar/delete", methods=["POST"])
def api_delete_date():
    data = request.get_json()
    calendar = get_calendar()
    d = data.get("date")
    if d and d in calendar:
        del calendar[d]
        save_calendar(calendar)
    update_ha_sensors()
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

    # Cancel follow-up reminders if all bins confirmed
    if _bins_confirmed_for(d):
        settings = get_settings()
        repeat_max = settings.get("reminder_repeat_max", 5)
        for i in range(1, repeat_max + 1):
            try:
                scheduler.remove_job(f"followup_{d}_{i}")
            except Exception:
                pass
        logger.info(f"All bins confirmed for {d}, cancelled follow-up reminders")

    update_ha_sensors()
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
    results = send_notification(
        title="🗑️ Test - Poubelles",
        message="Ceci est un test du système de rappel poubelles !",
    )
    if results:
        errors = [r for r in results if r.get("result") is None]
        if errors:
            return jsonify({
                "success": False,
                "error": f"{len(errors)}/{len(results)} envois échoués. Vérifiez les logs.",
                "results": results,
            }), 500
    return jsonify({"success": True, "results": results})


@app.route("/api/notify-services", methods=["GET"])
def api_notify_services():
    """List available HA notification services (for device selection)."""
    services = get_notify_services()
    settings = get_settings()
    selected = settings.get("notification_devices", [])
    return jsonify({"services": services, "selected": selected})


@app.route("/api/notification-devices", methods=["POST"])
def api_set_notification_devices():
    """Save selected notification devices."""
    data = request.get_json()
    devices = data.get("devices", [])
    settings = get_settings()
    settings["notification_devices"] = devices
    save_settings(settings)
    logger.info(f"Notification devices updated: {devices}")
    return jsonify({"success": True, "devices": devices})


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
    # Log startup info for debugging
    logger.info("=" * 50)
    logger.info("Gestion Poubelles - Démarrage")
    logger.info(f"  SUPERVISOR_TOKEN: {'set (' + str(len(SUPERVISOR_TOKEN)) + ' chars)' if SUPERVISOR_TOKEN else 'NOT SET'}")
    logger.info(f"  NOTIFICATION_SERVICE: {NOTIFICATION_SERVICE}")
    logger.info(f"  REMINDER: {REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}")
    logger.info(f"  INGRESS_ENTRY: {INGRESS_ENTRY}")
    logger.info(f"  HAS_OCR: {HAS_OCR}, HAS_PDF: {HAS_PDF}")
    logger.info(f"  DATA_DIR: {DATA_DIR}")
    logger.info("=" * 50)

    setup_scheduler()
    install_lovelace_card()
    install_notification_automations()
    update_ha_sensors()
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    logger.info(f"Starting Gestion Poubelles on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
