"""Streamlit viewer for Stage 3J's derived labelled-frame CSV."""
import sys
import wave
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.labelled_wav import OPTIONAL_COLUMNS, feature_columns


def _waveform(path):
    with wave.open(str(path), "rb") as source:
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16)
        if source.getnchannels() > 1: samples = samples.reshape(-1, source.getnchannels()).mean(axis=1)
        return np.linspace(0, len(samples) / source.getframerate(), len(samples)), samples


DISPLAY_NAMES = {
    "speech_gate_open": "Primary speech processing gate",
    "webrtc_assist_open": "WebRTC assist state",
    "comparison_speech_is_speech": "WebRTC VAD result",
    "is_whisper": "Classifier whisper decision",
    "low_proportion": "Current-frame low-band proportion",
    "temporal_v1_low_proportion_max": "Low-band maximum threshold",
    "temporal_v1_low_proportion_max_pass": "Low-band maximum passes",
    "temporal_v1_window_full": "Temporal window full",
    "temporal_v1_silero_min_pass": "Silero minimum passes",
    "temporal_v1_silero_max_pass": "Silero maximum passes",
    "temporal_v1_low_proportion_std_pass": "Low-band variation passes",
    "temporal_v1_raw_is_whisper": "Temporal classifier evidence",
    "threshold_crossing_route": "Policy confirmation route reached",
    "trigger_route": "Detector trigger emitted via",
    "trigger_suppression_reason": "Detector trigger not emitted: reason",
    "trigger": "Detector emitted trigger",
    "actuation_started": "Servo sequence started",
    "actuation_suppression_reason": "Servo request not started: reason",
}

st.set_page_config(layout="wide", page_title="Detector analysis")
st.title("Labelled WAV detector analysis")
st.caption("Presentation names use the current detector/policy/actuation architecture. Older CSVs remain supported; fields absent from earlier schemas are shown as not recorded.")
frames_path = Path(st.sidebar.text_input("labelled_frames.csv", "labelled_frames.csv"))
if not frames_path.exists():
    st.info("Run tools/analyse_labelled_wavs.py first, then enter its labelled_frames.csv path.")
    st.stop()
frames = pd.read_csv(frames_path)
wav_directory = Path(st.sidebar.text_input("WAV directory", str(frames_path.parent)))
wav_names = st.sidebar.multiselect("WAV files", sorted(frames.wav_file.dropna().unique()), default=sorted(frames.wav_file.dropna().unique()))
for meta in ("strength", "distance", "speaker", "confidence"):
    column = f"annotation_{meta}"
    if column in frames:
        choices = sorted(frames[column].dropna().astype(str).unique())
        picked = st.sidebar.multiselect(meta, choices, default=choices)
        frames = frames[frames[column].isna() | frames[column].astype(str).isin(picked)]
frames = frames[frames.wav_file.isin(wav_names)]
if frames.empty: st.warning("No frames match the filters."); st.stop()
wav_name = st.selectbox("Recording", sorted(frames.wav_file.unique()))
data = frames[frames.wav_file == wav_name].copy()
end = float(data.frame_time_seconds.max())
start, finish = st.slider("Zoom time range (seconds)", 0.0, max(end, 0.01), (0.0, max(end, 0.01)))
view = data[data.frame_time_seconds.between(start, finish)]
fig = go.Figure()
wav_candidate = wav_directory / wav_name
if wav_candidate.exists():
    times, samples = _waveform(wav_candidate); stride = max(1, len(samples) // 10000)
    fig.add_trace(go.Scatter(x=times[::stride], y=samples[::stride], name="waveform", line=dict(color="#999")))
for _, segment in data[["annotation_label", "annotation_start_seconds", "annotation_end_seconds", "annotation_confidence", "annotation_notes"]].dropna(subset=["annotation_label"]).drop_duplicates().iterrows():
    fig.add_vrect(x0=segment.annotation_start_seconds, x1=segment.annotation_end_seconds, opacity=.18,
                  annotation_text=f"{segment.annotation_label}: {segment.get('annotation_notes', '')}")
for column, title in (("speech_probability", "primary speech probability"), ("whisper_probability", "classifier whisper probability"), ("raw_score", "classifier score")):
    if column in view: fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column], name=title, yaxis="y2"))
