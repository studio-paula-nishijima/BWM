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

            # -----------------------------
            # Speech detector
            # -----------------------------

            "is_speech",
            "speech_probability",


            # -----------------------------
            # Whisper detector
            # -----------------------------

            "is_whisper",
            "trigger",

            "raw_score",
            "whisper_probability",


            # -----------------------------
            # Acoustic features
            # -----------------------------

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

        """
        Stage 3E compatible logger.

        Accepts:

            DetectorPipelineResult

        containing:

            result.speech
            result.whisper


        Backwards compatibility:

            Also accepts WhisperDetectionResult directly.
        """


        # ---------------------------------
        # Stage 3E pipeline result
        # ---------------------------------

        if hasattr(result, "speech"):

            speech = result.speech

            whisper = result.whisper


        # ---------------------------------
        # Legacy whisper-only result
        # ---------------------------------

        else:

            speech = None

            whisper = result



        self.writer.writerow([


            frame_number,


            datetime.now()
            .isoformat(),



            # -----------------------------
            # Speech
            # -----------------------------

            (
                speech.is_speech
                if speech
                else False
            ),


            (
                speech.speech_probability
                if speech
                else 0.0
            ),



            # -----------------------------
            # Whisper
            # -----------------------------

            whisper.is_whisper,

            triggered,


            whisper.raw_score,

            whisper.whisper_probability,



            # -----------------------------
            # Features
            # -----------------------------

            whisper.rms,

            whisper.zcr,

            whisper.entropy,


            whisper.voicing,

            whisper.hnr,


            whisper.spectral_centroid,


            whisper.band_energy_low,

            whisper.band_energy_mid,

            whisper.band_energy_high,


            whisper.temporal_score,

            whisper.formant_score,

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
