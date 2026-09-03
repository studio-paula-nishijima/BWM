import signal
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

TRANSLATION_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = TRANSLATION_ROOT.parent
sys.path.append(str(TRANSLATION_ROOT / "src"))
sys.path.append(str(REPOSITORY_ROOT))

from configs.runtime_config import RUNTIME_CONFIG
from events.filtering import filter_events_by_date
from events.playback_selection import rebase_playback_time, select_random_segment

shutdown_hooks = []
_shutdown_in_progress = False


def register_shutdown_hook(fn):
    shutdown_hooks.append(fn)


def shutdown():
    global _shutdown_in_progress
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True
    print("\n[SHUTDOWN] Cleaning up hardware...")
    for fn in shutdown_hooks:
        try:
            fn()
        except Exception as exc:
            print(f"[SHUTDOWN ERROR] {exc}")
    print("[SHUTDOWN] Complete")


def signal_handler(sig, frame):
    print(f"\n[SIGNAL] Received {sig}, shutting down...")
    shutdown()
    sys.exit(0)


def prepare_events(events, playback_cfg):
    # The loaded .npy score is session source data.  Selection/rebasing below
    # intentionally works on private copies only.
    events = deepcopy(list(events))
    events = filter_events_by_date(events, playback_cfg["start_date"], playback_cfg["end_date"])
    if not events:
        raise RuntimeError("No events remain after playback filtering")
    t0 = events[0]["playback_time"]
    for event in events:
        event["playback_time"] -= t0
    events = sorted(events, key=lambda event: event["playback_time"])
    if playback_cfg["random_segment"]:
        events = select_random_segment(events, playback_cfg["segment_minutes"] * 60)
        events = rebase_playback_time(events)
    return events


def log_dispatched_event(event):
    print("TARGET:", event["playback_time"])
    print(f"{pd.Timestamp(event['timestamp']).strftime('%Y-%m-%d %H:%M:%S')} | "
          f"{event['target']} | {event['metadata']['frequency']:.2f} Hz")


def run_engine(activation_controller, engine, sleep_resolution):
    activation_controller.start()
    while not engine.is_terminal:
        activation_controller.wait_until_active()
        engine.step()
        if engine.is_running:
            activation_controller.wait_for_change(sleep_resolution)


def run_session_runtime(runtime, sleep_resolution):
    """Persistent low-resource loop: idle waits, active sessions step efficiently."""
    while True:
        runtime.wait_until_active()
        runtime.step()
        if runtime.is_active:
            runtime.wait_for_change(sleep_resolution)


