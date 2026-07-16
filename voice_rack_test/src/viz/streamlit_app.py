import sys
from pathlib import Path

sys.path.append(
    str(
        Path(__file__).resolve().parents[1]
    )
)

import numpy as np
import streamlit as st
import plotly.graph_objects as go

from diagnostics.density import (
    compute_event_density,
    burst_statistics
)


events = np.load(
    "events.npy",
    allow_pickle=True
)

events = list(events)

st.title("Water Whisper Diagnostics")


# ---------------------------------------------------
# Historical timeline
# ---------------------------------------------------

times = np.array([
    e["timestamp"]
    for e in events
])

channels = [
    e["target"]
    for e in events
]

fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=times,
        y=channels,
        mode="markers",
        name="Actuations"
    )
)

fig.update_layout(
    title="Historical Actuation Timeline",
    xaxis_title="Historical Date",
    yaxis_title="Channel"
)

st.plotly_chart(
    fig,
    use_container_width=True
)


# ---------------------------------------------------
# Playback density
# ---------------------------------------------------

window = st.slider(
    "Density Window (s)",
    1.0,
    60.0,
    10.0
)

bins, density = compute_event_density(
    events,
    window=window
)

fig2 = go.Figure()

fig2.add_trace(
    go.Scatter(
        x=bins,
        y=density,
        mode="lines",
        name="Density"
    )
)

fig2.update_layout(
    title="Playback Event Density",
    xaxis_title="Playback Time (s)",
    yaxis_title="Events/sec"
)

st.plotly_chart(
    fig2,
    use_container_width=True
)

st.subheader("Burst Statistics")

stats = burst_statistics(events)

st.json(stats)
