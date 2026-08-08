#!/usr/bin/env bash
# Run on the Raspberry Pi from the translation directory.
set -euo pipefail

sudo apt update
sudo apt install -y python3-venv python3-pip python3-gpiozero python3-lgpio

python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/requirements_translation.txt

echo "Pi environment created at $(pwd)/.venv"
