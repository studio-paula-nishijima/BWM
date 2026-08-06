#!/usr/bin/env python3
"""Run offline Stage 3J analysis for one or many WAV/log/annotation triplets."""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.labelled_wav import analyse_triplets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triplet", action="append", default=[], metavar="WAV,LOG,ANNOTATIONS",
                        help="repeat for each recording")
    parser.add_argument("--manifest", help="CSV with wav_file,log_file,annotation_file columns")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frame-seconds", type=float, default=0.03)
    parser.add_argument("--weighting", choices=("frame", "segment"), default="frame")
    parser.add_argument("--full-pipeline", action="store_true", help="include bypassed whisper frames in whisper evaluation")
    parser.add_argument("--reject-overlaps", action="store_true")
    args = parser.parse_args()
    triplets = []
    for item in args.triplet:
        fields = item.split(",", 2)
        if len(fields) != 3: parser.error("--triplet must be WAV,LOG,ANNOTATIONS")
        triplets.append(tuple(fields))
    if args.manifest:
        with open(args.manifest, newline="") as source:
            for row in csv.DictReader(source):
                triplets.append((row["wav_file"], row["log_file"], row["annotation_file"]))
    if not triplets: parser.error("provide at least one --triplet or --manifest")
    results = analyse_triplets(triplets, args.output_dir, args.frame_seconds, args.weighting,
                               args.full_pipeline, args.reject_overlaps)
    for name, table in results.items(): print(f"{name}: {len(table)} rows")


if __name__ == "__main__":
    main()
