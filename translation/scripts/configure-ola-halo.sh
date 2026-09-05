#!/bin/sh
# Idempotently reproduce the OLA FTDI setup proven on rpi05.
set -eu

config_dir=${OLA_CONFIG_DIR:-/etc/ola}
adapter_serial=${OLA_FTDI_SERIAL:-BG03CXL2}
universe=${OLA_UNIVERSE:-1}

if [ ! -d "$config_dir" ]; then
  echo "OLA configuration directory not found: $config_dir" >&2
  echo "Install the Raspberry Pi OS ola package first." >&2
  exit 1
fi

set_value() {
  file=$1
  key=$2
  value=$3
  if [ ! -f "$file" ]; then
    echo "Expected OLA plugin configuration not found: $file" >&2
    exit 1
  fi
  if grep -q "^${key}[[:space:]]*=" "$file"; then
    sed -i "s|^${key}[[:space:]]*=.*|${key} = ${value}|" "$file"
  else
    printf '%s = %s\n' "$key" "$value" >> "$file"
  fi
}

set_value "$config_dir/ola-ftdidmx.conf" enabled true
set_value "$config_dir/ola-ftdidmx.conf" frequency 30
set_value "$config_dir/ola-stageprofi.conf" enabled false
set_value "$config_dir/ola-opendmx.conf" enabled false
# The entire Serial USB plugin must be off; ignore_device alone did not release
# the FTDI plugin on rpi05.
set_value "$config_dir/ola-usbserial.conf" enabled false

adapter_device=
for candidate in /dev/ttyUSB*; do
  [ -e "$candidate" ] || continue
  if udevadm info --query=property --name="$candidate" 2>/dev/null | grep -q "^ID_SERIAL_SHORT=${adapter_serial}$"; then
    adapter_device=$candidate
    break
  fi
done
if [ -n "$adapter_device" ]; then
  set_value "$config_dir/ola-usbserial.conf" ignore_device "$adapter_device"
else
  echo "FTDI serial $adapter_serial is not currently visible; plugin configuration was still applied." >&2
fi

systemctl restart olad.service

# Device aliases are assigned dynamically. Resolve the output by serial every
# time instead of storing the rpi05 test alias (8).
attempt=0
patch_target=
while [ "$attempt" -lt 10 ] && [ -z "$patch_target" ]; do
  attempt=$((attempt + 1))
  patch_target=$(ola_dev_info 2>/dev/null | awk -v serial="$adapter_serial" '
    /^Device [0-9]+:/ {
      device=$2
      sub(":", "", device)
      matched=index($0, serial) > 0
    }
    matched && /^[[:space:]]+port [0-9]+, OUT/ {
      port=$2
      sub(",", "", port)
      print device, port
      exit
    }')
  [ -n "$patch_target" ] || sleep 1
done

if [ -z "$patch_target" ]; then
  echo "OLA did not expose an output for FTDI serial $adapter_serial; universe $universe was not patched." >&2
  exit 1
fi

set -- $patch_target
ola_patch -d "$1" -p "$2" -u "$universe"
echo "Patched FTDI serial $adapter_serial (current OLA device $1, port $2) to universe $universe."
