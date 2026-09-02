# Raspberry Pi autoplay services

The production runners remain independent at boot:

```text
rpi02: whisper-runtime.service -> translation/whisper_runtime.py
rpi03: play-events.service     -> translation/play_events.py
```

Both units use `After=local-fs.target`.  They deliberately do not use or wait
for `network-online.target`, Wi-Fi, Ethernet, MQTT, BLE, the person detector,
Translation availability, or Voice availability.  Transport setup failures are
handled by the runners as isolated degradation, so each process can start and
perform its local function independently.

## Paths and service behaviour

The Pi checkout location is `/home/raspi/BWM`.  Both units use
`WorkingDirectory=/home/raspi/BWM/translation`.

- `whisper-runtime.service` runs
  `/home/raspi/BWM/translation/whisper_venv/bin/python -u /home/raspi/BWM/translation/whisper_runtime.py`.
- `play-events.service` runs
  `/home/raspi/BWM/translation/translation_venv/bin/python -u /home/raspi/BWM/translation/play_events.py`.

`PYTHONUNBUFFERED=1` and `python -u` make existing console output promptly
available in journald.  The units are `Type=simple`, stop with the retained
10-second graceful stop window, restart only on process failure, and wait five
seconds before restarting.  SIGTERM reaches the runners' existing signal
handlers: Voice cleans up its timer, workers, controls and hardware; Translation
closes admission, cancels runtime work, stops playback, shuts down Halo lighting
when present, and quiesces GPIO.

## Install and operate

On the matching Pi, with the checkout and both required virtual environments
already present at the paths above:

```bash
cd /home/raspi/BWM/translation
chmod +x scripts/install-autoplay-services.sh
./scripts/install-autoplay-services.sh
```

The script copies both unit files to `/etc/systemd/system`, reloads systemd,
enables both services, restarts them, and displays their status.  The equivalent
manual commands are:

```bash
sudo install -m 0644 '/home/raspi/BWM/services/voice rack services/whisper-runtime.service' /etc/systemd/system/whisper-runtime.service
sudo install -m 0644 '/home/raspi/BWM/services/translation services/play-events.service' /etc/systemd/system/play-events.service
sudo systemctl daemon-reload
sudo systemctl enable whisper-runtime.service play-events.service
sudo systemctl start whisper-runtime.service play-events.service
sudo systemctl restart whisper-runtime.service play-events.service
sudo systemctl status whisper-runtime.service play-events.service
```

Live and current-boot logs:

```bash
journalctl -u whisper-runtime.service -f
journalctl -u play-events.service -f
journalctl -u whisper-runtime.service -b
journalctl -u play-events.service -b
journalctl -u whisper-runtime.service -n 200
journalctl -u play-events.service -n 200
```

## Pi validation

On rpi02, confirm `whisper-runtime.service` is active, `whisper_runtime.py` is
running, Voice reaches its normal local operational state without network, and
the journal updates live.  Deliberately terminate the process to confirm the
five-second `on-failure` restart; then run `sudo systemctl stop
whisper-runtime.service` and confirm its cleanup messages.

On rpi03, confirm `play-events.service` is active, `play_events.py` is running,
and Translation begins its initially-active session without network.  Confirm
the expected initial playback, local GPIO17 backup operation, journal output,
failure restart, and graceful stop with GPIO quiescence and Halo fade/blackout
when lighting is configured.

Do not automatically disable, remove, rename, or mask legacy services.  Before
deployment, manually check for conflicts: on rpi02 the legacy
`voice-rack.service` and `button-controller-voice.service` may conflict (the
latter also claims GPIO17); on rpi03 legacy `play-events.service` deployments
and `button-controller.service` may conflict.  Only the deployment operator
should decide how to resolve those legacy installations.
