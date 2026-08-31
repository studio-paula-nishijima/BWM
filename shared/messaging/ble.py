"""BLE central transport for BWM semantic events.

The transport only reconstructs and parses the BWM envelope.  Application
interpretation, including deduplication, remains with the receiving ingress.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import threading
from typing import Callable

from .events import EventValidationError, SemanticEvent

LOG = logging.getLogger(__name__)

DEFAULT_SERVICE_UUID = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001"
DEFAULT_ACTIVATION_UUID = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1002"
DEFAULT_DEVICE_NAME = "BWM Vision"
START, END = 0x01, 0x02


@dataclass(frozen=True)
class BLESettings:
    enabled: bool = False
    service_uuid: str = DEFAULT_SERVICE_UUID
    characteristic_uuid: str = DEFAULT_ACTIVATION_UUID
    advertised_name: str = DEFAULT_DEVICE_NAME
    scan_timeout_seconds: float = 8.0
    reconnect_seconds: float = 5.0
    max_message_bytes: int = 4096

    def __post_init__(self):
        if not self.service_uuid or not self.characteristic_uuid:
            raise ValueError("BLE service_uuid and characteristic_uuid are required")
        if self.scan_timeout_seconds <= 0 or self.reconnect_seconds <= 0 or self.max_message_bytes < 64:
            raise ValueError("BLE timeouts must be positive and max_message_bytes must be at least 64")


@dataclass
class BLEFragmentReassembler:
    """Bounded, reset-on-error implementation of the ESP notification contract."""
    max_message_bytes: int = 4096
    _chunks: list[bytes] = field(default_factory=list, init=False)
    _next_sequence: int = field(default=0, init=False)
    _size: int = field(default=0, init=False)

    def reset(self) -> None:
        self._chunks.clear(); self._next_sequence = self._size = 0

    def feed(self, frame: bytes) -> bytes | None:
        if len(frame) < 4:
            self.reset(); raise ValueError("frame shorter than 3-byte header plus payload")
        flags, sequence, payload = frame[0], int.from_bytes(frame[1:3], "little"), frame[3:]
        if flags & ~(START | END):
            self.reset(); raise ValueError("unsupported frame flags")
        if flags & START:
            if sequence != 0:
                self.reset(); raise ValueError("start frame sequence is not zero")
            self.reset()
        elif not self._chunks:
            self.reset(); raise ValueError("frame arrived before start")
        if sequence != self._next_sequence:
            expected = self._next_sequence; self.reset()
            raise ValueError(f"sequence gap: expected {expected}, got {sequence}")
        if self._size + len(payload) > self.max_message_bytes:
            self.reset(); raise ValueError(f"message exceeds {self.max_message_bytes} bytes")
        self._chunks.append(payload); self._size += len(payload); self._next_sequence += 1
        if flags & END:
            complete = b"".join(self._chunks); self.reset(); return complete
        return None


class SemanticBLETransport:
    """Failure-isolated, process-wide Bleak client with automatic resubscription."""
    def __init__(self, settings: BLESettings, on_event: Callable[[SemanticEvent], object], *,
                 scanner=None, client_factory=None):
        self.settings, self._on_event = settings, on_event
        self._scanner, self._client_factory = scanner, client_factory
        self._stop = threading.Event(); self._thread = self._loop = self._stop_async = None
        self._reassembler = BLEFragmentReassembler(settings.max_message_bytes)

    def start(self) -> bool:
        if not self.settings.enabled:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="bwm-ble", daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        if self._loop and self._stop_async:
            self._loop.call_soon_threadsafe(self._stop_async.set)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.settings.scan_timeout_seconds + 2)

    def notification(self, _sender, data: bytearray) -> None:
        try:
            complete = self._reassembler.feed(bytes(data))
            if complete is None:
                return
            event = SemanticEvent.from_json(complete)
            LOG.info("[BLE] activation event received: %s", event.id)
            self._on_event(event)
        except (ValueError, EventValidationError) as exc:
            LOG.warning("[BLE] dropped malformed activation frame: %s", exc)
        except Exception:
            LOG.exception("[BLE] semantic event handler failed")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            LOG.warning("[BLE] unavailable; continuing without BLE: %s", exc)

    async def _run(self) -> None:
        self._loop, self._stop_async = asyncio.get_running_loop(), asyncio.Event()
        if self._scanner is None or self._client_factory is None:
            from bleak import BleakClient, BleakScanner
            self._scanner, self._client_factory = BleakScanner, BleakClient
        while not self._stop.is_set():
            try:
                LOG.info("[BLE] scanning for %s", self.settings.advertised_name)
                device = await self._scanner.find_device_by_filter(self._matches_device,
                                                                    timeout=self.settings.scan_timeout_seconds)
                if device is not None:
                    await self._connect_and_subscribe(device)
            except Exception as exc:
                if not self._stop.is_set():
                    LOG.warning("[BLE] transport degraded; reconnecting: %s", exc)
            if not self._stop.is_set():
                await self._wait_or_stop(self.settings.reconnect_seconds)

    def _matches_device(self, device, advertisement) -> bool:
        uuids = {value.lower() for value in (getattr(advertisement, "service_uuids", None) or [])}
        return self.settings.service_uuid.lower() in uuids or getattr(device, "name", None) == self.settings.advertised_name

    async def _connect_and_subscribe(self, device) -> None:
        client = self._client_factory(device)
        try:
            await client.connect()
            LOG.info("[BLE] connected")
            await client.start_notify(self.settings.characteristic_uuid, self.notification)
            LOG.info("[BLE] subscribed to activation notifications")
            while getattr(client, "is_connected", False) and not self._stop.is_set():
                await self._wait_or_stop(0.5)
        finally:
            if getattr(client, "is_connected", False):
                await client.disconnect()
            self._reassembler.reset()
            if not self._stop.is_set():
                LOG.info("[BLE] disconnected; reconnecting")

    async def _wait_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_async.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
