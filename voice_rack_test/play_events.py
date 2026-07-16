import sys
import signal
import time
import numpy as np
import pandas as pd
from pathlib import Path

# ---------------------------------------------------
# Path setup
# ---------------------------------------------------

sys.path.append(
    str(Path(__file__).resolve().parent / "src")
)

from configs.runtime_config import RUNTIME_CONFIG
from events.playback_selection import (
    select_random_segment,
    rebase_playback_time
)
from runtime.gpio_backend import GPIOBackend
from runtime.pin_config import PIN_MAP
from runtime.router import EventRouter
from runtime.clock import RealtimeClock
from events.filtering import filter_events_by_date


# ---------------------------------------------------
# Global shutdown registry
# ---------------------------------------------------

shutdown_hooks = []
_shutdown_in_progress = False


def register_shutdown_hook(fn):
    shutdown_hooks.append(fn)


def shutdown():
    global _shutdown_in_progress

    if _shutdown_in_progress:
        return

    _shutdown_in_progress = True

    print("\n[SHUTDOWN] Cleaning up hardware...")

    for fn in shutdown_hooks:
        try:
            fn()
        except Exception as e:
            print(f"[SHUTDOWN ERROR] {e}")

    print("[SHUTDOWN] Complete")


def signal_handler(sig, frame):
    print(f"\n[SIGNAL] Received {sig}, shutting down...")
    shutdown()
    sys.exit(0)


# Attach signal handlers (Ctrl+C + systemd stop)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ---------------------------------------------------
# Config
# ---------------------------------------------------

playback_cfg = RUNTIME_CONFIG["playback"]

PLAYBACK_START = playback_cfg["start_date"]
PLAYBACK_END = playback_cfg["end_date"]


# ---------------------------------------------------
# Load events
# ---------------------------------------------------

events = np.load("events.npy", allow_pickle=True)
events = list(events)

print(f"Loaded raw events: {len(events)}")

events = filter_events_by_date(events, PLAYBACK_START, PLAYBACK_END)

print(f"Events after filtering: {len(events)}")

if len(events) == 0:
    raise RuntimeError("No events remain after playback filtering")


# ---------------------------------------------------
# Rebase timeline
# ---------------------------------------------------

t0 = events[0]["playback_time"]

for e in events:
    e["playback_time"] -= t0


events = sorted(events, key=lambda e: e["playback_time"])


# ---------------------------------------------------
# Optional segment selection
# ---------------------------------------------------

if playback_cfg["random_segment"]:

    duration_seconds = playback_cfg["segment_minutes"] * 60

    events = select_random_segment(events, duration_seconds)
    events = rebase_playback_time(events)


# ---------------------------------------------------
# Debug
# ---------------------------------------------------

print("\nFIRST 10 EVENTS:\n")

for e in events[:10]:
    print(e["playback_time"], e["timestamp"], e["target"])


print(
    f"\nPlayback window: "
    f"{events[0]['timestamp']} → {events[-1]['timestamp']}"
)

print(f"Loaded {len(events)} events")


# ---------------------------------------------------
# Runtime setup
# ---------------------------------------------------

solenoid_backend = GPIOBackend(PIN_MAP)
register_shutdown_hook(solenoid_backend.shutdown)

backends = {"solenoid": solenoid_backend}
router = EventRouter(backends)
clock = RealtimeClock()


# ---------------------------------------------------
# Main playback loop
# ---------------------------------------------------

try:

    for event in events:

        print("TARGET:", event["playback_time"])
        target_time = event["playback_time"]

        while clock.now() < target_time:
            time.sleep(0.001)

        print(
            f"{pd.Timestamp(event['timestamp']).strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{event['target']} | "
            f"{event['metadata']['frequency']:.2f} Hz"
        )

        router.dispatch(event)


finally:
    # ALWAYS run even on crash / Ctrl+C fallback
    shutdown()
