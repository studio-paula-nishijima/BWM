"""Transport-neutral Voice semantic ingress seam; it intentionally owns no policy."""
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import INSTALLATION_ACTIVATION, SemanticEvent


class VoiceSemanticIngress:
    """Deliver valid, de-duplicated installation state to an integration callback.

    The Voice lifecycle deliberately does not subscribe to this seam yet: deciding
    whether installation state affects Voice remains a Voice/demo policy decision.
    """
    def __init__(self, on_installation_activation, recent_ids=None):
        self._callback = on_installation_activation
        self._recent_ids = recent_ids or RecentEventIds()

    def handle_event(self, event: SemanticEvent) -> bool:
        if event.event_type != INSTALLATION_ACTIVATION or self._recent_ids.seen(event.id):
            return False
        state = event.payload.get("state")
        if state not in {"active", "inactive"}:
            return False
        self._callback(state, event)
        return True
