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
    # Spectral centroid
    # -----------------------------

    def spectral_centroid(
        self,
        signal: np.ndarray
    ) -> float:
        """
        Spectral centroid in Hz.
        """

        spectrum = np.abs(np.fft.rfft(signal))

        if spectrum.sum() == 0:
            return 0.0

        freqs = np.fft.rfftfreq(
            len(signal),
            d=1.0 / self.sample_rate
        )

        return float(
            np.sum(freqs * spectrum)
            / np.sum(spectrum)
        )

    # -----------------------------
    # Band energies
    # -----------------------------

    def band_energies(
        self,
        signal: np.ndarray,
    ) -> tuple[float, float, float]:
        """
        Return energy in three frequency bands.

        Low  : 300–1000 Hz
        Mid  : 1000–2500 Hz
        High : 2500–4000 Hz
        """

        spectrum = np.abs(
            np.fft.rfft(signal)
        ) ** 2

        freqs = np.fft.rfftfreq(
            len(signal),
            d=1.0 / self.sample_rate
        )

        def energy(low, high):
            mask = (
                (freqs >= low)
                & (freqs < high)
            )
            return float(
                spectrum[mask].sum()
            )

        return (
            energy(300, 1000),
            energy(1000, 2500),
            energy(2500, 4000),
        )

    # -----------------------------
    # Band energy ratios
    # -----------------------------

    def band_energy_ratios(
        self,
        low: float,
        mid: float,
        high: float,
    ) -> tuple[float, float, float]:
        """
        Return normalised band energy ratios.
        """

        total = low + mid + high

        if total <= 0:
            return (
                0.0,
                0.0,
                0.0,
            )

        return (
            low / total,
            mid / total,
            high / total,
        )

    # -----------------------------
    # Complete feature extraction
    # -----------------------------

    def extract(self, frame):

        filtered = self.bandpass(frame)

        centroid = self.spectral_centroid(
            filtered
        )

        (
            low_energy,
            mid_energy,
            high_energy,
        ) = self.band_energies(
            filtered
        )

        (
            low_ratio,
            mid_ratio,
            high_ratio,
        ) = self.band_energy_ratios(
            low_energy,
            mid_energy,
            high_energy,
        )

        return {
            "rms": self.rms(filtered),
            "zcr": self.zcr(filtered),
            "entropy": self.entropy(filtered),

            "centroid": centroid,

            "band_low": low_energy,
            "band_mid": mid_energy,
            "band_high": high_energy,

            "ratio_low": low_ratio,
            "ratio_mid": mid_ratio,
            "ratio_high": high_ratio,
        }
	
