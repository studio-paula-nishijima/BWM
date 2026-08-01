"""
Stage 3C - Circular audio buffer

Stores recent audio frames using constant memory.

Designed to sit after frame acquisition:

Audio Source
      |
      ▼
Frame Source
      |
      ▼
Ring Buffer   <-- this module
      |
      ▼
Whisper Detector
"""


from collections import deque
import numpy as np


class AudioRingBuffer:
    """
    Circular buffer for audio frames.

    Stores a configurable duration of audio while maintaining
    constant memory usage.

    Frames are expected to be numpy arrays containing PCM samples.
    """

    def __init__(
        self,
        sample_rate,
        buffer_seconds,
    ):
        """
        Parameters
        ----------
        sample_rate : int
            Audio sample rate in Hz.

        buffer_seconds : float
            Maximum duration stored.
        """

        self.sample_rate = sample_rate
        self.buffer_seconds = buffer_seconds

        self.max_samples = int(
            sample_rate * buffer_seconds
        )

        self.buffer = deque()

        self.current_samples = 0


    def append(self, frame):
        """
        Add an audio frame.

        Parameters
        ----------
        frame : numpy.ndarray

            PCM audio samples.
        """

        frame = np.asarray(frame)

        self.buffer.append(frame)

        self.current_samples += len(frame)


        # Remove oldest frames until within limit
        while self.current_samples > self.max_samples:

            old = self.buffer.popleft()

            self.current_samples -= len(old)



    def get_recent(self, seconds=None):
        """
        Return most recent audio.

        Parameters
        ----------
        seconds : float | None

            Duration requested.

            None returns entire buffer.


        Returns
        -------
        numpy.ndarray
        """

        if seconds is None:
            seconds = self.buffer_seconds


        requested_samples = int(
            seconds * self.sample_rate
        )


        if not self.buffer:
            return np.array(
                [],
                dtype=np.float32
            )


        frames = []

        samples = 0


        # Walk backwards through buffer

        for frame in reversed(self.buffer):

            frames.insert(
                0,
                frame
            )

            samples += len(frame)


            if samples >= requested_samples:
                break


        audio = np.concatenate(frames)


        # Trim excess from beginning

        if len(audio) > requested_samples:

            audio = audio[-requested_samples:]


        return audio



    def clear(self):
        """
        Empty buffer.
        """

        self.buffer.clear()

        self.current_samples = 0



    def duration(self):
        """
        Current stored duration in seconds.
        """

        return (
            self.current_samples /
            self.sample_rate
        )
