import heapq


class EventQueue:

    def __init__(self):

        self.queue = []

    def add_event(self, event):

        heapq.heappush(
            self.queue,
            (event["time"], event)
        )

    def add_events(self, events):

        for e in events:
            self.add_event(e)

    def pop_next(self):

        if not self.queue:
            return None

        return heapq.heappop(self.queue)[1]

    def is_empty(self):

        return len(self.queue) == 0
