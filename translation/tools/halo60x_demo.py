"""Preview or run the Halo 60x demonstration over an Open-DMX USB cable."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lighting.halo60x_demo import Halo60xCue, Halo60xState, build_halo60x_demo, state_to_dmx_channels
from lighting.open_dmx import send_open_dmx_frame


def play_cue(serial_port, cue, start_address: int, interval: float, *, clock=time.monotonic,
             sleep=time.sleep, send_frame=send_open_dmx_frame) -> None:
    """Transmit the current cue state without allowing slow I/O to extend it."""
    started = clock()
    deadline = started + cue.fade_seconds + cue.hold_seconds
    next_frame_at = started
    while True:
        now = clock()
        if now >= deadline:
            break
        send_frame(serial_port, state_to_dmx_channels(cue.state_at(now - started)), start_address)
        next_frame_at += interval
        delay = next_frame_at - clock()
        if delay > 0:
            sleep(delay)
        else:
            # A host-timed Open DMX cable cannot keep up with this requested
            # rate. Drop stale intermediate frames and use the newest state.
            next_frame_at = clock()
    send_frame(serial_port, state_to_dmx_channels(cue.end), start_address)


def run_live(port: str, start_address: int, interval: float, *, fade_seconds: float,
             hold_seconds: float, check_fade_seconds: float, blackout_hold_seconds: float) -> None:
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
            for cue in build_halo60x_demo(
                fade_seconds=fade_seconds,
                hold_seconds=hold_seconds,
                check_fade_seconds=check_fade_seconds,
                blackout_hold_seconds=blackout_hold_seconds,
            ):
                print(f"[Halo 60x] {cue.label}", flush=True)
                play_cue(serial_port, cue, start_address, interval)
        finally:
            send_open_dmx_frame(serial_port, (0, 0, 0), start_address)


def run_static(port: str, start_address: int, interval: float, *, brightness: float,
               cct: float, duration: float | None) -> None:
    """Transmit one explicit DMX state without sending blackout on exit."""
    if interval <= 0 or (duration is not None and duration <= 0):
        raise ValueError("interval and duration must be positive")
    state = Halo60xState(brightness, cct)
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required for --live; use translation_venv") from exc

    with serial.Serial(port=port, baudrate=250000, bytesize=8, parity=serial.PARITY_NONE,
                       stopbits=2, timeout=1) as serial_port:
        try:
            if duration is None:
                print(f"[Halo 60x] static {brightness:g}% {cct:g} K until Ctrl+C", flush=True)
                while True:
                    cue = Halo60xCue("static", state, state, 0, 1.0)
                    play_cue(serial_port, cue, start_address, interval)
            else:
                print(f"[Halo 60x] static {brightness:g}% {cct:g} K for {duration:g} s", flush=True)
                cue = Halo60xCue("static", state, state, 0, duration)
                play_cue(serial_port, cue, start_address, interval)
        except KeyboardInterrupt:
            print("\n[Halo 60x] static transmission stopped; no blackout sent", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=0.1, help="frame interval in seconds")
    parser.add_argument("--port", help="Linux serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--address", type=int, default=1, help="Halo DMX start address (default: 1)")
    parser.add_argument("--fade", type=float, default=4.0, metavar="SECONDS",
                        help="fade duration for matrix/setup cues (default: 4)")
    parser.add_argument("--hold", type=float, default=5.0, metavar="SECONDS",
                        help="hold duration at each look (default: 5)")
    parser.add_argument("--check-fade", type=float, default=12.0, metavar="SECONDS",
                        help="fade duration for independent-control checks (default: 12)")
    parser.add_argument("--blackout-hold", type=float, default=3.0, metavar="SECONDS",
                        help="blackout hold duration at beginning/end (default: 3)")
    parser.add_argument("--static", action="store_true",
                        help="hold one explicit intensity/CCT state instead of running the demonstration")
    parser.add_argument("--brightness", type=float, metavar="PERCENT",
                        help="static intensity from 0 to 100 (required with --static)")
    parser.add_argument("--cct", type=float, metavar="KELVIN",
                        help="static CCT from 2700 to 6500 K (required with --static)")
    parser.add_argument("--duration", type=float, metavar="SECONDS",
                        help="optional static transmission duration; default: until Ctrl+C; no blackout")
    parser.add_argument("--live", action="store_true", help="send frames to the connected Halo 60x")
    args = parser.parse_args()
    if args.live:
        if not args.port:
            parser.error("--live requires --port, for example --port /dev/ttyUSB0")
        if args.static:
            if args.brightness is None or args.cct is None:
                parser.error("--static requires --brightness and --cct")
            run_static(args.port, args.address, args.interval, brightness=args.brightness,
                       cct=args.cct, duration=args.duration)
            return
        run_live(args.port, args.address, args.interval, fade_seconds=args.fade,
                 hold_seconds=args.hold, check_fade_seconds=args.check_fade,
                 blackout_hold_seconds=args.blackout_hold)
        return
    for cue in build_halo60x_demo():
        for state in cue.frames(args.interval):
            print(json.dumps({"cue": cue.label, **state.__dict__}, sort_keys=True))


if __name__ == "__main__":
    main()
