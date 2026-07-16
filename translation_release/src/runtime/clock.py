import time


class RealtimeClock:

    def __init__(self):

        self.start = time.time()

    def now(self):

        return time.time() - self.start


class SimulatedClock:

    def __init__(self):

        self.t = 0.0

    def now(self):

        return self.t

    def advance(self, dt):

        self.t += dt
