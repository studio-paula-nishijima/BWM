"""Transport-neutral Voice semantic ingress seam; it intentionally owns no policy."""
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import INSTALLATION_ACTIVATION, SemanticEvent


class VoiceSemanticIngress:
    """Deliver valid, de-duplicated installation state to an integration callback.

    The Voice lifecycle deliberately does not subscribe to this seam yet: deciding
    whether installation state affects Voice remains a Voice/demo policy decision.
    """
    def __init__(self, on_installation_activation, recent_ids=None, *, emit=print):
        self._callback = on_installation_activation
        self._recent_ids = recent_ids or RecentEventIds()
        self._emit = emit

    def handle_event(self, event: SemanticEvent, *, transport="unknown") -> bool:
        if event.event_type != INSTALLATION_ACTIVATION or self._recent_ids.seen(event.id):
            return False
        state = event.payload.get("state")
        if state not in {"active", "inactive"}:
            return False
        self._emit("[SemanticRx] "
                   f"transport={transport} type={event.event_type} origin={event.origin} "
                   f"state={state} id={event.id}")
        self._callback(state, event)
        return True
