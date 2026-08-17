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
    python3 uart_connection_test.py --name pi-a
    python3 uart_connection_test.py --name pi-b

GPIO14 (TX) and GPIO15 (RX) are assigned to the device-tree ``uart0`` alias.
The script resolves that alias to its actual /dev/tty* device at runtime, then
opens that device directly.  Do not use /dev/serial0: it is a separate,
configuration-dependent alias and can point at the debug UART.

Before running the test on each Pi, run ``--inspect`` and confirm that GPIO14
and GPIO15 are assigned to uart0 and that the resolved transport device is not
claimed by a kernel serial console or serial getty. Disable the login shell over
serial in raspi-config if required, then reboot.
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


GPIO_UART_ALIAS = "uart0"
DEVICE_TREE_ROOT = Path("/sys/firmware/devicetree/base")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        help="override the GPIO14/15 UART device resolved from the uart0 alias",
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


def device_tree_alias_target(alias: str) -> Path | None:
    """Return the device-tree node targeted by *alias*, when available."""
    try:
        relative_path = (DEVICE_TREE_ROOT / "aliases" / alias).read_bytes()
    except OSError:
        return None
    return DEVICE_TREE_ROOT / relative_path.rstrip(b"\0").decode("ascii").lstrip("/")


def tty_for_device_tree_node(node: Path) -> str | None:
    """Find the /dev/tty* device backed by a device-tree node."""
    try:
        expected = node.resolve()
    except OSError:
        return None

    for tty in sorted(Path("/sys/class/tty").glob("tty*")):
        of_node = tty / "device" / "of_node"
        try:
            if of_node.resolve() == expected:
                return f"/dev/{tty.name}"
        except OSError:
            continue
    return None


def gpio_uart_port() -> str | None:
    """Resolve the UART selected by the GPIO14/15 uart0 pin function."""
    target = device_tree_alias_target(GPIO_UART_ALIAS)
    return tty_for_device_tree_node(target) if target else None


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


def inspect(port: str | None) -> int:
    """Show the information needed to verify the GPIO14/15 UART mapping."""
    uart0_node = device_tree_alias_target(GPIO_UART_ALIAS)
    print(f"GPIO14/15 pin-function alias: {GPIO_UART_ALIAS}")
    print(f"{GPIO_UART_ALIAS} device-tree node: {uart0_node or 'unavailable'}")
    print(f"Resolved GPIO14/15 transport device: {port or 'unavailable'}")
    if port:
        tty_name = os.path.basename(os.path.realpath(port))
        run_inspection(["readlink", "-f", port])
        run_inspection(
            ["readlink", "-f", f"/sys/class/tty/{tty_name}/device/of_node"]
        )
    run_inspection(["readlink", "-f", "/dev/serial0"])
    run_inspection(["pinctrl", "get", "14"])
    run_inspection(["pinctrl", "get", "15"])
    run_inspection(["sh", "-c", "cat /proc/cmdline"])
    run_inspection(["sh", "-c", "ls -l /dev/ttyAMA* /dev/ttyS* 2>/dev/null"])
    if port:
        run_inspection(
            ["systemctl", "is-active", f"serial-getty@{os.path.basename(port)}.service"]
        )
    return 0


def main() -> int:
    args = parse_args()
    port = args.port or gpio_uart_port()
    if args.inspect:
        return inspect(port)
    if not args.name:
        print("--name is required unless --inspect is used", file=sys.stderr)
        return 2
    if not port:
        print(
            "Could not resolve the GPIO14/15 uart0 alias to a /dev/tty* device. "
            "Run with --inspect, correct the pinmux/UART configuration, or pass "
            "the verified device explicitly with --port.",
            file=sys.stderr,
        )
        return 2
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2

    console_tty = serial_console_claims(port)
    getty_tty = serial_getty_claims(port)
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
            f"Refusing to use {port}: {'; '.join(claims)}. "
            f"Disable the serial login shell and reboot.{console_fix}",
            file=sys.stderr,
        )
        return 2

    try:
        uart = serial.Serial(port, args.baud, timeout=0.1)
    except serial.SerialException as error:
        print(f"Could not open {port}: {error}", file=sys.stderr)
        return 1

    print(f"Opened {port} at {args.baud} baud as {args.name}. Press Ctrl+C to stop.")
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
