#!/usr/bin/env python3
"""Evaluate normal-speech context policies from an existing labelled-frame CSV."""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.context_sweep import run_context_sweep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labelled-frames", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--analysis-tag", default="3Q_context_sweep")
    args = parser.parse_args()
    frames = pd.read_csv(args.labelled_frames)
    report = run_context_sweep(frames)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"context_sweep_{args.analysis_tag}.csv"
    report.to_csv(path, index=False)
    print(f"context sweep rows: {len(report)}")
    print(f"wrote: {path}")


if __name__ == "__main__":
    main()
