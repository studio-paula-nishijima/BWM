# Local and Raspberry Pi Python environments

The deployment target is a Raspberry Pi 5 running Raspberry Pi OS (Bookworm
or later).  Use Python 3.11 on a workstation so that language and standard
library behaviour matches the Pi target.

## Workstation (Windows)

After Python 3.11 is available, run this from `translation`:

```powershell
.\scripts\setup-local.ps1
.\scripts\run-local.ps1 -Target main
```

The local runner sets `GPIOZERO_PIN_FACTORY=mock`; GPIO calls have no physical
effect.  `-Target play-events` can be used after a suitable `events.npy` has
been generated.

`main.py` currently reads LamaH CSV files from paths under
`/home/raspi/BWMTest/lamah_data`.  Those source files are not included in this
workspace, so generating events locally requires either that dataset or a
local configuration pointing at a copy of it.

## Raspberry Pi

From the `translation` directory, run:

```bash
chmod +x scripts/setup-pi.sh
./scripts/setup-pi.sh
```

This matches the existing deployment notes: `gpiozero` and `lgpio` are supplied
by `apt`, and the virtual environment exposes those system packages.  It is
the only environment that can validate actual GPIO, I2C/PCA9685, ALSA, and the
ReSpeaker microphone.

The optional Whisper stack is separate because its pinned Torch versions need
to be available for the Pi's ARM64 platform; install it only on the Pi after
confirming compatible wheels.
