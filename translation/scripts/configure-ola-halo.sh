#!/bin/sh
# Idempotently configure OLA plugins for the known FTDI Halo adapter.
set -eu
for config in /etc/ola/ola-ftdidmx.conf /etc/ola/ola-stageprofi.conf /etc/ola/ola-opendmx.conf /etc/ola/ola-usbserial.conf; do
  install -d -m 0755 /etc/ola
  : > "$config"
done
printf 'enabled = true\nfrequency = 30\n' > /etc/ola/ola-ftdidmx.conf
printf 'enabled = false\n' > /etc/ola/ola-stageprofi.conf
printf 'enabled = false\n' > /etc/ola/ola-opendmx.conf
printf 'enabled = false\n' > /etc/ola/ola-usbserial.conf
echo 'OLA plugin configuration written. Verify FTDI serial BG03CXL2 and patch its output to universe 1 with ola_dev_info/ola_patch.'
