import wave
import numpy as np


class WavSource:

    def __init__(
        self,
        filename,
        sample_rate,
        frame_size
    ):

        self.filename = filename
        self.sample_rate = sample_rate
        self.frame_size = frame_size

        self.wav = wave.open(
            filename,
            "rb"
        )

        if self.wav.getnchannels() != 1:
            raise ValueError(
                "WAV must be mono"
            )

        if self.wav.getsampwidth() != 2:
            raise ValueError(
                "WAV must be 16-bit PCM"
            )

        if self.wav.getframerate() != sample_rate:
            raise ValueError(
                f"WAV sample rate must be {sample_rate}Hz"
            )


    def read_frame(self):

        data = self.wav.readframes(
            self.frame_size
        )

        if len(data) != self.frame_size * 2:
            return None


        frame = (
            np.frombuffer(
                data,
                dtype=np.int16
            )
            .astype(np.float32)
            /
            32768.0
        )

        return frame


    def close(self):

        self.wav.close()
