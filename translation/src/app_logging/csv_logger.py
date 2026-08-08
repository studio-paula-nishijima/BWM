import csv
from pathlib import Path
from datetime import datetime



class WhisperCSVLogger:

    def __init__(
        self,
        filename,
        processing_mode=None,
        speech_detector_implementation=None,
        comparison_speech_detector_implementation=None,
        whisper_classifier_implementation=None,
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
        self.comparison_speech_detector_implementation = comparison_speech_detector_implementation
        self.whisper_classifier_implementation = whisper_classifier_implementation


        self.writer.writerow([

            "frame",
            "timestamp",

            "processing_mode",
            "speech_detector_implementation",
            "comparison_speech_detector_implementation",

            # -----------------------------
            # Speech detector
            # -----------------------------

            "is_speech",
            "speech_probability",
            "speech_gate_open",
            "comparison_speech_evaluated",
            "comparison_speech_is_speech",
            "comparison_speech_aggressiveness",


            # -----------------------------
            # Whisper detector
            # -----------------------------

            "is_whisper",
            "whisper_processed",
            "trigger",

            "raw_score",
            "whisper_probability",
            "stage1_silero_threshold", "stage1_silero_low_pass", "stage1_enter_count", "stage1_exit_count", "stage1_candidate",
            "zcr_threshold", "zcr_pass", "centroid_threshold", "centroid_pass", "group_a_pass",
            "entropy_threshold", "group_b_pass", "total_band_energy", "low_proportion", "mid_proportion", "high_proportion", "low_proportion_threshold", "group_c_pass",
            "silero_rolling_median", "high_silero_threshold", "high_silero_raw", "high_silero_count", "high_silero_normal_evidence", "silero_penalty",
            "group_count", "effective_group_score", "grouped_v1_raw_is_whisper", "stage2_is_whisper", "stage2_consecutive_count",
            "legacy_is_whisper", "grouped_v1_is_whisper", "whisper_classifier_implementation", "final_trigger",


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
            "low_proportion_std", "mid_proportion_std", "high_proportion_std", "zcr_std", "entropy_std", "spectral_centroid_std", "spectral_flux", "cepstral_peak_prominence", "spectral_slope", "spectral_rolloff", "spectral_flatness",
            "temporal_v1_window_full", "temporal_v1_silero_median", "temporal_v1_low_proportion_std", "temporal_v1_silero_min_pass", "temporal_v1_silero_max_pass", "temporal_v1_low_proportion_std_pass", "temporal_v1_raw_is_whisper", "temporal_v1_is_whisper", "temporal_v1_qualifying_run", "confirmation_frames",

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
            speech_comparison = result.speech_comparison

            whisper = result.whisper

            processing_mode = result.processing_mode
            speech_gate_open = result.speech_gate_open
            whisper_processed = result.whisper_processed


        # ---------------------------------
        # Legacy whisper-only result
        # ---------------------------------

        else:

            speech = None
            speech_comparison = None

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
            self.comparison_speech_detector_implementation,



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
            bool(speech_comparison and speech_comparison.features.get("evaluated", False)),
            speech_comparison.is_speech if speech_comparison else None,
            speech_comparison.features.get("aggressiveness") if speech_comparison else None,



            # -----------------------------
            # Whisper
            # -----------------------------

            whisper.is_whisper,

            whisper_processed,

            triggered,

            whisper.raw_score,

            whisper.whisper_probability,
            *[getattr(whisper, name, None) for name in (
                "stage1_silero_threshold", "stage1_silero_low_pass", "stage1_enter_count", "stage1_exit_count", "stage1_candidate",
                "zcr_threshold", "zcr_pass", "centroid_threshold", "centroid_pass", "group_a_pass", "entropy_threshold", "group_b_pass",
                "total_band_energy", "low_proportion", "mid_proportion", "high_proportion", "low_proportion_threshold", "group_c_pass",
                "silero_rolling_median", "high_silero_threshold", "high_silero_raw", "high_silero_count", "high_silero_normal_evidence", "silero_penalty",
                "group_count", "effective_group_score", "grouped_v1_raw_is_whisper", "stage2_is_whisper", "stage2_consecutive_count",
                "legacy_is_whisper", "grouped_v1_is_whisper",
            )],
            getattr(whisper, "whisper_classifier_implementation", None) or self.whisper_classifier_implementation,
            triggered,



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
            *[getattr(whisper, name, None) for name in (
                "low_proportion_std", "mid_proportion_std", "high_proportion_std", "zcr_std", "entropy_std", "spectral_centroid_std", "spectral_flux", "cepstral_peak_prominence", "spectral_slope", "spectral_rolloff", "spectral_flatness",
            )],
            *[getattr(whisper, name, None) for name in (
                "temporal_v1_window_full", "temporal_v1_silero_median", "temporal_v1_low_proportion_std", "temporal_v1_silero_min_pass", "temporal_v1_silero_max_pass", "temporal_v1_low_proportion_std_pass", "temporal_v1_raw_is_whisper", "temporal_v1_is_whisper", "temporal_v1_qualifying_run", "confirmation_frames",
            )],

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
