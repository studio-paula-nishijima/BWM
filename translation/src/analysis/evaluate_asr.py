"""Command-line entrypoint for offline Stage 3Q ASR evaluation."""
from __future__ import annotations
import argparse
from .asr_evaluation import FasterWhisperBackend, evaluate, write_outputs

def main():
    parser = argparse.ArgumentParser(description="Evaluate local multilingual ASR on WAV inputs.")
    parser.add_argument("--input-mode", required=True, choices=("whole_wav", "annotated_span", "captured_clip"))
    parser.add_argument("--wav"); parser.add_argument("--annotations")
    parser.add_argument("--capture-output"); parser.add_argument("--capture-metadata")
    parser.add_argument("--asr-output-mode", default="transcribe", choices=("transcribe", "translate_to_english"))
    parser.add_argument("--model", default="small"); parser.add_argument("--device", default="auto"); parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--language", help="Known ISO language code; omit to allow backend detection.")
    parser.add_argument("--output-dir", default="analysis_output"); parser.add_argument("--output-tag")
    args = parser.parse_args()
    backend = FasterWhisperBackend(args.model, args.device, args.compute_type)
    rows, whole_rows = evaluate(backend, input_mode=args.input_mode, wav_path=args.wav, annotation_path=args.annotations,
                                capture_output=args.capture_output, capture_metadata=args.capture_metadata,
                                output_mode=args.asr_output_mode, language=args.language)
    print(write_outputs(rows, whole_rows, args.output_dir, args.output_tag))

if __name__ == "__main__": main()
