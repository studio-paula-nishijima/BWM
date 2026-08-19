import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.context_sweep import evaluate_context_policy, run_context_sweep


class ContextSweepTests(unittest.TestCase):
    def _frames(self):
        return pd.DataFrame({
            "wav_file": ["a.wav"] * 5,
            "frame": range(5),
            "frame_time_seconds": [0.0, .03, .06, .09, .12],
            "speech_probability": [.8, .1, .1, .1, .1],
            "temporal_v1_raw_is_whisper": [False, True, True, True, True],
            "confirmation_requirement": [2] * 5,
            "annotation_label": ["normal_speech"] * 5,
            "annotation_start_seconds": [0.] * 5,
            "annotation_end_seconds": [.15] * 5,
            "annotation_notes": [""] * 5,
            "annotation_speaker_id": ["speaker_01"] * 5,
        })

    def test_context_penalty_increases_requirement_without_veto(self):
        result = evaluate_context_policy(self._frames(), .6, .1, 4)
        self.assertEqual(result.effective_confirmation_requirement.tolist(), [4] * 5)
        self.assertEqual(result.live_candidate_run.tolist(), [0, 1, 2, 3, 4])
        self.assertTrue(result.base_threshold_crossing.iloc[2])
        self.assertTrue(result.policy_threshold_crossing.iloc[4])
        self.assertTrue(result.policy_above_requirement.iloc[4])

    def test_live_state_continues_while_segment_local_state_resets(self):
        frames = self._frames().iloc[1:].copy().reset_index(drop=True)
        frames["frame_time_seconds"] = [.03, .06, .09, .12]
        frames["speech_probability"] = 0.0
        frames["confirmation_requirement"] = 3
        frames["annotation_start_seconds"] = [.03, .03, .09, .09]
        frames["annotation_end_seconds"] = [.09, .09, .15, .15]
        result = evaluate_context_policy(frames, .6, .3, 36)
        self.assertTrue(result.policy_threshold_crossing.iloc[2])
        self.assertTrue(result.cross_boundary_continuation.iloc[2])
        self.assertFalse(result.segment_local_above_requirement.iloc[2])

    def test_requested_grid_and_scope_rows_are_emitted(self):
        report = run_context_sweep(self._frames())
        policies = report.policy_id.drop_duplicates()
        self.assertEqual(len(policies), 27)
        self.assertIn("direct_microphone_normal_speech", set(report.scope))
        self.assertEqual(len(report[report.row_type == "known_paula_passage"]), 54)

    def test_non_verbal_note_is_reported_even_when_label_is_silence(self):
        frames = self._frames()
        frames["annotation_label"] = "silence"
        frames["annotation_notes"] = "non_verbal_vocalisation"
        report = run_context_sweep(frames)
        row = report[(report.row_type == "scope_summary") & (report.scope == "non_verbal_background")].iloc[0]
        self.assertEqual(int(row.segment_count), 1)


if __name__ == "__main__":
    unittest.main()
