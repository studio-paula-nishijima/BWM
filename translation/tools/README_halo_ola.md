# Halo 60x through OLA

The production path is `play-events -> persistent ola_streaming_client -> olad -> FTDI DMX
plugin -> amaran Halo 60x`. No BWM application opens `/dev/ttyUSB*`.

The authoritative rpi05 test installed only the Raspberry Pi OS/Debian OLA
package. It used the packaged system service and command-line client; the
separate Python bindings were not part of the successful hardware test:

```bash
sudo apt update
sudo apt install ola
sudo systemctl enable --now olad.service
```

Apply the repository provisioning script as root:

```bash
sudo sh /home/raspi/BWM/translation/scripts/configure-ola-halo.sh
sudo systemctl restart olad.service
ola_dev_info
ola_patch --help
```

The script reproduces the working `/etc/ola` configuration: FTDI DMX enabled at
30 Hz; StageProfi, Open DMX, and the complete Serial USB plugin disabled. It
then restarts the system `olad`, finds serial `BG03CXL2` (VID/PID `0403:6001`)
in `ola_dev_info`, and patches its current output port to universe 1. OLA device
numbers are dynamic and never hard-coded. Override the deployment identity with
`OLA_FTDI_SERIAL` and `OLA_UNIVERSE` when needed; `OLA_CONFIG_DIR` is available
only for an explicitly verified alternative daemon configuration directory.

Test independently, then run the runtime:

```bash
python tools/halo60x_demo.py --live --universe 1 --static --brightness 100 --cct 2700
python tools/halo60x_demo.py --live --universe 1 --static --brightness 100 --cct 6500
```

The demo and runtime each maintain one long-lived `ola_streaming_client` process
and feed it frames through stdin. Frames end at the fixture's final configured
slot: address 1 therefore sends the hardware-proven three values such as
`255,0,0`, rather than padding the universe to 512 slots. This avoids both the
observed full-frame output failure and state reversion from isolated short-lived
sources. Each client blacks out before withdrawing its source. Do not leave the
demo running while `play-events` is authoritative for universe 1.

The rpi05 proof did not record its exact Pi model or OS release. Query those on
the target rather than treating an assumed release as part of the contract.
