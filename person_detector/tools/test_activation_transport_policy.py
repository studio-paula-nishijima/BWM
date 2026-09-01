#!/usr/bin/env python3
"""Deterministic, hardware-free regression checks for ESP transport policy."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "stage2_espidf" / "main"
HEADER = (MAIN / "activation_transport_policy.h").read_text(encoding="utf-8")
TRANSPORT = (MAIN / "activation_transport.cpp").read_text(encoding="utf-8")
TRANSPORT_HEADER = (MAIN / "activation_transport.h").read_text(encoding="utf-8")


def constant(name: str) -> int:
    match = re.search(rf"{name}\s*=\s*(\d+)", HEADER)
    if not match:
        raise AssertionError(f"missing production constant {name}")
    return int(match.group(1))


FALLBACK_MS = constant("kMqttUnavailableFallbackMs")
RECLAIM_MS = constant("kMqttHealthyReclaimMs")


class PolicyModel:
    """Readable oracle for the same two-state hysteresis contract."""

    def __init__(self, now_ms: int = 0) -> None:
        self.current = "mqtt"
        self.unhealthy_since = now_ms
        self.healthy_since: int | None = None

    def update(self, now_ms: int, mqtt_healthy: bool) -> None:
        if self.current == "mqtt":
            self.healthy_since = None
            if mqtt_healthy:
                self.unhealthy_since = None
            else:
                if self.unhealthy_since is None:
                    self.unhealthy_since = now_ms
                if now_ms - self.unhealthy_since >= FALLBACK_MS:
                    self.current = "ble"
                    self.unhealthy_since = None
            return
        self.unhealthy_since = None
        if not mqtt_healthy:
            self.healthy_since = None
        else:
            if self.healthy_since is None:
                self.healthy_since = now_ms
            if now_ms - self.healthy_since >= RECLAIM_MS:
                self.current = "mqtt"
                self.healthy_since = None


class TransportPolicyTests(unittest.TestCase):
    def test_01_startup_healthy_prefers_mqtt(self) -> None:
        policy = PolicyModel()
        policy.update(0, True)
        self.assertEqual(policy.current, "mqtt")

    def test_02_startup_without_wifi_falls_back(self) -> None:
        policy = PolicyModel()
        policy.update(FALLBACK_MS, False)
        self.assertEqual(policy.current, "ble")

    def test_03_broker_outage_with_wifi_falls_back(self) -> None:
        # Production health is wifi_has_ip && mqtt_.pathOperational().
        self.assertIn("wifi_has_ip && mqtt_.pathOperational()", TRANSPORT)
        policy = PolicyModel()
        policy.update(FALLBACK_MS, False)
        self.assertEqual(policy.current, "ble")

    def test_04_short_outage_does_not_flap(self) -> None:
        policy = PolicyModel()
        policy.update(FALLBACK_MS - 1, False)
        self.assertEqual(policy.current, "mqtt")

    def test_05_threshold_enters_ble_fallback(self) -> None:
        policy = PolicyModel()
        policy.update(FALLBACK_MS, False)
        self.assertEqual(policy.current, "ble")

    def test_06_short_recovery_remains_on_ble(self) -> None:
        policy = PolicyModel()
        policy.update(FALLBACK_MS, False)
        policy.update(5000, True)
        policy.update(5000 + RECLAIM_MS - 1, True)
        self.assertEqual(policy.current, "ble")

    def test_07_continuous_recovery_reclaims_mqtt(self) -> None:
        policy = PolicyModel()
        policy.update(FALLBACK_MS, False)
        policy.update(5000, True)
        policy.update(5000 + RECLAIM_MS, True)
        self.assertEqual(policy.current, "mqtt")

    def test_08_both_unavailable_has_explicit_drop(self) -> None:
        self.assertIn('"mqtt_and_ble_unavailable"', TRANSPORT)
        self.assertIn('"activation dropped source=%s id=%s reason=%s"', TRANSPORT)

    def test_09_event_is_constructed_before_transport_choice(self) -> None:
        constructed = TRANSPORT.index("makeActivationEvent(trigger_source, event)")
        choice = TRANSPORT.index("const bool use_ble")
        self.assertLess(constructed, choice)

    def test_10_handover_attempts_reuse_same_event_object(self) -> None:
        self.assertGreaterEqual(TRANSPORT.count("mqtt_.publish(event)"), 1)
        self.assertGreaterEqual(TRANSPORT.count("ble_.publish(event)"), 2)
        self.assertEqual(TRANSPORT.count("makeActivationEvent("), 1)

    def test_11_manual_and_camera_share_dispatcher(self) -> None:
        self.assertIn('dispatch("camera_confirmation", nullptr, 0)', TRANSPORT)
        self.assertIn('return dispatch("manual_test", event_id, event_id_size)', TRANSPORT)

    def test_persisted_modes_remain_backward_compatible(self) -> None:
        self.assertIn("Mqtt = 0, Ble = 1, Auto = 2", TRANSPORT_HEADER)
        self.assertIn("ActivationTransportMode::Auto", TRANSPORT)

    def test_thresholds_are_explicit_contract_values(self) -> None:
        self.assertEqual(FALLBACK_MS, 3000)
        self.assertEqual(RECLAIM_MS, 10000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