for column, title in (("comparison_speech_is_speech", DISPLAY_NAMES["comparison_speech_is_speech"]), ("webrtc_assist_open", DISPLAY_NAMES["webrtc_assist_open"]), ("is_whisper", DISPLAY_NAMES["is_whisper"]), ("trigger", DISPLAY_NAMES["trigger"]), ("actuation_started", DISPLAY_NAMES["actuation_started"]), ("is_speech", "primary speech decision"), ("speech_gate_open", DISPLAY_NAMES["speech_gate_open"]), ("whisper_processed", "classifier processed")):
    if column in view: fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column].astype(str).str.lower().eq("true").astype(int), name=title, mode="markers"))
TIMELINE_MARGIN = dict(l=80, r=80, t=40, b=55)
fig.update_layout(xaxis=dict(range=[start, finish], title="Audio time (seconds)"), yaxis2=dict(overlaying="y", side="right"), height=460, margin=TIMELINE_MARGIN)
temporal_columns = ["frame_time_seconds", "low_proportion", "temporal_v1_low_proportion_max", "temporal_v1_low_proportion_max_pass", "temporal_v1_window_full", "temporal_v1_silero_min_pass", "temporal_v1_silero_max_pass", "temporal_v1_low_proportion_std_pass", "temporal_v1_raw_is_whisper"]
temporal_columns = [column for column in temporal_columns if column in view]
low_band_fig = None
if "temporal_v1_low_proportion_max_pass" in view:
    low_band_fig = go.Figure()
    if "low_proportion" in view:
        low_band_fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view.low_proportion, name=DISPLAY_NAMES["low_proportion"]))
    if "temporal_v1_low_proportion_max" in view and view.temporal_v1_low_proportion_max.notna().any():
        threshold = view.temporal_v1_low_proportion_max.dropna().iloc[0]
        low_band_fig.add_hline(y=threshold, line_dash="dash", annotation_text=DISPLAY_NAMES["temporal_v1_low_proportion_max"])
    low_band_fig.update_layout(xaxis=dict(range=[start, finish], title="Audio time (seconds)"), yaxis_title="Proportion", height=460, margin=TIMELINE_MARGIN)
st.subheader("Production decision path")
st.plotly_chart(fig, use_container_width=True)
st.subheader("Temporal candidate")
if low_band_fig:
    st.plotly_chart(low_band_fig, use_container_width=True)
elif "temporal_v1_raw_is_whisper" in view:
    st.info("This legacy CSV predates the current-frame low-band maximum; the condition was not recorded.")
features = feature_columns(view)
st.subheader("Feature traces")
visible = st.multiselect("Feature traces", features, default=features[:3])
if visible:
    feature_fig = go.Figure()
    for column in visible: feature_fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column], name=DISPLAY_NAMES.get(column, column)))
    feature_fig.update_layout(xaxis=dict(range=[start, finish], title="Audio time (seconds)"), height=460, margin=TIMELINE_MARGIN)
    st.plotly_chart(feature_fig, use_container_width=True)
if low_band_fig:
    st.dataframe(view[temporal_columns].rename(columns=DISPLAY_NAMES), use_container_width=True)
st.subheader("Detector, policy, and actuation events")
event_columns = ["frame_time_seconds", "threshold_crossing_route", "trigger_route", "trigger_suppression_reason", "actuation_requested", "actuation_started", "actuation_suppression_reason"]
event_columns = [column for column in event_columns if column in view]
if event_columns:
    events = view[event_columns].dropna(how="all", subset=[column for column in event_columns if column != "frame_time_seconds"])
    st.dataframe(events.rename(columns=DISPLAY_NAMES), use_container_width=True)
else:
    st.info("This legacy CSV does not record policy-route or actuation events.")
st.subheader("Annotations in view")
columns = [c for c in ["annotation_label", "annotation_start_seconds", "annotation_end_seconds", *[f"annotation_{x}" for x in OPTIONAL_COLUMNS]] if c in view]
st.dataframe(view[columns].drop_duplicates(), use_container_width=True)
