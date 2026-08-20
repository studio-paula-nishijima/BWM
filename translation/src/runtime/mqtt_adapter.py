"""Translation-specific interpretation of shared BWM semantic events."""
import logging
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import INSTALLATION_ACTIVATION, SemanticEvent

LOG = logging.getLogger(__name__)


class TranslationMQTTAdapter:
    def __init__(self, runtime, activation_topic: str, recent_ids=None):
        self._runtime, self._activation_topic = runtime, activation_topic
        self._recent_ids = recent_ids or RecentEventIds()

    def handle(self, topic: str, event: SemanticEvent) -> bool:
        if topic != self._activation_topic or event.event_type != INSTALLATION_ACTIVATION:
            return False
        if self._recent_ids.seen(event.id):
            LOG.info("Duplicate semantic event ignored: %s", event.id)
            return False
        state = event.payload.get("state")
        if state == "active":
            changed = self._runtime.activate()
            LOG.info("Remote activation %s", "started session" if changed else "ignored; already active")
            return changed
        if state == "inactive":
            changed = self._runtime.deactivate()
            LOG.info("Remote deactivation %s", "cancelled session" if changed else "ignored; already idle")
            return changed
        LOG.warning("Rejected installation activation with invalid state: %r", state)
        return False
