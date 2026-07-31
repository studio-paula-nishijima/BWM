import time

class EventPlayer:
    def __init__(self, events, backend):
        self.events = sorted(events, key=lambda x: x[0])
        self.backend = backend

    def play(self):
        start = time.time()

        for t, typ, dur in self.events:
            while time.time() - start < t:
                time.sleep(0.001)

            self.backend.pulse("solenoid_1", dur)
