#!/bin/bash
# 🏛 MALXGMN EMPIRE - SERVER 2 (CORE ENGINE & STORAGE) DEPLOY SCRIPT - BRD
# Menjalankan Python API, Bot Watcher, dan mengelola Session & JSON Storage

set -e

PROJECT_DIR="/var/www/SCRIPTS_BRD"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="$PROJECT_DIR/core_brd.log"
APP_NAME="core_brd"

echo "=========================================="
echo "   MALXGMN EMPIRE - SERVER 2 (BRD CORE)   "
echo "=========================================="

echo "[+] Moving to core directory..."
cd "$PROJECT_DIR" || { echo "[!] Directory not found: $PROJECT_DIR"; exit 1; }

# ---------------------------------------------------------
# 1️⃣ BACKUP DATA JSON (PERLINDUNGAN DATA KORBAN)
# ---------------------------------------------------------
JSON_DIR="$PROJECT_DIR/json"
BACKUP_DIR="$PROJECT_DIR/json_backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "$JSON_DIR" ] && [ "$(ls -A "$JSON_DIR"/*.json 2>/dev/null)" ]; then
    echo "[+] Backing up JSON database before restart..."
    mkdir -p "$BACKUP_DIR"
    cp "$JSON_DIR"/*.json "$BACKUP_DIR/" 2>/dev/null && echo "[✔] Backup saved to: $BACKUP_DIR" || echo "[!] No JSON files to backup"
else
    echo "[*] No JSON files to backup (first deploy or empty)"
fi

# Simpan 5 backup terakhir
ls -dt "$PROJECT_DIR"/json_backup_* 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true

# ---------------------------------------------------------
# 2️⃣ HENTIKAN LAYANAN LAMA (ANTI-ZOMBIE PROCESS)
# ---------------------------------------------------------
echo "[+] Stopping previous Python processes gracefully..."
pkill -SIGTERM -f "$PROJECT_DIR/setup.py" || true
pkill -SIGTERM -f "$PROJECT_DIR/main.py" || true
pkill -SIGTERM -f "$PROJECT_DIR/api.py" || true

echo "[*] Waiting 5 seconds for file write completion..."
sleep 5

pkill -9 -f "$PROJECT_DIR/setup.py" || true
pkill -9 -f "$PROJECT_DIR/main.py" || true
pkill -9 -f "$PROJECT_DIR/api.py" || true
sleep 1

# ---------------------------------------------------------
# 3️⃣ AKTIFKAN VIRTUALENV & JALANKAN PM2
# ---------------------------------------------------------
PYTHON_BIN="python3"
if [ -d "$VENV_DIR" ]; then
    echo "[+] Virtual environment found: $VENV_DIR"
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    echo "[!] Virtualenv not found, using system python"
fi

touch "$LOG_FILE"

echo "[+] Starting Core Engine via PM2..."
pm2 delete "$APP_NAME" 2>/dev/null || true
pm2 start setup.py --name "$APP_NAME" --interpreter "$PYTHON_BIN" -- --mode=2
pm2 save

echo "=========================================="
echo "    SERVER 2 (BRD CORE) ACTIVE & READY   "
echo "=========================================="
echo "[✔] API Port: 5000"
echo "[✔] Sessions: $PROJECT_DIR/sessions/"
echo "[✔] JSON Storage: $PROJECT_DIR/json/"
echo "[✔] Logs: pm2 logs $APP_NAME"
echo "=========================================="
