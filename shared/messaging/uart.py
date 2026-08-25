"""Bidirectional newline-delimited JSON UART transport for BWM semantic events."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable

from .events import EventValidationError, SemanticEvent

LOG = logging.getLogger(__name__)


class UARTConfigurationError(RuntimeError):
    """The requested BWM UART cannot safely be opened."""


@dataclass(frozen=True)
class UARTSettings:
    enabled: bool = False
    device_mode: str = "uart0"
    device: str | None = None
    baud_rate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout_seconds: float = 0.25
    max_frame_bytes: int = 8192

    def __post_init__(self):
        if self.device_mode not in {"uart0", "explicit"}:
            raise ValueError("UART device_mode must be 'uart0' or 'explicit'")
        if self.device_mode == "explicit" and not self.device:
            raise ValueError("UART explicit device_mode requires device")
        if self.device == "/dev/serial0":
            raise ValueError("/dev/serial0 must not be used for BWM UART")
        if self.baud_rate <= 0 or self.max_frame_bytes < 64 or self.timeout_seconds <= 0:
            raise ValueError("UART baud_rate, timeout_seconds and max_frame_bytes must be positive")


class NewlineEventDecoder:
    """Bounded incremental decoder that always recovers at the next newline."""
    def __init__(self, max_frame_bytes: int):
        self.max_frame_bytes, self._buffer, self._discarding = max_frame_bytes, bytearray(), False

    def feed(self, data: bytes) -> list[SemanticEvent]:
        events = []
        for byte in data:
            if self._discarding:
                if byte == 10:
                    self._discarding = False
                continue
            if byte == 10:
                raw, self._buffer = bytes(self._buffer).rstrip(b"\r"), bytearray()
                if not raw:
                    continue
                try:
                    events.append(SemanticEvent.from_json(raw))
                except EventValidationError as exc:
                    LOG.warning("Rejected malformed UART frame: %s", exc)
                continue
            self._buffer.append(byte)
            if len(self._buffer) > self.max_frame_bytes:
                LOG.warning("Rejected oversized UART frame (> %d bytes)", self.max_frame_bytes)
                self._buffer.clear()
                self._discarding = True
        return events


def encode_frame(event: SemanticEvent, max_frame_bytes: int = 8192) -> bytes:
    frame = event.to_json().encode("utf-8") + b"\n"
    if len(frame) > max_frame_bytes:
        raise ValueError(f"UART event frame exceeds {max_frame_bytes} bytes")
    return frame


def resolve_uart0_device(dt_root: Path = Path("/sys/firmware/devicetree/base"), tty_root: Path = Path("/sys/class/tty"), *, path_resolver=None) -> str:
    """Resolve the DT ``uart0`` alias to its concrete /dev/tty* node."""
    try:
        target_text = (dt_root / "aliases" / "uart0").read_bytes().rstrip(b"\0").decode("ascii")
    except OSError as exc:
        raise UARTConfigurationError("Cannot resolve device-tree alias uart0") from exc
    target = dt_root / target_text.lstrip("/")
    path_resolver = path_resolver or (lambda path: path.resolve(strict=True))
    try:
        expected = path_resolver(target)
    except OSError as exc:
        raise UARTConfigurationError(f"uart0 alias target is unavailable: {target_text}") from exc
    matches = []
    for tty in tty_root.glob("tty*"):
        try:
            if path_resolver(tty / "device" / "of_node") == expected:
                matches.append(f"/dev/{tty.name}")
        except OSError:
            continue
    if len(matches) != 1:
        detail = "none" if not matches else ", ".join(sorted(matches))
        raise UARTConfigurationError(f"uart0 must resolve to exactly one /dev/tty* device; found {detail}")
    return matches[0]


def _console_devices(cmdline: str) -> set[str]:
    return {match.group(1) for match in re.finditer(r"(?:^|\s)console=([^,\s]+)", cmdline)}


def assert_uart_unclaimed(device: str, *, cmdline_path: Path = Path("/proc/cmdline"), systemctl=subprocess.run) -> None:
    """Reject kernel-console and serial-getty ownership of the actual device."""
    tty_name = os.path.basename(os.path.realpath(device))
    try:
        if tty_name in _console_devices(cmdline_path.read_text(encoding="utf-8")):
            raise UARTConfigurationError(f"Refusing {device}: kernel serial console claims {tty_name}")
    except OSError as exc:
        raise UARTConfigurationError("Cannot inspect /proc/cmdline for UART console ownership") from exc
    unit = f"serial-getty@{tty_name}.service"
    try:
        for state in ("is-active", "is-enabled"):
            if systemctl(["systemctl", state, "--quiet", unit], check=False).returncode == 0:
                raise UARTConfigurationError(f"Refusing {device}: {unit} is {state}")
    except FileNotFoundError:
        LOG.warning("systemctl unavailable; cannot check %s", unit)


class SemanticUARTTransport:
    """One persistent, failure-isolated UART reader thread and synchronized writer."""
    def __init__(self, settings: UARTSettings, on_event: Callable[[SemanticEvent], None], serial_factory=None):
        self.settings, self._on_event, self._serial_factory = settings, on_event, serial_factory
        self._serial = None
        self._thread = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self.device: str | None = None

    def start(self) -> bool:
        if not self.settings.enabled:
            return False
        try:
            self.device = self.settings.device if self.settings.device_mode == "explicit" else resolve_uart0_device()
            if self.device == "/dev/serial0":
                raise UARTConfigurationError("/dev/serial0 must not be used for BWM UART")
            assert_uart_unclaimed(self.device)
            factory = self._serial_factory
            if factory is None:
                import serial
                factory = serial.Serial
            self._serial = factory(self.device, baudrate=self.settings.baud_rate, bytesize=self.settings.bytesize,
                                   parity=self.settings.parity, stopbits=self.settings.stopbits,
                                   timeout=self.settings.timeout_seconds)
            self._thread = threading.Thread(target=self._read_loop, name="bwm-uart", daemon=True)
            self._thread.start()
            LOG.info("UART open on %s at %d baud", self.device, self.settings.baud_rate)
            return True
        except Exception as exc:
            LOG.warning("UART startup unavailable; local operation continues: %s", exc)
            self.close()
            return False

    def _read_loop(self) -> None:
        decoder = NewlineEventDecoder(self.settings.max_frame_bytes)
        while not self._stop.is_set() and self._serial is not None:
            try:
                chunk = self._serial.read(256)
                if chunk:
                    for event in decoder.feed(chunk):
                        try:
                            self._on_event(event)
                        except Exception:
                            LOG.exception("UART semantic event handler failed")
            except Exception as exc:
                if not self._stop.is_set():
                    LOG.warning("UART read failed; transport is degraded: %s", exc)
                return

    def send(self, event: SemanticEvent) -> bool:
        if self._serial is None:
            LOG.warning("UART send skipped while unavailable")
            return False
        try:
            with self._write_lock:
                self._serial.write(encode_frame(event, self.settings.max_frame_bytes))
                self._serial.flush()
            return True
        except Exception as exc:
            LOG.warning("UART write failed; transport is degraded: %s", exc)
            return False

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.settings.timeout_seconds + 1)
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None
