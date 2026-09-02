#!/usr/bin/env bash
# Run on the Raspberry Pi from the translation directory.
set -euo pipefail

sudo apt update
sudo apt install -y python3-venv python3-pip python3-gpiozero python3-lgpio

python3 -m venv --system-site-packages translation_venv
translation_venv/bin/python -m pip install --upgrade pip
translation_venv/bin/python -m pip install -r requirements/requirements_translation.txt

echo "Translation environment created at $(pwd)/translation_venv"
echo "Create whisper_venv separately from requirements/requirements_whisper.txt for whisper_runtime.py."
