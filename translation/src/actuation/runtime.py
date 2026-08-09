"""Input-source independent actuation option resolution."""

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
