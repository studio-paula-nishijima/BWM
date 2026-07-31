from collections import deque


class TemporalSmoother:
    """
    Handles frame history and decision smoothing.

    Stage 1:
    Replicates the existing behaviour:
        - 10-frame history
        - whisper ratio threshold
    """

    def __init__(
        self,
        window_size=10,
        trigger_ratio=0.6
    ):

        self.history = deque(
            maxlen=window_size
        )

        self.trigger_ratio = trigger_ratio


    def update(self, value):

        self.history.append(
            bool(value)
        )

        stability = (
            sum(self.history)
            /
            len(self.history)
        )

        return stability > self.trigger_ratio


    def reset(self):

        self.history.clear()
