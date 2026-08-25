"""Translation-specific interpretation of shared BWM semantic events."""
import logging
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import INSTALLATION_ACTIVATION, VOICE_STATE, VOICE_STATES, SemanticEvent

LOG = logging.getLogger(__name__)


class TranslationSemanticIngress:
    """Transport-neutral validation, deduplication, and Translation interpretation."""
    def __init__(self, runtime, activation_topic: str, voice_state_topic=None, recent_ids=None):
        self._runtime, self._activation_topic, self._voice_state_topic = runtime, activation_topic, voice_state_topic
        self._recent_ids = recent_ids or RecentEventIds()

    def handle(self, topic: str, event: SemanticEvent) -> bool:
        if topic == self._voice_state_topic and event.event_type == VOICE_STATE:
            if self._recent_ids.seen(event.id):
                LOG.info("Duplicate Voice state ignored: %s", event.id)
                return "ignored_duplicate"
            state = event.payload.get("state")
            if state not in VOICE_STATES:
                LOG.warning("Rejected invalid Voice state: %r", state)
                return "rejected_invalid"
            return self._runtime.observe_voice_state(state)
        if topic != self._activation_topic or event.event_type != INSTALLATION_ACTIVATION:
            return False
        if self._recent_ids.seen(event.id):
            LOG.info("Duplicate semantic event ignored: %s", event.id)
            print(f"[Semantic ingress] Duplicate event ignored: {event.id}")
            return False
        state = event.payload.get("state")
        if state == "active":
            changed = self._runtime.activate()
            LOG.info("Remote activation %s", "started session" if changed else "ignored; already active")
            print("[Semantic ingress] installation active: " + ("started session" if changed else "already active"))
            return changed
        if state == "inactive":
            changed = self._runtime.deactivate()
            LOG.info("Remote deactivation %s", "cancelled session" if changed else "ignored; already idle")
            print("[Semantic ingress] installation inactive: " + ("cancelled session" if changed else "already idle"))
            return changed
        LOG.warning("Rejected installation activation with invalid state: %r", state)
        print(f"[Semantic ingress] Rejected invalid installation state: {state!r}")
        return False

    def handle_event(self, event: SemanticEvent) -> bool:
        """Accept a decoded event from any transport without transport policy."""
        if event.event_type == VOICE_STATE and self._voice_state_topic:
            return self.handle(self._voice_state_topic, event)
        if event.event_type == INSTALLATION_ACTIVATION:
            return self.handle(self._activation_topic, event)
        return False


class TranslationMQTTAdapter(TranslationSemanticIngress):
    """Compatibility name; this adapter is now transport-neutral semantic ingress."""
