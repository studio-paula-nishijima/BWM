import sys
import tempfile
import unittest
import warnings
import wave
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.labelled_wav import (AnnotationValidationError, evaluation_summary,
    feature_separation, feature_summary, join_frames_to_annotations, load_annotations)


class LabelledWavAnalysisTests(unittest.TestCase):
    def _csv(self, directory, text):
        path = Path(directory) / "annotations.csv"; path.write_text(text); return path

    def test_validation_requires_valid_non_overrunning_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "a.wav"
            with wave.open(str(wav), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(100); output.writeframes(b"\0\0" * 100)
            good = self._csv(directory, "wav_file,start_seconds,end_seconds,label\na.wav,0,0.5,whisper\n")
            self.assertEqual(len(load_annotations(good, directory)), 1)
            bad = self._csv(directory, "wav_file,start_seconds,end_seconds,label\na.wav,-1,2,other\n")
            with self.assertRaises(AnnotationValidationError): load_annotations(bad, directory)

    def test_one_file_per_wav_annotations_can_use_a_transient_wav_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._csv(directory, "start_seconds,end_seconds,label\n0,.5,whisper\n")
            with self.assertRaises(AnnotationValidationError): load_annotations(path, directory)
            loaded = load_annotations(path, directory, default_wav_file="a.wav")
            self.assertEqual(loaded.wav_file.iloc[0], "a.wav")

    def test_join_uses_half_open_boundaries_and_metadata(self):
        anns = pd.DataFrame({"wav_file":["a.wav", "a.wav"], "start_seconds":[0, .06], "end_seconds":[.06, .12], "label":["silence", "whisper"], "notes":["quiet", "soft"]})
        rows = pd.DataFrame({"frame":[0, 1, 2, 3], "rms":[1, 2, 3, 4]})
        joined = join_frames_to_annotations(rows, anns, "a.wav")
        self.assertEqual(joined.annotation_label.tolist(), ["silence", "silence", "whisper", "whisper"])
        self.assertEqual(joined.annotation_notes.iloc[2], "soft")

    def test_overlaps_warn_or_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._csv(directory, "wav_file,start_seconds,end_seconds,label\na.wav,0,.1,silence\na.wav,.05,.2,whisper\n")
            with warnings.catch_warnings(record=True) as caught: load_annotations(path, directory)
            self.assertTrue(caught)
            with self.assertRaises(AnnotationValidationError): load_annotations(path, directory, reject_overlaps=True)

    def _frames(self):
        return pd.DataFrame({"wav_file":["a.wav"]*6, "annotation_start_seconds":[0,0,.1,.1,.2,.2], "annotation_end_seconds":[.1,.1,.2,.2,.3,.3],
            "annotation_label":["whisper", "whisper", "normal_speech", "normal_speech", "uncertain", "silence"],
            "rms":[9., 11., 1., 3., 50., 0.], "is_speech":[True, True, True, True, False, False],
            "is_whisper":[True, True, False, False, True, False], "whisper_processed":[True, False, True, True, True, True]})

    def test_uncertain_excluded_and_bypassed_whisper_excluded_by_default(self):
        frames = self._frames()
        result = evaluation_summary(frames)
        whisper = result[result.stage == "whisper"].iloc[0]
        self.assertEqual(whisper.frame_count, 3)  # one whisper bypassed, uncertain excluded
        full = evaluation_summary(frames, full_pipeline=True)
        self.assertEqual(full[full.stage == "whisper"].iloc[0].frame_count, 4)

    def test_direct_mode_blank_speech_fields_and_weighting(self):
        frames = self._frames().drop(columns=["whisper_processed"]).copy()
        frames["is_speech"] = np.nan
        frame_summary = feature_summary(frames, "frame")
        segment_summary = feature_summary(frames, "segment")
        self.assertEqual(set(frame_summary.weighting), {"frame"})
        self.assertEqual(set(segment_summary.weighting), {"segment"})
        self.assertEqual(evaluation_summary(frames).query("stage == 'speech'").iloc[0].frame_count, 0)

    def test_segment_weighting_does_not_allow_long_segments_to_dominate(self):
        frames = pd.DataFrame({"wav_file": ["a.wav"] * 5,
            "annotation_label": ["whisper"] * 5,
            "annotation_start_seconds": [0, 0, 0, 0, 1],
            "annotation_end_seconds": [1, 1, 1, 1, 2], "rms": [10., 10., 10., 10., 0.]})
        frame_mean = feature_summary(frames, "frame").query("feature == 'rms'").iloc[0]["mean"]
        segment_mean = feature_summary(frames, "segment").query("feature == 'rms'").iloc[0]["mean"]
        self.assertEqual(frame_mean, 8.)
        self.assertEqual(segment_mean, 5.)

    def test_feature_metrics_include_threshold_and_confusion_matrix(self):
        separation = feature_separation(self._frames(), "frame")
        row = separation[(separation.comparison == "whisper_vs_normal_speech") & (separation.feature == "rms")].iloc[0]
        self.assertGreater(row.roc_auc, .9)
        self.assertIn("[[", row.confusion_matrix)
        self.assertTrue(np.isfinite(row.candidate_threshold))

    def test_feature_separation_handles_extreme_feature_ranges(self):
        frames = self._frames()
        frames["band_energy"] = [0., 0., 0., 1e300, np.inf, np.nan]
        separation = feature_separation(frames, "frame")
        row = separation[(separation.comparison == "whisper_vs_normal_speech") & (separation.feature == "band_energy")].iloc[0]
        self.assertTrue(np.isfinite(row.distribution_overlap))


if __name__ == "__main__": unittest.main()
