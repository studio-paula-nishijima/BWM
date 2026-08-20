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
