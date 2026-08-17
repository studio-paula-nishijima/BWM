#!/usr/bin/env python3
"""Bidirectional UART smoke test for two Raspberry Pis.

Wire the boards as follows (3.3 V TTL only):
    Pi A TX -> Pi B RX
    Pi A RX -> Pi B TX
    Pi A GND -> Pi B GND

Run this script on both boards. Each board sends a heartbeat every second and
prints the heartbeats it receives from the other board.

Example:
    python3 uart_connection_test.py --inspect
    python3 uart_connection_test.py --name pi-a --port /dev/ttyAMA10
    python3 uart_connection_test.py --name pi-b --port /dev/ttyAMA10

The captured Pi 5 configuration for this installation maps GPIO14 (TX) and
GPIO15 (RX) to RP1 UART0, exposed as /dev/ttyAMA10.  Do not substitute
/dev/serial0, ttyAMA0, or ttyS0: those names are aliases or vary by board and
configuration.

Before running the test on each Pi, run ``--inspect`` and confirm that GPIO14
and GPIO15 are assigned to uart0.  The kernel serial console and serial getty
must not use ttyAMA10.  Disable the login shell over serial in raspi-config and
remove ``console=ttyAMA10,...`` from /boot/firmware/cmdline.txt if present,
then reboot.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import serial


GPIO14_15_UART = "/dev/ttyAMA10"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        default=GPIO14_15_UART,
        help="GPIO14/15 UART device path (default: %(default)s)",
    )
    parser.add_argument("--baud", type=int, default=115200, help="baud rate")
    parser.add_argument("--name", help="this Pi's label, e.g. pi-a")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="seconds between heartbeats"
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="show GPIO14/15 and serial-console state without opening the UART",
    )
    return parser.parse_args()


def run_inspection(command: list[str]) -> None:
    """Print a best-effort hardware/configuration diagnostic."""
    print(f"$ {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("  command unavailable")
        return
    output = (result.stdout + result.stderr).strip()
    print(f"  {output if output else f'(exit {result.returncode})'}")


def console_devices(cmdline: str) -> set[str]:
    """Return kernel-console tty basenames from a kernel command line."""
    return {
        match.group(1)
        for match in re.finditer(r"(?:^|\s)console=([^,\s]+)", cmdline)
    }


def serial_console_claims(port: str) -> str | None:
    """Explain whether the kernel console is using *port*, if it can be read."""
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8")
    except OSError:
        return None

    tty_name = os.path.basename(os.path.realpath(port))
    if tty_name in console_devices(cmdline):
        return tty_name
    return None


def serial_getty_claims(port: str) -> str | None:
    """Return the tty name when its serial login service is active or enabled."""
    tty_name = os.path.basename(os.path.realpath(port))
    unit = f"serial-getty@{tty_name}.service"
    try:
        for state in ("is-active", "is-enabled"):
            result = subprocess.run(
                ["systemctl", state, "--quiet", unit], check=False
            )
            if result.returncode == 0:
                return tty_name
    except FileNotFoundError:
        return None
    return None


def inspect(port: str) -> int:
    """Show the information needed to verify the GPIO14/15 UART mapping."""
    tty_name = os.path.basename(os.path.realpath(port))
    print(f"Configured GPIO14/15 transport device: {port}")
    run_inspection(["readlink", "-f", port])
    run_inspection(["readlink", "-f", "/dev/serial0"])
    run_inspection(["readlink", "-f", f"/sys/class/tty/{tty_name}/device/of_node"])
    run_inspection(["pinctrl", "get", "14", "15"])
    run_inspection(["sh", "-c", "cat /proc/cmdline"])
    run_inspection(["sh", "-c", "ls -l /dev/ttyAMA* /dev/ttyS* 2>/dev/null"])
    run_inspection(["systemctl", "is-active", "serial-getty@ttyAMA10.service"])
    return 0


def main() -> int:
    args = parse_args()
    if args.inspect:
        return inspect(args.port)
    if not args.name:
        print("--name is required unless --inspect is used", file=sys.stderr)
        return 2
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2

    console_tty = serial_console_claims(args.port)
    getty_tty = serial_getty_claims(args.port)
    if console_tty or getty_tty:
        claims = []
        if console_tty:
            claims.append(f"the kernel console claims {console_tty}")
        if getty_tty:
            claims.append(f"serial-getty@{getty_tty}.service is active or enabled")
        console_fix = (
            f" Remove console={console_tty},... from /boot/firmware/cmdline.txt."
            if console_tty
            else ""
        )
        print(
            f"Refusing to use {args.port}: {'; '.join(claims)}. "
            f"Disable the serial login shell and reboot.{console_fix}",
            file=sys.stderr,
        )
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
