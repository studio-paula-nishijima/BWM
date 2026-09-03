# Translation guidance

1. Preserve the LamaH-CE -> `events.npy` base translation path unless the active stage explicitly changes it.
2. `events.npy` is the base score; future interactions act on runtime state/events rather than rewriting it repeatedly.
3. Never assume a fixed solenoid or actuator count: hardware topology is configuration-driven.
4. Keep data translation/preprocessing, event generation, playback, runtime modulation, scheduling/safety, hardware control, and communications separate.
5. Shared/external messages describe semantic events, never GPIO operations or physical transports.
6. Physical fallback controls must not depend on the subsystem they replace.
7. GPIO14/15 are reserved for the BWM UART transport; do not assume `/dev/serial0`. When UART work begins, follow the runtime device-tree `uart0` alias resolution and startup ownership checks in `ARCHITECTURE.md`. GPIO17 is the local translation activation backup button; GPIO2/3 are I2C-reserved.
8. Preserve released/default behaviour unless the current stage explicitly changes it.
9. Do not introduce future-stage abstractions speculatively.
10. Read `ARCHITECTURE.md` before significant playback, runtime, modulation, safety, or messaging changes.
11. All hardware-bound runtime events, including modulation-generated events, must pass through RuntimeSafety. Do not use runtime safety to tune artistic behaviour without explicit approval and measured evidence.
11. Installation activation is application state, not process lifecycle: inactive playback preserves its logical score position and must not busy-spin.
12. Session teardown must quiesce reusable hardware before IDLE; never substitute full backend shutdown, and no old-session actuation may occur after IDLE.
13. For live Voice/Whisper work, read `VOICE_ARCHITECTURE.md`: preserve its authoritative lifecycle and busy-admission semantics.  Only display completion normally releases an admitted interaction.
14. Keep Voice boundaries separate: attach downstream work to structured ASR results, use the retrieval runtime adapter, keep retrieval response text opaque at the Voice/display boundary, and reuse `shared/messaging/` rather than a Voice MQTT stack.
15. Voice publishes semantic lifecycle state only.  Translation owns reaction selection, modulation, safety, and hardware behaviour.
16. Build one semantic event before MQTT/UART fan-out and preserve its ID/origin. UART resolves DT `uart0`, never `/dev/serial0`, and cannot bypass semantic ingress/deduplication/admission.
17. Any implementation changing runtime, hardware, deployment, service, or behaviour configuration must explicitly report every configuration file/key changed, its previous and new values when known, whether it changes tracked defaults or deployment-local overrides, and any required Pi-side action. Inspect and preserve uncommitted configuration changes before editing; never silently normalize Pi-local tuning or alter unrelated defaults.
