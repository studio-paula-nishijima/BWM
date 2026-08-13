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

Generation-time safety is configuration-connected but disabled for the Stage 1 release baseline. Meaningful safety enforcement belongs to the later dynamic-runtime stage.
