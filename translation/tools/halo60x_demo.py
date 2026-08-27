"""Preview or run the Halo 60x demonstration over an Open-DMX USB cable."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lighting.halo60x_demo import build_halo60x_demo, state_to_dmx_channels


def send_open_dmx_frame(serial_port, channels: tuple[int, int, int], start_address: int) -> None:
    """Send one frame using the Enttec Open DMX serial convention."""
    if not 1 <= start_address <= 510:
        raise ValueError("start_address must leave room for the three Halo channels")
    frame = bytearray(512)
    frame[start_address - 1:start_address + 2] = bytes(channels)
    serial_port.send_break(duration=0.0001)
    serial_port.write(bytes([0]) + frame)


def run_live(port: str, start_address: int, interval: float) -> None:
    """Run the demonstration against an FTDI/Enttec-Open-DMX-compatible cable."""
    if interval <= 0:
        raise ValueError("interval must be positive")
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required for --live; use translation_venv") from exc

    with serial.Serial(port=port, baudrate=250000, bytesize=8, parity=serial.PARITY_NONE,
                       stopbits=2, timeout=1) as serial_port:
        try:
            for cue in build_halo60x_demo():
                print(f"[Halo 60x] {cue.label}", flush=True)
                for state in cue.frames(interval):
                    send_open_dmx_frame(serial_port, state_to_dmx_channels(state), start_address)
                    time.sleep(interval)
        finally:
            send_open_dmx_frame(serial_port, (0, 0, 0), start_address)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=0.1, help="frame interval in seconds")
    parser.add_argument("--port", help="Linux serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--address", type=int, default=1, help="Halo DMX start address (default: 1)")
    parser.add_argument("--live", action="store_true", help="send frames to the connected Halo 60x")
    args = parser.parse_args()
    if args.live:
        if not args.port:
            parser.error("--live requires --port, for example --port /dev/ttyUSB0")
        run_live(args.port, args.address, args.interval)
        return
    for cue in build_halo60x_demo():
        for state in cue.frames(args.interval):
            print(json.dumps({"cue": cue.label, **state.__dict__}, sort_keys=True))


if __name__ == "__main__":
    main()
