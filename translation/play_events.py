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
from runtime.playback import PlaybackEngine


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


def log_dispatched_event(event):
    print("TARGET:", event["playback_time"])
    print(
        f"{pd.Timestamp(event['timestamp']).strftime('%Y-%m-%d %H:%M:%S')} | "
        f"{event['target']} | {event['metadata']['frequency']:.2f} Hz"
    )


def run_engine(engine, sleep_resolution):
    """Keep blocking/sleep behaviour at the command-line composition boundary."""
    engine.start()
    while engine.is_running:
        engine.step()
        if engine.is_running:
            time.sleep(sleep_resolution)


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
        engine = PlaybackEngine(
            events,
            RealtimeClock(),
            EventRouter({"solenoid": solenoid_backend}),
            event_logger=log_dispatched_event,
        )
        run_engine(
            engine,
            playback_cfg["sleep_resolution"],
        )
    finally:
        shutdown()


if __name__ == "__main__":
    main()
