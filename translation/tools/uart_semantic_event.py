#!/usr/bin/env python3
"""Send or log real shared BWM events over the configured UART."""
import argparse, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from shared.messaging.config import load_uart_settings
from shared.messaging.events import installation_activation, voice_state
from shared.messaging.uart import SemanticUARTTransport
parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=("send", "receive")); parser.add_argument("type", nargs="?", choices=("voice.state", "installation.activation")); parser.add_argument("state", nargs="?"); parser.add_argument("--origin", default="uart_tool")
args = parser.parse_args()
if args.mode == "send" and (not args.type or not args.state): parser.error("send requires type and state")
transport = SemanticUARTTransport(load_uart_settings(ROOT), lambda event: print(event.to_json()))
if not transport.start(): raise SystemExit("UART unavailable; inspect uart0/console/getty")
try:
    if args.mode == "send":
        event = voice_state(args.origin, args.state) if args.type == "voice.state" else installation_activation(args.origin, args.state)
        if not transport.send(event): raise SystemExit("UART send failed")
    else:
        while True: time.sleep(1)
finally: transport.close()
