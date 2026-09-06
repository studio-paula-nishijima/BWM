"""Preview or send Halo 60x cues through OLA/olad (never direct serial)."""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lighting.halo60x_demo import Halo60xCue, Halo60xState, build_halo60x_demo, state_to_dmx_channels
from lighting.ola_client import OLAUniverseClient

def frame_for(state, address):
    frame = bytearray(address + 2); frame[address - 1:address + 2] = bytes(state_to_dmx_channels(state)); return frame

def play_cue(client, cue, address, interval, *, clock=time.monotonic, sleep=time.sleep):
    started, deadline, next_frame = clock(), None, None
    deadline, next_frame = started + cue.fade_seconds + cue.hold_seconds, started
    while clock() < deadline:
        client.send(frame_for(cue.state_at(clock() - started), address))
        next_frame += interval; delay = next_frame - clock()
        if delay > 0: sleep(delay)
        else: next_frame = clock()
    client.send(frame_for(cue.end, address))

def run_live(universe, address, interval, *, fade_seconds, hold_seconds, check_fade_seconds, blackout_hold_seconds):
    client = OLAUniverseClient(universe)
    try:
        for cue in build_halo60x_demo(fade_seconds=fade_seconds, hold_seconds=hold_seconds, check_fade_seconds=check_fade_seconds, blackout_hold_seconds=blackout_hold_seconds):
            print(f"[Halo 60x / OLA universe {universe}] {cue.label}", flush=True); play_cue(client, cue, address, interval)
    finally:
        client.send(frame_for(Halo60xState(0, 2700), address)); client.close()

def run_static(universe, address, interval, *, brightness, cct, duration):
    client, state = OLAUniverseClient(universe), Halo60xState(brightness, cct)
    try:
        cue = Halo60xCue("static", state, state, 0, duration or 1.0)
        if duration is None:
            print(f"[Halo 60x / OLA universe {universe}] static until Ctrl+C", flush=True)
            while True: play_cue(client, cue, address, interval)
        else: play_cue(client, cue, address, interval)
    except KeyboardInterrupt: pass
    finally:
        client.send(frame_for(Halo60xState(0, 2700), address)); client.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=.1); parser.add_argument("--universe", type=int, default=1)
    parser.add_argument("--address", type=int, default=1); parser.add_argument("--live", action="store_true")
    parser.add_argument("--static", action="store_true"); parser.add_argument("--brightness", type=float); parser.add_argument("--cct", type=float); parser.add_argument("--duration", type=float)
    parser.add_argument("--fade", type=float, default=4); parser.add_argument("--hold", type=float, default=5); parser.add_argument("--check-fade", type=float, default=12); parser.add_argument("--blackout-hold", type=float, default=3)
    args = parser.parse_args()
    if args.live:
        if args.static:
            if args.brightness is None or args.cct is None: parser.error("--static requires --brightness and --cct")
            run_static(args.universe, args.address, args.interval, brightness=args.brightness, cct=args.cct, duration=args.duration)
        else: run_live(args.universe, args.address, args.interval, fade_seconds=args.fade, hold_seconds=args.hold, check_fade_seconds=args.check_fade, blackout_hold_seconds=args.blackout_hold)
        return
    for cue in build_halo60x_demo():
        for state in cue.frames(args.interval): print(json.dumps({"cue": cue.label, **state.__dict__}, sort_keys=True))

if __name__ == "__main__": main()
