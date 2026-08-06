import csv
from pathlib import Path
from datetime import datetime



class WhisperCSVLogger:

    def __init__(
        self,
        filename,
        processing_mode=None,
        speech_detector_implementation=None,
    ):

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

        self.processing_mode = processing_mode
        self.speech_detector_implementation = speech_detector_implementation


        self.writer.writerow([

            "frame",
            "timestamp",

            "processing_mode",
            "speech_detector_implementation",

            # -----------------------------
            # Speech detector
            # -----------------------------

            "is_speech",
            "speech_probability",
            "speech_gate_open",


            # -----------------------------
            # Whisper detector
            # -----------------------------

            "is_whisper",
            "whisper_processed",
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

            processing_mode = result.processing_mode
            speech_gate_open = result.speech_gate_open
            whisper_processed = result.whisper_processed


        # ---------------------------------
        # Legacy whisper-only result
        # ---------------------------------

        else:

            speech = None

            whisper = result

            processing_mode = self.processing_mode
            speech_gate_open = True
            whisper_processed = True



        self.writer.writerow([


            frame_number,


            datetime.now()
            .isoformat(),

            processing_mode,
            self.speech_detector_implementation,



            # -----------------------------
            # Speech
            # -----------------------------

            (
                speech.is_speech
                if speech
                else None
            ),


            (
                speech.speech_probability
                if speech
                else None
            ),

            speech_gate_open,



            # -----------------------------
            # Whisper
            # -----------------------------

            whisper.is_whisper,

            whisper_processed,

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
