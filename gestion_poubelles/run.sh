#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

echo "[INFO] Démarrage de l'addon Gestion Poubelles..."

# Read configuration from options.json
REMINDER_HOUR=$(jq -r '.reminder_hour' "$CONFIG_PATH")
REMINDER_MINUTE=$(jq -r '.reminder_minute' "$CONFIG_PATH")
NOTIFICATION_SERVICE=$(jq -r '.notification_service' "$CONFIG_PATH")

# Get ingress port from environment (set by Supervisor)
INGRESS_PORT="${INGRESS_PORT:-8099}"
INGRESS_ENTRY="${INGRESS_ENTRY:-/}"

export REMINDER_HOUR
export REMINDER_MINUTE
export NOTIFICATION_SERVICE
export SUPERVISOR_TOKEN
export INGRESS_ENTRY
export INGRESS_PORT

# Force unbuffered Python output so logs appear in real-time
export PYTHONUNBUFFERED=1

echo "[INFO] Configuration: reminder=${REMINDER_HOUR}:${REMINDER_MINUTE}, notification=${NOTIFICATION_SERVICE}"
echo "[INFO] Ingress port: ${INGRESS_PORT}, entry: ${INGRESS_ENTRY}"

if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo "[INFO] SUPERVISOR_TOKEN is set (length: ${#SUPERVISOR_TOKEN})"
else
    echo "[WARN] SUPERVISOR_TOKEN is NOT set - notifications will not work"
fi

cd /opt/poubelles
exec python3 -u app.py
