import numpy as np
from scipy.signal import butter, lfilter


class WhisperFeatures:
    """
    Acoustic feature extraction.

    Stage 1:
    Contains only the existing feature calculations.
    
    Future:
    - voicing
    - HNR
    - formants
    - spectral centroid
    - band energy ratios
    """

    def __init__(
        self,
        sample_rate=16000
    ):
        self.sample_rate = sample_rate


    # -----------------------------
    # Filtering
    # -----------------------------

    def bandpass(
        self,
        signal,
        low=300,
        high=4000,
        order=4
    ):

        nyq = 0.5 * self.sample_rate

        b, a = butter(
            order,
            [
                low / nyq,
                high / nyq
            ],
            btype="band"
        )

        return lfilter(
            b,
            a,
            signal
        )


    # -----------------------------
    # RMS
    # -----------------------------

    def rms(self, x):

        return np.sqrt(
            np.mean(x ** 2) + 1e-9
        )


    # -----------------------------
    # Zero crossing rate
    # -----------------------------

    def zcr(self, x):

        return (
            np.mean(
                np.abs(
                    np.diff(
                        np.sign(x)
                    )
                )
            )
            / 2
        )


    # -----------------------------
    # Spectral entropy
    # -----------------------------

    def entropy(
        self,
        x,
        eps=1e-9
    ):

        fft = np.fft.rfft(x)

        psd = np.abs(fft) ** 2

        psd /= (
            np.sum(psd)
            + eps
        )

        return -np.sum(
            psd *
            np.log(
                psd + eps
            )
        )


    # -----------------------------
    # Complete feature extraction
    # -----------------------------

    def extract(self, frame):

        filtered = self.bandpass(frame)

        return {
            "rms": self.rms(filtered),
            "zcr": self.zcr(filtered),
            "entropy": self.entropy(filtered),
        }
