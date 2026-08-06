"""Stage 3I observability tests for detector routing, CSV rows, and counters."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from app_logging.csv_logger import WhisperCSVLogger
from whisper.models import SpeechDetectionResult, WhisperDetectionResult
from whisper.pipeline import DetectorPipeline


class RecordingWhisperDetector:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def classify(self, _frame):
        self.calls += 1
        return WhisperDetectionResult(
            is_whisper=next(self.values),
            whisper_probability=0.0,
        )


class RecordingSpeechDetector:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def classify(self, _frame):
        self.calls += 1
        return SpeechDetectionResult(is_speech=next(self.values), speech_probability=0.0)


class PipelineObservabilityTests(unittest.TestCase):
    frame = np.zeros(480, dtype=np.float32)

    def test_direct_always_processes_whisper_without_a_fabricated_speech_result(self):
        whisper = RecordingWhisperDetector([False])
        result = DetectorPipeline(whisper, mode="direct").process(self.frame)

        self.assertEqual(whisper.calls, 1)
        self.assertIsNone(result.speech)
        self.assertTrue(result.speech_gate_open)
        self.assertTrue(result.whisper_processed)

    def test_closed_speech_gate_marks_neutral_whisper_result_as_unprocessed(self):
        whisper = RecordingWhisperDetector([True])
        result = DetectorPipeline(
            whisper, RecordingSpeechDetector([False]), mode="speech_gate"
        ).process(self.frame)

        self.assertEqual(whisper.calls, 0)
        self.assertFalse(result.speech_gate_open)
        self.assertFalse(result.whisper_processed)
        self.assertFalse(result.whisper.is_whisper)
        self.assertEqual(result.whisper.whisper_probability, 0.0)

    def test_open_speech_gate_processes_whisper(self):
        whisper = RecordingWhisperDetector([True])
        result = DetectorPipeline(
            whisper, RecordingSpeechDetector([True]), mode="speech_gate"
        ).process(self.frame)

        self.assertTrue(result.speech_gate_open)
        self.assertTrue(result.whisper_processed)
        self.assertTrue(result.whisper.is_whisper)
        self.assertEqual(whisper.calls, 1)

    def test_shadow_always_processes_whisper_and_collects_disagreements(self):
        pipeline = DetectorPipeline(
            RecordingWhisperDetector([True, False, True, False]),
            RecordingSpeechDetector([False, True, True, False]),
            mode="shadow",
        )
        results = [pipeline.process(self.frame) for _ in range(4)]

        self.assertTrue(all(result.whisper_processed for result in results))
        self.assertTrue(all(result.speech_gate_open for result in results))
        summary = pipeline.summary()
        self.assertEqual(summary["speech_false_whisper_true"], 1)
        self.assertEqual(summary["speech_true_whisper_false"], 1)
        self.assertEqual(summary["speech_true_whisper_true"], 1)
        self.assertEqual(summary["speech_false_whisper_false"], 1)

    def test_csv_fields_and_summary_counters_are_consistent(self):
        pipeline = DetectorPipeline(
            RecordingWhisperDetector([True]),
            RecordingSpeechDetector([False, True]),
            mode="speech_gate",
        )
        bypassed = pipeline.process(self.frame)
        processed = pipeline.process(self.frame)
        pipeline.record_trigger()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.csv"
            logger = WhisperCSVLogger(
                path,
                processing_mode="speech_gate",
                speech_detector_implementation="silero",
            )
            logger.log(1, bypassed, False)
            logger.log(2, processed, True)
            logger.close()
            with path.open(newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(rows[0]["processing_mode"], "speech_gate")
        self.assertEqual(rows[0]["speech_detector_implementation"], "silero")
        self.assertEqual(rows[0]["speech_gate_open"], "False")
        self.assertEqual(rows[0]["whisper_processed"], "False")
        self.assertEqual(rows[1]["speech_gate_open"], "True")
        self.assertEqual(rows[1]["whisper_processed"], "True")
        self.assertEqual(rows[0]["whisper_probability"], "0.0")

        self.assertEqual(
            pipeline.summary(),
            {
                "total_frames": 2,
                "speech_positive_frames": 1,
                "whisper_processed_frames": 1,
                "gated_bypassed_frames": 1,
                "whisper_positive_frames": 1,
                "trigger_count": 1,
                "speech_false_whisper_true": 0,
                "speech_true_whisper_false": 0,
                "speech_true_whisper_true": 0,
                "speech_false_whisper_false": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
