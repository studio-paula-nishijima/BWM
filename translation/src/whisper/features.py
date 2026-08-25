from collections import deque

import numpy as np
from scipy.signal import butter, lfilter


class AudioFeatures:
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
        sample_rate=16000,
        rolling_window_frames=10,
    ):
        self.sample_rate = sample_rate
        self.rolling_window_frames = rolling_window_frames
        self.reset()

    def reset(self):
        self._previous_normalised_spectrum = None
        self._history = {name: deque(maxlen=self.rolling_window_frames) for name in (
            "low_proportion", "mid_proportion", "high_proportion", "zcr", "entropy", "centroid"
        )}

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

    def extract(self, frame, analysis_full=True):

        filtered = self.bandpass(frame)

        spectrum = np.abs(np.fft.rfft(filtered))
        power = spectrum ** 2
        freqs = np.fft.rfftfreq(len(filtered), d=1.0 / self.sample_rate)
        spectrum_total = spectrum.sum()

        def energy(low, high):
            return float(power[(freqs >= low) & (freqs < high)].sum())

        low_energy, mid_energy, high_energy = (
            energy(300, 1000),
            energy(1000, 2500),
            energy(2500, 4000),
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

        total_band_energy = low_energy + mid_energy + high_energy + 1e-12
        low_proportion = low_energy / total_band_energy
        mid_proportion = mid_energy / total_band_energy
        high_proportion = high_energy / total_band_energy
        self._history["low_proportion"].append(low_proportion)
        zcr = self.zcr(filtered)
        self._history["zcr"].append(zcr)
        window_full = len(self._history["low_proportion"]) == self.rolling_window_frames
        low_std = float(np.std(self._history["low_proportion"], ddof=0)) if window_full else None
        zcr_std = float(np.std(self._history["zcr"], ddof=0)) if window_full else None
        if not analysis_full:
            return {
                "band_low": low_energy, "band_mid": mid_energy, "band_high": high_energy,
                "ratio_low": low_ratio, "ratio_mid": mid_ratio, "ratio_high": high_ratio,
                "total_band_energy": total_band_energy, "low_proportion": low_proportion,
                "mid_proportion": mid_proportion, "high_proportion": high_proportion,
                "rolling_window_full": window_full, "low_proportion_std": low_std, "zcr": zcr, "zcr_std": zcr_std, "rms": self.rms(filtered), "acoustic_rms": float(np.sqrt(np.mean(filtered ** 2))),
            }

        centroid = float(np.sum(freqs * spectrum) / spectrum_total) if spectrum_total else 0.0
        entropy = -np.sum((power / (power.sum() + 1e-9)) * np.log(power / (power.sum() + 1e-9) + 1e-9))
        normalised = spectrum / (spectrum_total + 1e-12)
        flux = None if self._previous_normalised_spectrum is None else float(np.sum((normalised - self._previous_normalised_spectrum) ** 2))
        self._previous_normalised_spectrum = normalised
        for name, value in {"mid_proportion": mid_proportion, "high_proportion": high_proportion,
                            "entropy": entropy, "centroid": centroid}.items():
            self._history[name].append(value)
        rolling_std = {name: (float(np.std(values, ddof=0)) if len(values) == self.rolling_window_frames else None) for name, values in self._history.items()}

        cumulative = np.cumsum(power)
        rolloff_index = int(np.searchsorted(cumulative, 0.85 * power.sum())) if power.sum() else 0
        positive = power[power > 0]
        flatness = float(np.exp(np.mean(np.log(positive))) / np.mean(positive)) if len(positive) else 0.0
        valid = spectrum > 0
        slope = float(np.polyfit(freqs[valid], np.log(spectrum[valid]), 1)[0]) if valid.sum() > 1 else 0.0
        autocorrelation = np.correlate(filtered, filtered, mode="full")[len(filtered) - 1:]
        peak = float(np.max(autocorrelation[1:])) if len(autocorrelation) > 1 else 0.0
        periodicity = peak / (float(autocorrelation[0]) + 1e-12)
        noise_floor = float(np.mean(autocorrelation[1:])) if len(autocorrelation) > 1 else 0.0
        hnr = float(10 * np.log10(max(peak - noise_floor, 1e-12) / max(noise_floor, 1e-12)))
        cepstrum = np.fft.irfft(np.log(spectrum + 1e-12))
        cpp = float(np.max(cepstrum[1:]) - np.mean(cepstrum[1:])) if len(cepstrum) > 1 else 0.0

        return {
            "rms": self.rms(filtered),
            "zcr": zcr,
            "entropy": float(entropy),

            "centroid": centroid,

            "band_low": low_energy,
            "band_mid": mid_energy,
            "band_high": high_energy,

            "ratio_low": low_ratio,
            "ratio_mid": mid_ratio,
            "ratio_high": high_ratio,
            "total_band_energy": total_band_energy,
            "low_proportion": low_proportion,
            "mid_proportion": mid_proportion,
            "high_proportion": high_proportion,
            "rolling_window_full": window_full,
            "low_proportion_std": low_std,
            "mid_proportion_std": rolling_std["mid_proportion"],
            "high_proportion_std": rolling_std["high_proportion"],
            "zcr_std": zcr_std,
            "entropy_std": rolling_std["entropy"],
            "centroid_std": rolling_std["centroid"],
            "spectral_flux": flux,
            "voicing": periodicity,
            "hnr": hnr,
            "cepstral_peak_prominence": cpp,
            "spectral_slope": slope,
            "spectral_rolloff": float(freqs[min(rolloff_index, len(freqs) - 1)]),
            "spectral_flatness": flatness,
        }
	
