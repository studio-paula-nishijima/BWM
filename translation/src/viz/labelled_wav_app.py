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


st.set_page_config(layout="wide", page_title="Labelled WAV analysis")
st.title("Stage 3J: Labelled WAV detector analysis")
st.caption("Frame-weighted results treat correlated 30 ms frames as individual observations. Use segment weighting when each annotated interval should have equal influence.")
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
for column, title in (("speech_probability", "speech probability"), ("whisper_probability", "whisper probability"), ("raw_score", "whisper score")):
    if column in view: fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column], name=title, yaxis="y2"))
for column, title in (("is_speech", "speech decision"), ("speech_gate_open", "gate open"), ("whisper_processed", "whisper processed"), ("is_whisper", "whisper decision"), ("trigger", "trigger")):
    if column in view: fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column].astype(str).str.lower().eq("true").astype(int), name=title, mode="markers"))
fig.update_layout(xaxis_range=[start, finish], yaxis2=dict(overlaying="y", side="right"), height=600)
st.plotly_chart(fig, use_container_width=True)
features = feature_columns(view)
visible = st.multiselect("Feature traces", features, default=features[:3])
if visible:
    feature_fig = go.Figure()
    for column in visible: feature_fig.add_trace(go.Scatter(x=view.frame_time_seconds, y=view[column], name=column))
    # Keep this panel aligned with the decision panel above: both now use the
    # same explicit zoom range instead of Plotly independently padding data.
    feature_fig.update_layout(xaxis_range=[start, finish])
    st.plotly_chart(feature_fig, use_container_width=True)
st.subheader("Annotations in view")
columns = [c for c in ["annotation_label", "annotation_start_seconds", "annotation_end_seconds", *[f"annotation_{x}" for x in OPTIONAL_COLUMNS]] if c in view]
st.dataframe(view[columns].drop_duplicates(), use_container_width=True)
