import numpy as np
import collections
from scipy.signal import butter, lfilter


class WhisperDetector:

    def __init__(self):
        self.history = collections.deque(maxlen=10)

        self.rms_min = 0.005
        self.rms_max = 0.1

        self.zcr_min = 0.05
        self.zcr_max = 0.3

        self.entropy_min = 4.5

    def _bandpass(self, signal, low=300, high=4000, fs=16000, order=4):
        nyq = 0.5 * fs
        b, a = butter(order, [low / nyq, high / nyq], btype="band")
        return lfilter(b, a, signal)

    def _rms(self, x):
        return np.sqrt(np.mean(x ** 2) + 1e-9)

    def _zcr(self, x):
        return np.mean(np.abs(np.diff(np.sign(x)))) / 2

    def _entropy(self, x, eps=1e-9):
        fft = np.fft.rfft(x)
        psd = np.abs(fft) ** 2
        psd = psd / (np.sum(psd) + eps)
        return -np.sum(psd * np.log(psd + eps))

    def classify(self, frame):

        frame = self._bandpass(frame)

        r = self._rms(frame)
        z = self._zcr(frame)
        e = self._entropy(frame)

        score = 0

        if self.rms_min < r < self.rms_max:
            score += 1
        if self.zcr_min < z < self.zcr_max:
            score += 1
        if e > self.entropy_min:
            score += 1

        is_whisper = score >= 2

        self.history.append(is_whisper)
        stability = sum(self.history) / len(self.history)

        return stability > 0.6, (r, z, e)
