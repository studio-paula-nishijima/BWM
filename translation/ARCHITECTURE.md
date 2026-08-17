# Translation architecture

Current base path:

`LamaH-CE -> event generation -> events.npy -> playback -> routing -> hardware`

`events.npy` is the persistent base score. The present system retains the released generator, score schema, playback ordering, and GPIO dispatch behaviour. Hardware topology is loaded from `configs/hardware.yaml`; its six current solenoids are not an architectural channel-count limit.

Target runtime path (documented only):

`events.npy -> Playback Engine -> Runtime Modulation Engine -> runtime safety/scheduling -> hardware`

The future Runtime Modulation Engine remains generic: it may support overlays/insertion, interruption, event transformation, suppression/filtering, parameter modulation, and strategies not yet anticipated. Cascades and multi-tap patterns are configurations/strategies using that layer, not architectural primitives.

Future external-event path (documented only):

`BWM semantic event layer -> translation-side policy/commands -> Runtime Modulation Engine`

Future compatibility includes shared semantic MQTT events, an MQTT-to-UART transport bridge, UART reservation on GPIO14/15, person-detector installation activation, GPIO17 as the local activation fallback, whisper/oracle semantic interaction and question events, a separate Voice Pi backup interaction button, and message IDs/origin metadata for transport deduplication. None is implemented in this stage.

## Future UART inter-Pi transport

GPIO14/TXD0 and GPIO15/RXD0 are reserved as the intended physical UART pins for the BWM inter-Pi transport. On the current Raspberry Pi 5 configuration, those pins are provided by RP1 UART0.

The future UART transport/bridge layer must resolve the device-tree `uart0` alias at runtime, derive the corresponding `/dev/tty*` node explicitly, and open that resolved node. It must not use `/dev/serial0` as the BWM transport selector: on the tested Pi 5 configuration, `/dev/serial0` resolves to `/dev/ttyAMA10`, the debug UART, while GPIO14/15 resolve to `/dev/ttyAMA0`. `/dev/ttyAMA0` is an observed mapping on that configuration, not a device name to hard-code as the architectural contract.

Before opening the resolved UART, the transport/bridge layer must perform startup ownership checks and fail clearly if the device is claimed by either the kernel serial console or a `serial-getty` service.

Conceptual flow:

`BWM semantic message -> UART transport adapter -> resolve DT uart0 alias -> validate device ownership -> open resolved /dev/tty* -> GPIO14/15`

Device-tree resolution and UART ownership checks belong exclusively to the UART transport/bridge layer. MQTT/common semantic events and translation runtime logic remain independent of Linux UART device names and of whether a semantic message crosses UART or IP networking. Message IDs/origin metadata remain the planned deduplication mechanism if redundant transports are enabled.

Generation-time safety is configuration-connected but disabled for the Stage 1 release baseline. Meaningful safety enforcement belongs to the later dynamic-runtime stage.
