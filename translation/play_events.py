import signal
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from configs.runtime_config import RUNTIME_CONFIG
from events.filtering import filter_events_by_date
from events.playback_selection import rebase_playback_time, select_random_segment


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
        except Exception as exc:
            print(f"[SHUTDOWN ERROR] {exc}")
    print("[SHUTDOWN] Complete")


def signal_handler(sig, frame):
    print(f"\n[SIGNAL] Received {sig}, shutting down...")
    shutdown()
    sys.exit(0)


def prepare_events(events, playback_cfg):
    """Apply the released date-filter, rebase and segment-selection sequence."""
    events = filter_events_by_date(
        events, playback_cfg["start_date"], playback_cfg["end_date"]
    )
    if not events:
        raise RuntimeError("No events remain after playback filtering")

    t0 = events[0]["playback_time"]
    for event in events:
        event["playback_time"] -= t0
    events = sorted(events, key=lambda event: event["playback_time"])

    if playback_cfg["random_segment"]:
        events = select_random_segment(events, playback_cfg["segment_minutes"] * 60)
        events = rebase_playback_time(events)
    return events


def play(events, router, clock, sleep_resolution):
    """Dispatch in score order after each released target-time wait."""
    for event in events:
        print("TARGET:", event["playback_time"])
        target_time = event["playback_time"]
        while clock.now() < target_time:
            time.sleep(sleep_resolution)
        print(
            f"{pd.Timestamp(event['timestamp']).strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{event['target']} | {event['metadata']['frequency']:.2f} Hz"
        )
        router.dispatch(event)


def main():
    # Hardware imports stay in the executable path: test/import operations do
    # not require a Raspberry Pi or gpiozero.
    from configs.runtime_config import PROJECT_ROOT, get_solenoid_pin_map
    from runtime.clock import RealtimeClock
    from runtime.gpio_backend import GPIOBackend
    from runtime.router import EventRouter

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    playback_cfg = RUNTIME_CONFIG["playback"]
    events_path = PROJECT_ROOT / RUNTIME_CONFIG["files"]["events_file"]
    events = list(np.load(events_path, allow_pickle=True))
    print(f"Loaded raw events: {len(events)}")
    events = prepare_events(events, playback_cfg)
    print(f"Events after filtering: {len(events)}")

    print("\nFIRST 10 EVENTS:\n")
    for event in events[:10]:
        print(event["playback_time"], event["timestamp"], event["target"])
    print(f"\nPlayback window: {events[0]['timestamp']} -> {events[-1]['timestamp']}")
    print(f"Loaded {len(events)} events")

    solenoid_backend = GPIOBackend(get_solenoid_pin_map())
    register_shutdown_hook(solenoid_backend.shutdown)
    try:
        play(
            events,
            EventRouter({"solenoid": solenoid_backend}),
            RealtimeClock(),
            playback_cfg["sleep_resolution"],
        )
    finally:
        shutdown()


if __name__ == "__main__":
    main()
