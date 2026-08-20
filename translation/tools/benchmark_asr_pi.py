#!/usr/bin/env python3
"""Pi-oriented ASR benchmark; run while the normal BWM stack is active."""
from __future__ import annotations
import argparse, csv, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from analysis.asr_evaluation import FasterWhisperBackend, evaluate

def system_snapshot():
    value = {"cpu_percent": None, "rss_bytes": None, "available_ram_bytes": None, "swap_free_bytes": None, "temperature_c": None, "throttled": None}
    try:
        import os, psutil
        process, memory, swap = psutil.Process(os.getpid()), psutil.virtual_memory(), psutil.swap_memory()
        value.update(cpu_percent=psutil.cpu_percent(interval=None), rss_bytes=process.memory_info().rss, available_ram_bytes=memory.available, swap_free_bytes=swap.free)
    except ImportError: pass
    try:
        value["temperature_c"] = float(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000
    except (OSError, ValueError): pass
    try: value["throttled"] = subprocess.check_output(["vcgencmd", "get_throttled"], text=True).strip()
    except (OSError, subprocess.SubprocessError): pass
    return value

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True); parser.add_argument("--annotations", required=True)
    parser.add_argument("--models", nargs="+", default=["base", "tiny", "small"]); parser.add_argument("--threads", nargs="+", type=int, default=[1, 2, 3, 4])
    parser.add_argument("--output-dir", type=Path, default=Path("analysis_output")); parser.add_argument("--tag", default=time.strftime("pi_asr_%Y%m%d_%H%M%S"))
    args = parser.parse_args(); destination = args.output_dir / args.tag; suffix = 1
    while destination.exists(): destination = args.output_dir / f"{args.tag}_{suffix}"; suffix += 1
    destination.mkdir(parents=True); rows = []
    for model in args.models:
        for threads in args.threads:
            before = system_snapshot(); backend = FasterWhisperBackend(model, "cpu", "int8", threads)
            result, _ = evaluate(backend, input_mode="annotated_span", wav_path=args.wav, annotation_path=args.annotations)
            after = system_snapshot()
            for item in result.to_dict("records"): rows.append({"model": model, "threads": threads, **before, **{f"after_{k}": v for k, v in after.items()}, **item})
    with (destination / "asr_pi_benchmark.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row})); writer.writeheader(); writer.writerows(rows)
    print(destination)
if __name__ == "__main__": main()
