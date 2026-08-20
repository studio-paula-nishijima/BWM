class EventRouter:

    def __init__(self, backends):

        self.backends = backends

    def dispatch(self, event):

        event_type = event["type"]

        if event_type == "solenoid":

            self.backends["solenoid"].pulse(
                event["target"],
                event["duration"]
            )

        elif event_type == "gear_rack":

            self.backends["gear_rack"].execute(
                event
            )

        else:

            print(
                f"Unknown event type: {event_type}"
            )

    def begin_session(self):
        for backend in self.backends.values():
            begin = getattr(backend, "begin_session", None)
            if begin is not None:
                begin()

    def quiesce(self):
        """Quiesce reusable hardware without releasing process-level ownership."""
        for backend in self.backends.values():
            quiesce = getattr(backend, "quiesce", None)
            if quiesce is not None:
                quiesce()

    def is_idle(self):
        return all(getattr(backend, "is_idle", lambda: True)() for backend in self.backends.values())
