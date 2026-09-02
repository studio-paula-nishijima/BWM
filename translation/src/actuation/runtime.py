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
    """Cancellable delayed local feedback for each emitted whisper trigger."""
    def __init__(self, controller, delay_seconds, *, emit=print, timer_factory=threading.Timer):
        self.controller, self.delay_seconds, self.emit, self._timer_factory = controller, delay_seconds, emit, timer_factory
        self._timers = set()
    def schedule(self, sequence=None):
        if self.controller is None: return
        self.emit(f"[Servo] scheduled +{self.delay_seconds:.2f} s")
        timer = self._timer_factory(self.delay_seconds, lambda: self._actuate(sequence))
        self._timers.add(timer)
        timer.daemon = True
        timer.start()
    def _actuate(self, sequence=None):
        result = self.controller.actuate(sequence=sequence)
        if result.get("started"):
            self.emit("[Servo] actuated")
        else:
            self.emit(f"[Servo] suppressed: {result.get('suppression_reason', 'unavailable')}")
    def cancel(self):
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
