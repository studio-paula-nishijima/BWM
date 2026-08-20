import tempfile
import unittest
import wave
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.asr_evaluation import ASRResult, crop_audio, evaluate, normalize_text, read_wav, word_error_counts, write_outputs


class FakeASR:
    name, model = "fake", "unit"
    def __init__(self, text="hello river"): self.text, self.calls = text, []
    def transcribe(self, audio, *, output_mode, language=None):
        self.calls.append((audio, output_mode, language))
        if output_mode == "unsupported": raise ValueError("unsupported")
        return ASRResult(self.text, language or "en", .9, [{"start": 0, "end": audio.duration_seconds, "text": self.text}])


class ASREvaluationTests(unittest.TestCase):
    def wav(self, directory, name="a.wav", rate=16000, frames=16000):
        path = Path(directory) / name
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
            output.writeframes(np.arange(frames, dtype="<i2").tobytes())
        return path

    def annotation(self, directory, text):
        path = Path(directory) / "a.csv"; path.write_text(text); return path

    def test_read_and_crop_preserve_16k_mono_and_sample_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = read_wav(self.wav(directory)); clipped = crop_audio(audio, .1, .25)
            self.assertEqual(audio.sample_rate, 16000); self.assertEqual(len(audio.samples), 16000)
            self.assertEqual(len(clipped.samples), 2400); self.assertAlmostEqual(clipped.start_seconds, .1)

    def test_annotated_spans_are_independent_and_metadata_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = self.wav(directory); annotations = self.annotation(directory, "start_seconds,end_seconds,label,utterance_id,language,transcription,speaker_id,session_id\n0,.2,whisper,q1,en,hello river,s1,x\n.4,.6,whisper,q2,de,hallo fluss,s2,x\n")
            fake = FakeASR(); rows, _ = evaluate(fake, input_mode="annotated_span", wav_path=wav, annotation_path=annotations)
            self.assertEqual(len(rows), 2); self.assertEqual(rows.utterance_id.tolist(), ["q1", "q2"])
            self.assertEqual(rows.speaker_id.tolist(), ["s1", "s2"]); self.assertEqual([call[0].duration_seconds for call in fake.calls], [.2, .2])

    def test_whole_wav_is_distinct_and_no_annotation_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = self.wav(directory); rows, whole = evaluate(FakeASR(), input_mode="whole_wav", wav_path=wav)
            self.assertEqual(rows.input_mode.iloc[0], "whole_wav"); self.assertEqual(len(whole), 1); self.assertEqual(rows.ground_truth_transcription.iloc[0], "")

    def test_capture_metadata_mapping_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = self.wav(directory, "clip.wav"); metadata = Path(directory) / "captures.csv"
            metadata.write_text("capture_wav,capture_id,source_wav,matched_utterance_id,detector_profile,capture_policy,language,transcription\nclip.wav,c7,source.wav,q7,temporal_v2_context,fixed_12s,it,ciao fiume\n")
            rows, _ = evaluate(FakeASR("ciao fiume"), input_mode="captured_clip", capture_output=directory)
            row = rows.iloc[0]; self.assertEqual(row.capture_id, "c7"); self.assertEqual(row.utterance_id, "q7"); self.assertEqual(row.detector_profile, "temporal_v2_context")

    def test_metrics_normalization_empty_and_failures(self):
        self.assertEqual(normalize_text(" Héllo,   RIVER! "), "héllo river")
        metrics = word_error_counts("hello river", "hello")
        self.assertEqual(metrics["deletions"], 1); self.assertEqual(metrics["word_recall"], .5)
        self.assertTrue(word_error_counts("", "")["exact_match"])
        with tempfile.TemporaryDirectory() as directory:
            rows, _ = evaluate(FakeASR(""), input_mode="whole_wav", wav_path=self.wav(directory))
            self.assertEqual(rows.status.iloc[0], "ok"); self.assertEqual(rows.recognized_text_raw.iloc[0], "")

    def test_unsupported_mode_is_clear_and_inference_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            wav = self.wav(directory)
            with self.assertRaisesRegex(ValueError, "Unsupported ASR output mode"):
                evaluate(FakeASR(), input_mode="whole_wav", wav_path=wav, output_mode="unsupported")
            class FailingASR(FakeASR):
                def transcribe(self, *args, **kwargs): raise RuntimeError("model unavailable")
            rows, _ = evaluate(FailingASR(), input_mode="whole_wav", wav_path=wav)
            self.assertEqual(rows.status.iloc[0], "inference_failed")
            self.assertIn("model unavailable", rows.error.iloc[0])

    def test_tagged_outputs_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            rows, whole = evaluate(FakeASR(), input_mode="whole_wav", wav_path=self.wav(directory))
            first, second = write_outputs(rows, whole, directory, "same"), write_outputs(rows, whole, directory, "same")
            self.assertNotEqual(first, second); self.assertTrue((first / "asr_utterances.csv").exists())


if __name__ == "__main__": unittest.main()