def main():
    from configs.runtime_config import (PROJECT_ROOT, get_backup_button_pin, get_solenoid_pin_map,
                                        load_voice_reactions_config)
    from runtime.clock import RealtimeClock
    from runtime.gpio_backend import GPIOBackend
    from runtime.local_activation_input import LocalActivationInput
    from runtime.mqtt_adapter import TranslationMQTTAdapter
    from runtime.activation_publication import TranslationActivationPublisher
    from runtime.router import EventRouter
    from runtime.session import PlaybackSessionRuntime
    from lighting.halo_runtime import HaloLightingController

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    playback_cfg = RUNTIME_CONFIG["playback"]
    source_events = list(np.load(PROJECT_ROOT / RUNTIME_CONFIG["files"]["events_file"], allow_pickle=True))
    print(f"Loaded raw events: {len(source_events)}")

    def fresh_session_events():
        events = prepare_events(source_events, playback_cfg)
        print(f"Session events after filtering: {len(events)}")
        return events
    solenoid_pin_map = get_solenoid_pin_map()
    solenoid_backend = GPIOBackend(solenoid_pin_map)
    register_shutdown_hook(solenoid_backend.shutdown)
    try:
        voice_reactions = load_voice_reactions_config()
        reaction_strategies = {**RUNTIME_CONFIG.get("modulation", {}).get("strategies", {}),
                               **voice_reactions.get("strategies", {})}
        reaction_policies = {**RUNTIME_CONFIG.get("reaction_policy", {}),
                             "voice_default": voice_reactions.get("policy", {}),
                             **voice_reactions.get("policies", {})}
        lighting = HaloLightingController(RUNTIME_CONFIG.get("lighting", {}))
        runtime = PlaybackSessionRuntime(
            fresh_session_events, RealtimeClock(), EventRouter({"solenoid": solenoid_backend}),
            playback_cfg["session_timeout_seconds"], playback_cfg.get("initially_active", True),
            event_logger=log_dispatched_event,
            safety_config=RUNTIME_CONFIG.get("runtime_safety", {}),
            reaction_policy_config={"strategies": reaction_strategies, "policies": reaction_policies},
            voice_interaction_config=RUNTIME_CONFIG.get("voice_interaction", {}),
            reaction_targets=list(solenoid_pin_map),
            lighting_controller=lighting,
        )
        activation_publisher = TranslationActivationPublisher()
        runtime.set_activation_publisher(activation_publisher)
        register_shutdown_hook(lighting.shutdown)
        local_input = LocalActivationInput(get_backup_button_pin(), runtime)
        register_shutdown_hook(local_input.close)
        # Semantic ingress exists even if a particular optional transport is
        # unavailable; UART/BLE must not depend on MQTT startup succeeding.
        from shared.messaging.topics import TopicNamespace
        try:
            from shared.messaging.config import load_mqtt_settings
            _, topic_base = load_mqtt_settings(REPOSITORY_ROOT)
        except Exception:
            topic_base = "bwm"
        topics = TopicNamespace(topic_base)
        ingress = TranslationMQTTAdapter(runtime, topics.installation_activation,
                                         topics.voice_state, topics.voice_interaction)
        # MQTT is an optional semantic input. Failure to import/connect leaves
        # this persistent GPIO17-capable runtime untouched.
        try:
            from shared.messaging.config import load_mqtt_settings
            from shared.messaging.mqtt_client import SemanticMQTTClient
            mqtt_settings, topic_base = load_mqtt_settings(REPOSITORY_ROOT)
            topics = TopicNamespace(topic_base)
            activation_topic, voice_state_topic, voice_interaction_topic = topics.installation_activation, topics.voice_state, topics.voice_interaction
            mqtt_client = SemanticMQTTClient(mqtt_settings, ingress.handle)
            mqtt_client.start([activation_topic, voice_state_topic, voice_interaction_topic])
            register_shutdown_hook(mqtt_client.close)
        except Exception as exc:
            print(f"[MQTT] Unavailable; continuing with local activation: {exc}")
        try:
            from shared.messaging.config import load_uart_settings
            from shared.messaging.uart import SemanticUARTTransport
            # UART ingress is local-only: an inbound UART activation must not
            # be echoed back to its sender.  Every other accepted state change
            # reaches the runtime's one authoritative publication seam.
            uart_client = SemanticUARTTransport(
                load_uart_settings(REPOSITORY_ROOT),
                lambda event: ingress.handle_event(event, publish_authoritative=False),
            )
            if uart_client.start():
                activation_publisher.set_uart_transport(uart_client)
                runtime.publish_current_activation()
            register_shutdown_hook(uart_client.close)
        except Exception as exc:
            print(f"[UART] Unavailable; continuing without UART: {exc}")
        try:
            from shared.messaging.ble import SemanticBLETransport
            from shared.messaging.config import load_ble_settings
            ble_client = SemanticBLETransport(load_ble_settings(REPOSITORY_ROOT), ingress.handle_event)
            if ble_client.start():
                register_shutdown_hook(ble_client.close)
        except Exception as exc:
            print(f"[BLE] Unavailable; continuing without BLE: {exc}")
        run_session_runtime(runtime, playback_cfg["sleep_resolution"])
    finally:
        shutdown()


if __name__ == "__main__":
    main()
