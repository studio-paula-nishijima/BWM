#!/usr/bin/env bash
# Install the current BWM autoplay units on a Raspberry Pi.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
translation_dir="$(cd -- "$script_dir/.." && pwd)"
repo_dir="$(cd -- "$translation_dir/.." && pwd)"

if [[ "$translation_dir" != "/home/raspi/BWM/translation" ]]; then
    echo "This unit pair is configured for /home/raspi/BWM/translation; current checkout is $translation_dir." >&2
    echo "Deploy the checkout at /home/raspi/BWM before installing the units." >&2
    exit 1
fi

sudo install -m 0644 "$repo_dir/services/voice rack services/whisper-runtime.service" \
    /etc/systemd/system/whisper-runtime.service
sudo install -m 0644 "$repo_dir/services/translation services/play-events.service" \
    /etc/systemd/system/play-events.service
sudo systemctl daemon-reload
sudo systemctl enable whisper-runtime.service play-events.service
sudo systemctl restart whisper-runtime.service play-events.service
sudo systemctl --no-pager status whisper-runtime.service play-events.service
