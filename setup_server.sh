#!/usr/bin/env bash
# ==============================================================================
# Setup script for running NopeRi on Oracle Cloud ARM (or any Linux server)
# ==============================================================================
set -e

WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(whoami)"

echo "=== Setting up Naukri-Automate on Linux / Oracle ARM ==="
echo "Working directory: $WORKDIR"
echo "Running as user:   $CURRENT_USER"

# 1. Install system prerequisites if needed
if command -v apt-get &> /dev/null; then
    echo "Updating system packages and installing Python 3 + venv..."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip build-essential libffi-dev
elif command -v dnf &> /dev/null; then
    echo "Installing Python 3 + development tools via dnf..."
    sudo dnf install -y python3 python3-pip gcc libffi-devel
fi

# 2. Setup Virtual Environment
if [ ! -d "$WORKDIR/venv" ]; then
    echo "Creating virtual environment at $WORKDIR/venv..."
    python3 -m venv "$WORKDIR/venv"
fi

echo "Installing/updating Python dependencies..."
"$WORKDIR/venv/bin/pip" install --upgrade pip
"$WORKDIR/venv/bin/pip" install -r "$WORKDIR/requirements.txt"

# 3. Generate systemd service file
SERVICE_FILE="/etc/systemd/system/naukri.service"
echo "Configuring systemd service at $SERVICE_FILE..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=NopeRi Naukri Automation Daemon
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$WORKDIR
ExecStart=$WORKDIR/venv/bin/python cron/scheduler.py
Restart=always
RestartSec=15
StandardOutput=append:$WORKDIR/scheduler.log
StandardError=append:$WORKDIR/scheduler.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable naukri

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Ensure your .env and config.json are set up in: $WORKDIR"
echo "2. Start the background service:"
echo "   sudo systemctl start naukri"
echo ""
echo "3. Useful management commands:"
echo "   Status:      sudo systemctl status naukri"
echo "   Stop:        sudo systemctl stop naukri"
echo "   Restart:     sudo systemctl restart naukri"
echo "   Live Logs:   journalctl -u naukri -f"
echo "                or: tail -f $WORKDIR/scheduler.log"
echo "========================================================"
