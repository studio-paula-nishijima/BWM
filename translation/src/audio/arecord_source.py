import subprocess
import select
import time
import numpy as np

from .source import AudioSource, AudioFrame


class ArecordSource(AudioSource):

    def __init__(
        self,
        device,
        sample_rate,
        frame_size
    ):

        self.device = device
        self.sample_rate = sample_rate
        self.frame_size = frame_size

        self.frame_bytes = frame_size * 2

        self.proc = None
        self.frame_number = 0


    def open(self):

        self.proc = subprocess.Popen(
            [
                "arecord",
                "-D", self.device,
                "-f", "S16_LE",
                "-r", str(self.sample_rate),
                "-c", "1",
                "-t", "raw"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0
        )


    def read_frame(self):
    
        if self.proc is None:
            raise RuntimeError(
                "Audio source not opened"
            )
    
    
        while True:
    
            r, _, _ = select.select(
                [self.proc.stdout],
                [],
                [],
                1.0
            )
    
    
            if not r:
                continue
    
    
            data = self.proc.stdout.read(
                self.frame_bytes
            )
    
    
            # Live streams can occasionally return
            # incomplete reads. Ignore and retry.
            if len(data) != self.frame_bytes:
                continue
    
    
            samples = (
                np.frombuffer(
                    data,
                    dtype=np.int16
                )
                .astype(np.float32)
                /
                32768.0
            )
    
    
            frame = AudioFrame(
                samples=samples,
                timestamp=time.time(),
                frame_number=self.frame_number
            )
    
    
            self.frame_number += 1
    
    
            return frame


    def close(self):

        if self.proc:

            self.proc.terminate()
            self.proc = None
