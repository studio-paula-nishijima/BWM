#!/bin/sh
# Idempotently configure OLA plugins for the known FTDI Halo adapter.
set -eu
config_dir=${OLA_CONFIG_DIR:-}
if [ -z "$config_dir" ]; then
  for candidate in /var/lib/ola/conf /etc/ola; do
    if [ -d "$candidate" ]; then config_dir=$candidate; break; fi
  done
fi
if [ -z "$config_dir" ] || [ ! -d "$config_dir" ]; then
  echo 'Cannot find OLA configuration directory. Install the distribution ola package first, or set OLA_CONFIG_DIR.' >&2
  exit 1
fi
printf 'enabled = true\nfrequency = 30\n' > "$config_dir/ola-ftdidmx.conf"
printf 'enabled = false\n' > "$config_dir/ola-stageprofi.conf"
printf 'enabled = false\n' > "$config_dir/ola-opendmx.conf"
printf 'enabled = false\n' > "$config_dir/ola-usbserial.conf"
echo "OLA plugin configuration written to $config_dir. Verify FTDI serial BG03CXL2 and patch its output to universe 1 with ola_dev_info/ola_patch."
