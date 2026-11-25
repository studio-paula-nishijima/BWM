#!/usr/bin/env python3
"""Briefly sweep the BWM servo around its centre, then shut it down safely.

Run from the ``translation`` directory on the Raspberry Pi:

    python3 test/servo_centre_check.py

Override the 1500 us centre only when the servo has been calibrated differently:

    python3 test/servo_centre_check.py --centre-pulse 1475
"""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys
import time


TRANSLATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))
sys.path.insert(0, str(TRANSLATION_ROOT))

from configs.servos import (
    CHANNEL,
    DEFAULT_SPEED,
    FREQUENCY,
    MAX_PULSE,
    MIN_PULSE,
)
from servo.controller import ServoController
from servo.sweeps import constant_speed


SWEEP_OFFSET_US = 100
POSITION_HOLD_SECONDS = 0.75
DEFAULT_CENTRE_PULSE_US = 1500


def _stop_requested(signum: int, _frame: object) -> None:
    """Turn SIGTERM into normal cleanup through the ``finally`` block."""
    raise KeyboardInterrupt(f"received signal {signum}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--centre-pulse",
        type=int,
        default=DEFAULT_CENTRE_PULSE_US,
        help=(
            f"centre pulse in microseconds (default: {DEFAULT_CENTRE_PULSE_US})"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    centre_pulse = args.centre_pulse
    if not MIN_PULSE <= centre_pulse <= MAX_PULSE:
        print(
            f"Centre pulse must be within {MIN_PULSE}-{MAX_PULSE} us.",
            file=sys.stderr,
        )
        return 2

    low_pulse = max(MIN_PULSE, centre_pulse - SWEEP_OFFSET_US)
    high_pulse = min(MAX_PULSE, centre_pulse + SWEEP_OFFSET_US)
    servo = None

    signal.signal(signal.SIGTERM, _stop_requested)

    print("BWM servo pre-integration check")
    print(f"Configured range: {MIN_PULSE}-{MAX_PULSE} us")
    print(f"Using centre pulse: {centre_pulse} us")

    try:
        print(f"Initialising channel {CHANNEL} at {FREQUENCY} Hz and centring servo...")
        servo = ServoController(CHANNEL, FREQUENCY, centre_pulse)

        print(f"Sweeping slightly below centre to {low_pulse} us...")
        constant_speed(
            servo.set_pulse,
            centre_pulse,
            low_pulse,
            DEFAULT_SPEED,
        )
        time.sleep(POSITION_HOLD_SECONDS)

        print(f"Sweeping through centre to {high_pulse} us...")
        constant_speed(
            servo.set_pulse,
            low_pulse,
            high_pulse,
            DEFAULT_SPEED,
        )
        time.sleep(POSITION_HOLD_SECONDS)

        print(f"Returning servo to centre at {centre_pulse} us...")
        constant_speed(
            servo.set_pulse,
            high_pulse,
            centre_pulse,
            DEFAULT_SPEED,
        )
        time.sleep(POSITION_HOLD_SECONDS)
        print("Centre reached. Servo movement check complete.")
        return 0
    except KeyboardInterrupt:
        print("\nStop requested; centring and shutting down safely...")
        return 130
    except Exception as error:
        print(f"Servo check failed: {error}", file=sys.stderr)
        return 1
    finally:
        if servo is not None:
            print("Disabling servo output and deinitialising the controller...")
            servo.shutdown()
        print("Servo controller shutdown complete.")


if __name__ == "__main__":
    raise SystemExit(main())
