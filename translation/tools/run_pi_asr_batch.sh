#!/usr/bin/env bash
# Run cooled, isolated Pi ASR comparisons across annotated speech/whisper WAVs.
# The script does not start or stop voice_rack_test; set LOAD_LABEL to record
# whether the caller has already started that workload.
set -Eeuo pipefail

ROOT="${BWM_TRANSLATION_ROOT:-/home/raspi/BWM/translation}"
PY="${ASR_PYTHON:-$ROOT/whisper_venv/bin/python}"
WAV_ROOT="${ASR_WAV_ROOT:-$ROOT/test_files/test_wavs}"
OUT_ROOT="${ASR_OUTPUT_ROOT:-$ROOT/analysis_output}"
# This is a between-run resume target, not an in-run limit.  A benchmark that
# crosses 80C completes normally and records the Pi's throttling state; the
# next run waits only until the Pi has fallen back to this practical target.
COOL_TARGET_C="${COOL_TARGET_C:-78}"
MAX_COOL_SECONDS="${MAX_COOL_SECONDS:-3600}"
INCLUDE_SMALL="${INCLUDE_SMALL:-0}"
LOAD_LABEL="${LOAD_LABEL:-clean}"

mkdir -p "$OUT_ROOT"
LOG="$OUT_ROOT/pi_asr_batch_${LOAD_LABEL}_$(date +%Y%m%d_%H%M%S).log"

temperature_c() {
  awk '{ printf "%.1f", $1 / 1000 }' /sys/class/thermal/thermal_zone0/temp
}

wait_for_cool() {
  local started=$SECONDS
  while true; do
    local temperature
    temperature="$(temperature_c)"
    if awk -v current="$temperature" -v target="$COOL_TARGET_C" \
      'BEGIN { exit !(current <= target) }'; then
      echo "Temperature ${temperature}C: starting next run." | tee -a "$LOG"
      return 0
    fi
    if (( SECONDS - started >= MAX_COOL_SECONDS )); then
      echo "Cooling timeout at ${temperature}C; stopping batch." | tee -a "$LOG"
      return 1
    fi
    echo "Temperature ${temperature}C > ${COOL_TARGET_C}C; cooling for 60 s." | tee -a "$LOG"
    sleep 60
  done
}

has_speech_or_whisper() {
  grep -Eq ',(whisper|normal_speech)(,|$)' "$1"
}

run_one() {
  local wav="$1" annotation="$2" model="$3" threads="$4"
  local stem tag
  stem="$(basename "${wav%.wav}")"
  tag="pi_${LOAD_LABEL}_${stem}_${model}_${threads}t_$(date +%Y%m%d_%H%M%S)"
  wait_for_cool
  echo "=== ${stem} | ${model} | ${threads} thread(s) ===" | tee -a "$LOG"
  vcgencmd measure_temp 2>&1 | tee -a "$LOG" || true
  vcgencmd get_throttled 2>&1 | tee -a "$LOG" || true
  "$PY" "$ROOT/tools/benchmark_asr_pi.py" \
    --wav "$wav" --annotations "$annotation" \
    --models "$model" --threads "$threads" \
    --output-dir "$OUT_ROOT" --tag "$tag" 2>&1 | tee -a "$LOG"
}

index=0
shopt -s nullglob
for annotation in "$WAV_ROOT"/annotations/*.csv; do
  stem="$(basename "${annotation%.csv}")"
  wav="$WAV_ROOT/${stem}.wav"
  [[ -f "$wav" ]] || continue
  has_speech_or_whisper "$annotation" || continue

  # Rotate tiny/base order between recordings to limit systematic heat bias.
  if (( index % 2 )); then
    models=(base tiny)
  else
    models=(tiny base)
  fi
  if [[ "$INCLUDE_SMALL" == "1" ]]; then models+=(small); fi

  for model in "${models[@]}"; do
    for threads in 1 2; do
      if ! run_one "$wav" "$annotation" "$model" "$threads"; then
        echo "Batch stopped; see $LOG" >&2
        exit 1
      fi
    done
  done
  ((index += 1))
done

echo "Batch complete: $LOG"
