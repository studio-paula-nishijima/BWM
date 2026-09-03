"""Translation-specific interpretation of shared BWM semantic events."""
import logging
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import INSTALLATION_ACTIVATION, VOICE_INTERACTION, VOICE_STATE, VOICE_STATES, SemanticEvent

LOG = logging.getLogger(__name__)


class TranslationSemanticIngress:
    """Transport-neutral validation, deduplication, and Translation interpretation."""
    def __init__(self, runtime, activation_topic: str, voice_state_topic=None, voice_interaction_topic=None, recent_ids=None):
        self._runtime, self._activation_topic, self._voice_state_topic, self._voice_interaction_topic = runtime, activation_topic, voice_state_topic, voice_interaction_topic
        self._recent_ids = recent_ids or RecentEventIds()

    def handle(self, topic: str, event: SemanticEvent, *, publish_authoritative=True, transport="unknown") -> bool:
        if topic == self._voice_state_topic and event.event_type == VOICE_STATE:
            if self._recent_ids.seen(event.id):
                LOG.info("Duplicate Voice state ignored: %s", event.id)
                return "ignored_duplicate"
            state = event.payload.get("state")
            if state not in VOICE_STATES:
                LOG.warning("Rejected invalid Voice state: %r", state)
                return "rejected_invalid"
            print("[SemanticRx] "
                  f"transport={transport} type={event.event_type} origin={event.origin} "
                  f"state={state} id={event.id}")
            return self._runtime.observe_voice_state(state)
        if topic == self._voice_interaction_topic and event.event_type == VOICE_INTERACTION:
            if self._recent_ids.seen(event.id):
                return "ignored_duplicate"
            source, value = event.payload.get("source"), event.payload.get("silero_selection_value")
            if source not in {"detector", "button"} or (source == "detector" and not isinstance(value, (int, float))) or (source == "button" and value is not None):
                return "rejected_invalid"
            return self._runtime.observe_voice_interaction(event.payload)
        if topic != self._activation_topic or event.event_type != INSTALLATION_ACTIVATION:
            print(f"[Semantic ingress] REJECTED routing topic={topic} id={event.id} "
                  f"type={event.event_type} origin={event.origin}")
            return False
        if self._recent_ids.seen(event.id):
            LOG.info("Duplicate semantic event ignored: %s", event.id)
            print(f"[Semantic ingress] DEDUPLICATION duplicate id={event.id} "
                  f"type={event.event_type} origin={event.origin}; ignored")
            return False
        state = event.payload.get("state")
        if state not in {"active", "inactive"}:
            LOG.warning("Rejected installation activation with invalid state: %r", state)
            print(f"[Semantic ingress] VALIDATION rejected id={event.id} type={event.event_type} "
                  f"origin={event.origin} timestamp={event.timestamp} state={state!r}")
            return False
        print(f"[Semantic ingress] VALIDATION accepted id={event.id} type={event.event_type} "
              f"origin={event.origin} timestamp={event.timestamp} state={state} deduplication=new")
        if state == "active":
            changed = (self._runtime.activate() if publish_authoritative
                       else self._runtime.activate(publish=False))
            LOG.info("Remote activation %s", "started session" if changed else "ignored; already active")
            print(f"[Semantic ingress] ADMISSION id={event.id} result=" +
                  ("admitted_session_started" if changed else "ignored_already_active"))
            return changed
        if state == "inactive":
            changed = (self._runtime.deactivate() if publish_authoritative
                       else self._runtime.deactivate(publish=False))
            LOG.info("Remote deactivation %s", "cancelled session" if changed else "ignored; already idle")
            print(f"[Semantic ingress] ADMISSION id={event.id} result=" +
                  ("admitted_session_cancelled" if changed else "ignored_already_quiescent"))
            return changed

    def handle_event(self, event: SemanticEvent, *, publish_authoritative=True, transport="unknown") -> bool:
        """Accept a decoded event from any transport without transport policy."""
        if event.event_type == VOICE_STATE and self._voice_state_topic:
            return self.handle(self._voice_state_topic, event, transport=transport)
        if event.event_type == VOICE_INTERACTION and self._voice_interaction_topic:
            return self.handle(self._voice_interaction_topic, event, transport=transport)
        if event.event_type == INSTALLATION_ACTIVATION:
            return self.handle(self._activation_topic, event,
                               publish_authoritative=publish_authoritative, transport=transport)
        return False


class TranslationMQTTAdapter(TranslationSemanticIngress):
    """Compatibility name; this adapter is now transport-neutral semantic ingress."""
