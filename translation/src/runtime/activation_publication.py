"""Best-effort notification of Translation's authoritative activation state."""

from shared.messaging.events import installation_activation


class TranslationActivationPublisher:
    """Construct one new semantic state notification for each local transition."""

    ORIGIN = "translation_pi"

    def __init__(self, uart_transport=None, *, emit=print):
        self._uart_transport = uart_transport
        self._emit = emit

    def set_uart_transport(self, uart_transport):
        self._uart_transport = uart_transport

    def publish(self, state):
        event = installation_activation(self.ORIGIN, state)
        transport = self._uart_transport
        if transport is None:
            self._emit(f"[SemanticTx] transport=uart type=installation.activation origin={self.ORIGIN} "
                       f"state={state} result=unavailable; local_state_retained")
            return False
        try:
            sent = bool(transport.send(event))
        except Exception as exc:
            self._emit(f"[SemanticTx] transport=uart type=installation.activation origin={self.ORIGIN} "
                       f"state={state} result=failed; local_state_retained error={exc}")
            return False
        if sent:
            self._emit(f"[SemanticTx] transport=uart type={event.event_type} origin={event.origin} "
                       f"state={state} id={event.id} result=sent")
        else:
            self._emit(f"[SemanticTx] transport=uart type={event.event_type} origin={event.origin} "
                       f"state={state} id={event.id} result=failed; local_state_retained")
        return sent
