#!/usr/bin/env python3
"""Bidirectional UART smoke test for two Raspberry Pis.

Wire the boards as follows (3.3 V TTL only):
    Pi A TX -> Pi B RX
    Pi A RX -> Pi B TX
    Pi A GND -> Pi B GND

Run this script on both boards. Each board sends a heartbeat every second and
prints the heartbeats it receives from the other board.

Example:
    python3 uart_connection_test.py --name pi-a
    python3 uart_connection_test.py --name pi-b

The GPIO UART is normally available as /dev/serial0 after enabling the serial
hardware and disabling the serial login shell with raspi-config.
"""

from __future__ import annotations

import argparse
import sys
import time

import serial


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/serial0", help="UART device path")
    parser.add_argument("--baud", type=int, default=115200, help="baud rate")
    parser.add_argument("--name", required=True, help="this Pi's label, e.g. pi-a")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="seconds between heartbeats"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2

    try:
        uart = serial.Serial(args.port, args.baud, timeout=0.1)
    except serial.SerialException as error:
        print(f"Could not open {args.port}: {error}", file=sys.stderr)
        return 1

    print(f"Opened {args.port} at {args.baud} baud as {args.name}. Press Ctrl+C to stop.")
    sequence = 0
    next_heartbeat = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if now >= next_heartbeat:
                sequence += 1
                message = f"PING {args.name} {sequence}\n"
                uart.write(message.encode("ascii"))
                uart.flush()
                print(f"Sent: {message.rstrip()}")
                next_heartbeat = now + args.interval

            received = uart.readline()
            if received:
                print(f"Received: {received.decode('utf-8', errors='replace').rstrip()}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        uart.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
