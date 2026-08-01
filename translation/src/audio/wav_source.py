import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .source import AudioSource, AudioFrame


class WavSource(AudioSource):

    def __init__(
        self,
        filename,
        sample_rate,
        frame_size
    ):

        self.filename = Path(filename)
        self.sample_rate = sample_rate
        self.frame_size = frame_size

        self.audio = None
        self.position = 0
        self.frame_number = 0


    def open(self):

        audio, rate = sf.read(
            self.filename,
            dtype="float32"
        )


        if rate != self.sample_rate:

            raise ValueError(
                f"WAV sample rate {rate}Hz "
                f"does not match required "
                f"{self.sample_rate}Hz"
            )


        # Convert stereo to mono if required
        if len(audio.shape) > 1:

            audio = np.mean(
                audio,
                axis=1
            )


        self.audio = audio
        self.position = 0
        self.frame_number = 0


    def read_frame(self):

        if self.audio is None:

            raise RuntimeError(
                "WAV source not opened"
            )


        if self.position >= len(self.audio):

            return None


        end = (
            self.position +
            self.frame_size
        )


        samples = self.audio[
            self.position:end
        ]


        # Pad final frame so detector always receives
        # exactly FRAME_SIZE samples
        if len(samples) < self.frame_size:

            samples = np.pad(
                samples,
                (
                    0,
                    self.frame_size - len(samples)
                )
            )


        frame = AudioFrame(
            samples=samples,
            timestamp=time.time(),
            frame_number=self.frame_number
        )


        self.position = end
        self.frame_number += 1


        return frame


    def close(self):

        self.audio = None
