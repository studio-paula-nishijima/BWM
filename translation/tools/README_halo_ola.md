# Halo 60x through OLA

The production path is `play-events -> OLA Python client -> olad -> FTDI DMX
plugin -> amaran Halo 60x`. No BWM application opens `/dev/ttyUSB*`.

On the Pi install the distribution OLA package and Python bindings, then run
`sudo systemctl enable --now olad.service`:

```bash
sudo apt update
sudo apt install ola python3-ola
```

Apply the repository provisioning script as root:

```bash
sudo sh /home/raspi/BWM/translation/scripts/configure-ola-halo.sh
sudo systemctl restart olad.service
ola_dev_info
ola_patch --help
```

The script disables the conflicting Open DMX, StageProfi, and USB-serial OLA
plugins and enables FTDI at 30 Hz. Confirm the detected FTDI device reports
serial `BG03CXL2` (VID/PID `0403:6001`) and patch its output port to universe 1
using the current device/port IDs shown by `ola_dev_info`; those IDs are dynamic
and are intentionally not stored in application config. Repeat the patch only
if OLA's device database changes. `ola_dev_info` and `ola_patch` make this
inspectable after reboots.

Test independently, then run the runtime:

```bash
python tools/halo60x_demo.py --live --universe 1 --static --brightness 100 --cct 2700
python tools/halo60x_demo.py --live --universe 1 --static --brightness 100 --cct 6500
```

The demo blacks out and withdraws its OLA source on exit. Do not leave the demo
running while `play-events` is authoritative for universe 1.
