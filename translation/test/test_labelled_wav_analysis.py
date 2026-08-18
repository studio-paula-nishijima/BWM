import sys
import tempfile
import unittest
import warnings
import wave
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.labelled_wav import (AnnotationValidationError, analyse_triplets, evaluation_summary,
    feature_separation, feature_summary, join_frames_to_annotations, load_annotations,
    qualifying_run_summary, utterance_metadata_summary)


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

    def test_legacy_annotation_schema_remains_valid_with_blank_utterance_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._csv(directory, "start_seconds,end_seconds,label\n0,.5,whisper\n")
            loaded = load_annotations(path, directory, default_wav_file="a.wav")
            self.assertTrue(loaded.utterance_id.isna().all())
            self.assertTrue(loaded.transcription.isna().all())

    def test_extended_annotation_schema_preserves_shared_utterance_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._csv(directory,
                'start_seconds,end_seconds,label,utterance_id,language,transcription,speaker_id,session_id\n'
                '1.2,2.8,whisper,q001,en,"What happens when the river floods, then recedes?",speaker_01,session_a\n'
                '2.8,3.3,silence,q001,en,"What happens when the river floods, then recedes?",speaker_01,session_a\n'
                '3.3,5.1,whisper,q001,en,"What happens when the river floods, then recedes?",speaker_01,session_a\n')
            loaded = load_annotations(path, directory, default_wav_file="a.wav")
            self.assertEqual(loaded.utterance_id.tolist(), ["q001"] * 3)
            self.assertEqual(loaded.transcription.iloc[0], "What happens when the river floods, then recedes?")
            summary = utterance_metadata_summary(loaded)
            self.assertEqual(len(summary), 1)
            self.assertEqual(summary.start_seconds.iloc[0], 1.2)
            self.assertEqual(summary.end_seconds.iloc[0], 5.1)

    def test_conflicting_utterance_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._csv(directory,
                "start_seconds,end_seconds,label,utterance_id,language\n"
                "0,.1,whisper,q001,en\n.1,.2,silence,q001,de\n")
            with self.assertRaisesRegex(AnnotationValidationError, "Conflicting language"):
                load_annotations(path, directory, default_wav_file="a.wav")

    def test_join_uses_half_open_boundaries_and_metadata(self):
        anns = pd.DataFrame({"wav_file":["a.wav", "a.wav"], "start_seconds":[0, .06], "end_seconds":[.06, .12], "label":["silence", "whisper"], "notes":["quiet", "soft"]})
        rows = pd.DataFrame({"frame":[0, 1, 2, 3], "rms":[1, 2, 3, 4]})
        joined = join_frames_to_annotations(rows, anns, "a.wav")
        self.assertEqual(joined.annotation_label.tolist(), ["silence", "silence", "whisper", "whisper"])
        self.assertEqual(joined.annotation_notes.iloc[2], "soft")

    def test_join_propagates_compact_utterance_metadata_not_transcription(self):
        anns = pd.DataFrame({"wav_file": ["a.wav"], "start_seconds": [0], "end_seconds": [.06],
                             "label": ["whisper"], "utterance_id": ["q001"], "language": ["en"],
                             "transcription": ["A question, with punctuation!"], "speaker_id": ["speaker_01"],
                             "session_id": ["session_a"]})
        joined = join_frames_to_annotations(pd.DataFrame({"frame": [0, 1, 2]}), anns, "a.wav")
        self.assertEqual(joined.annotation_utterance_id.iloc[0], "q001")
        self.assertEqual(joined.annotation_language.iloc[0], "en")
        self.assertEqual(joined.annotation_speaker_id.iloc[0], "speaker_01")
        self.assertEqual(joined.annotation_session_id.iloc[0], "session_a")
        self.assertNotIn("annotation_transcription", joined.columns)

    def test_analysis_export_writes_transcription_once_per_utterance(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            annotation = self._csv(directory,
                "start_seconds,end_seconds,label,utterance_id,language,transcription,speaker_id,session_id\n"
                '0,.06,whisper,q001,en,"Question, with punctuation!",speaker_01,session_a\n')
            log = directory / "log.csv"
            pd.DataFrame({"frame": [0, 1], "is_speech": [True, True], "is_whisper": [True, True],
                          "whisper_processed": [True, True], "rms": [1., 1.]}).to_csv(log, index=False)
            results = analyse_triplets([(directory / "a.wav", log, annotation)], directory / "output")
            self.assertNotIn("annotation_transcription", results["labelled_frames"].columns)
            self.assertEqual(results["labelled_frames"].annotation_utterance_id.iloc[0], "q001")
            utterances = pd.read_csv(directory / "output" / "utterance_metadata.csv")
            self.assertEqual(utterances.transcription.iloc[0], "Question, with punctuation!")
            self.assertEqual(utterances.start_seconds.iloc[0], 0.)
            self.assertEqual(utterances.end_seconds.iloc[0], .06)

    def test_analysis_export_preserves_metadata_when_utterance_id_is_blank(self):
        annotations = pd.DataFrame({"wav_file": ["a.wav"], "start_seconds": [1.2], "end_seconds": [4.85],
                                    "label": ["whisper"], "utterance_id": [pd.NA], "language": ["english"],
                                    "transcription": ["A complete question"], "speaker_id": ["speaker_01"],
                                    "session_id": [pd.NA]})
        utterances = utterance_metadata_summary(annotations)
        self.assertEqual(len(utterances), 1)
        self.assertTrue(pd.isna(utterances.utterance_id.iloc[0]))
        self.assertEqual(utterances.transcription.iloc[0], "A complete question")

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
        whisper = result[result.stage == "whisper_vs_normal_speech"].iloc[0]
        self.assertEqual(whisper.frame_count, 3)  # one whisper bypassed, uncertain excluded
        full = evaluation_summary(frames, full_pipeline=True)
        self.assertEqual(full[full.stage == "whisper_vs_normal_speech"].iloc[0].frame_count, 4)

    def test_evaluation_names_both_whisper_scopes_and_segment_metrics(self):
        frames = self._frames()
        frames["temporal_v1_raw_is_whisper"] = False
        frames["temporal_v1_qualifying_run"] = 0
        frames["confirmation_requirement"] = 24
        frames["trigger"] = False
        result = evaluation_summary(frames)
        self.assertTrue({"whisper_vs_normal_speech", "whisper_vs_all_non_whisper", "whisper_sustained_segment", "whisper_trigger_segment"}.issubset(set(result.stage)))

    def test_cross_boundary_run_is_not_an_independent_non_whisper_sustained_event(self):
        frames = pd.DataFrame({
            "wav_file": ["a.wav"] * 9,
            "annotation_start_seconds": [0, 0] + [.1] * 7,
            "annotation_end_seconds": [.1, .1] + [.2] * 7,
            "annotation_label": ["whisper", "whisper"] + ["background_noise"] * 7,
            "temporal_v1_raw_is_whisper": [True] * 9,
            "temporal_v1_qualifying_run": list(range(13, 22)),
            "confirmation_requirement": [15] * 9,
            "trigger": [False] * 9,
        })
        summary = qualifying_run_summary(frames)
        background = summary[summary.annotation_label == "background_noise"].iloc[0]
        self.assertTrue(background.cross_boundary_continuation)
        self.assertEqual(background.cross_boundary_frame_count, 7)
        self.assertFalse(background.segment_local_sustained)
        sustained = evaluation_summary(frames).query("stage == 'whisper_sustained_segment'").iloc[0]
        self.assertEqual(sustained.fp, 0)

    def test_direct_mode_blank_speech_fields_and_weighting(self):
        frames = self._frames().drop(columns=["whisper_processed"]).copy()
        frames["is_speech"] = np.nan
        frame_summary = feature_summary(frames, "frame")
        segment_summary = feature_summary(frames, "segment")
        self.assertEqual(set(frame_summary.weighting), {"frame"})
        self.assertEqual(set(segment_summary.weighting), {"segment"})
        self.assertEqual(evaluation_summary(frames).query("stage == 'speech_vs_non_speech'").iloc[0].frame_count, 0)

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

    def test_equivalent_extended_metadata_does_not_change_metrics_or_runs(self):
        records = self._frames().copy()
        records["frame"] = range(len(records))
        records["temporal_v1_raw_is_whisper"] = [True, True, False, False, True, False]
        records["temporal_v1_qualifying_run"] = [1, 2, 0, 0, 1, 0]
        records["confirmation_requirement"] = 2
        records["trigger"] = [False, True, False, False, False, False]
        legacy = pd.DataFrame({"wav_file": ["a.wav"] * 3, "start_seconds": [0, .1, .2],
                               "end_seconds": [.1, .2, .3], "label": ["whisper", "normal_speech", "uncertain"]})
        extended = legacy.assign(utterance_id=["q001", pd.NA, pd.NA], language=["en", pd.NA, pd.NA],
                                 transcription=["Question?", pd.NA, pd.NA], speaker_id=["speaker_01", pd.NA, pd.NA],
                                 session_id=["session_a", pd.NA, pd.NA])
        old_frames = join_frames_to_annotations(records, legacy, "a.wav")
        new_frames = join_frames_to_annotations(records, extended, "a.wav")
        pd.testing.assert_frame_equal(evaluation_summary(old_frames), evaluation_summary(new_frames))
        pd.testing.assert_frame_equal(qualifying_run_summary(old_frames), qualifying_run_summary(new_frames))
        pd.testing.assert_frame_equal(feature_summary(old_frames), feature_summary(new_frames))


if __name__ == "__main__": unittest.main()
