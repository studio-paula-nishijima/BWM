#!/usr/bin/env python3
"""Diagnostic-only BWM Vision BLE activation receiver (no production imports)."""
import argparse
import asyncio
import json
from dataclasses import dataclass, field

SERVICE_UUID = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001"
ACTIVATION_UUID = "7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1002"
DEVICE_NAME = "BWM Vision"
START, END = 0x01, 0x02


@dataclass
class Reassembler:
    chunks: list[bytes] = field(default_factory=list)
    next_sequence: int = 0

    def feed(self, frame: bytes) -> bytes | None:
        if len(frame) < 4:
            raise ValueError("frame shorter than 3-byte header plus payload")
        flags, sequence = frame[0], int.from_bytes(frame[1:3], "little")
        if flags & START:
            if sequence != 0:
                raise ValueError("start frame sequence is not zero")
            self.chunks, self.next_sequence = [], 0
        elif not self.chunks:
            raise ValueError("frame arrived before start")
        if sequence != self.next_sequence:
            self.chunks = []
            raise ValueError(f"sequence gap: expected {self.next_sequence}, got {sequence}")
        self.chunks.append(frame[3:])
        self.next_sequence += 1
        if flags & END:
            payload = b"".join(self.chunks)
            self.chunks, self.next_sequence = [], 0
            return payload
        return None


def validate(payload: bytes) -> dict:
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid UTF-8 JSON: {error}") from error
    required = {"version": int, "id": str, "type": str, "origin": str, "timestamp": str, "payload": dict, "diagnostics": dict}
    for key, kind in required.items():
        if not isinstance(event.get(key), kind):
            raise ValueError(f"missing or invalid {key}")
    if event["type"] != "installation.activation" or event["origin"] != "person_detector":
        raise ValueError("not a BWM person-detector activation")
    if event["payload"].get("state") != "active":
        raise ValueError("payload state is not active")
    if not isinstance(event["diagnostics"].get("trigger_source"), str):
        raise ValueError("missing diagnostics.trigger_source")
    return event


async def run(args: argparse.Namespace) -> None:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as error:
        raise SystemExit("Install the diagnostic dependency on the Pi: python3 -m pip install bleak") from error
    while True:
        print(f"Scanning for {DEVICE_NAME!r} / {SERVICE_UUID}…")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name == args.name or SERVICE_UUID.lower() in {u.lower() for u in ad.service_uuids}
        )
        if device is None:
            print("No BWM Vision device found; retrying in 5 seconds.")
            await asyncio.sleep(5)
            continue
        reassembler = Reassembler()

        def notification(_, data: bytearray) -> None:
            try:
                complete = reassembler.feed(bytes(data))
                if complete is None:
                    return
                event = validate(complete)
                print("activation", event["id"], event["type"], event["origin"],
                      event["payload"]["state"], event["diagnostics"]["trigger_source"])
                if args.verbose:
                    print(complete.decode("utf-8"))
            except ValueError as error:
                print(f"malformed/incomplete activation: {error}")

        try:
            async with BleakClient(device) as client:
                print(f"Connected: {device.address}; subscribing to activation notifications.")
                await client.start_notify(ACTIVATION_UUID, notification)
                while client.is_connected:
                    await asyncio.sleep(1)
        except Exception as error:  # BlueZ errors are environment-specific.
            print(f"BLE connection ended: {error}")
        print("Disconnected; retrying in 5 seconds.")
        await asyncio.sleep(5)


def self_test() -> None:
    body = b'{"version":1,"id":"test","type":"installation.activation","origin":"person_detector","timestamp":"1970-01-01T00:00:00Z","payload":{"state":"active"},"diagnostics":{"trigger_source":"manual_test"}}'
    r = Reassembler()
    assert r.feed(bytes([START, 0, 0]) + body[:24]) is None
    result = r.feed(bytes([END, 1, 0]) + body[24:])
    assert result == body and validate(result)["id"] == "test"
    print("BLE frame/parser self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=DEVICE_NAME, help="advertised ESP name (default: BWM Vision)")
    parser.add_argument("--verbose", action="store_true", help="print raw JSON payloads")
    parser.add_argument("--self-test", action="store_true", help="validate framing/parser without BLE hardware")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
