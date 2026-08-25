"""Input-source independent actuation option resolution."""
import threading

def resolve_actuation_enabled(*, wav_path, enable_actuation=False, no_actuation=False):
    if enable_actuation and no_actuation:
        raise ValueError("--enable-actuation and --no-actuation cannot be used together")
    if enable_actuation:
        return True
    if no_actuation:
        return False
    return wav_path is None

def request_for_emitted_trigger(*, emitted_trigger, controller):
    if not emitted_trigger or controller is None:
        return None
    return controller.actuate()


class DelayedInteractionServo:
    """One cancellable local servo action for each admitted capture."""
    def __init__(self, controller, delay_seconds, *, emit=print, timer_factory=threading.Timer):
        self.controller, self.delay_seconds, self.emit, self._timer_factory = controller, delay_seconds, emit, timer_factory
        self._timer = None
    def schedule(self):
        if self.controller is None: return
        self.cancel(); self.emit(f"[Servo] scheduled +{self.delay_seconds:.2f} s")
        self._timer = self._timer_factory(self.delay_seconds, self._actuate); self._timer.daemon = True; self._timer.start()
    def _actuate(self):
        result = self.controller.actuate()
        if result.get("started"): self.emit("[Servo] actuated")
    def cancel(self):
        if self._timer: self._timer.cancel(); self._timer = None
