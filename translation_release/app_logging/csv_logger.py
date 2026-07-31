import csv
from pathlib import Path
from datetime import datetime


class WhisperCSVLogger:

    def __init__(self, filename):

        self.filename = Path(filename)

        self.filename.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.file = open(
            self.filename,
            "w",
            newline=""
        )

        self.writer = csv.writer(
            self.file
        )

        self.writer.writerow([
            "frame",
            "timestamp",

            "is_whisper",
            "trigger",

            "raw_score",
            "probability",

            "rms",
            "zcr",
            "entropy",

            "voicing",
            "hnr",
            "spectral_centroid",

            "band_energy_low",
            "band_energy_mid",
            "band_energy_high",

            "temporal_score",
            "formant_score",
        ])


    def log(
        self,
        frame_number,
        result,
        triggered
    ):

        self.writer.writerow([

            frame_number,

            datetime.now()
            .isoformat(),

            result.is_whisper,
            triggered,

            result.raw_score,
            result.whisper_probability,

            result.rms,
            result.zcr,
            result.entropy,

            result.voicing,
            result.hnr,
            result.spectral_centroid,

            result.band_energy_low,
            result.band_energy_mid,
            result.band_energy_high,

            result.temporal_score,
            result.formant_score,
        ])


        # Flush every frame.
        # This slightly increases SD writes,
        # but protects against power loss
        # during testing.
        self.file.flush()


    def close(self):

        try:
            self.file.close()
        except Exception:
            pass
