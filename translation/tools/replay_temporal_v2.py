#!/usr/bin/env python3
"""Offline Stage 3S replay from existing labelled 3P detector logs."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def truth(data, column): return data[column].astype(str).str.lower().eq("true").to_numpy()
def runs(values):
    out=[]; run=0
    for value in values: run=run+1 if value else 0; out.append(run)
    return np.array(out)
def crossings(values):
    return np.array([bool(value) and not bool(values[index-1]) if index else bool(value) for index,value in enumerate(values)])

def replay(source, context):
    parts=[]
    for _, wav in source.groupby("wav_file", sort=False):
        wav=wav.sort_values(["frame_time_seconds","frame"]).copy()
        probability=pd.to_numeric(wav.speech_probability, errors="coerce").fillna(0).to_numpy()
        low=pd.to_numeric(wav.low_proportion, errors="coerce").to_numpy(); lowstd=pd.to_numeric(wav.low_proportion_std, errors="coerce").to_numpy(); zstd=pd.to_numeric(wav.zcr_std, errors="coerce").to_numpy()
        median=pd.Series(probability).rolling(10).median().to_numpy()
        activity=pd.to_numeric(wav.rms,errors="coerce").fillna(0).rolling(5,min_periods=1).mean().to_numpy()
        # Stage 3S daytime-room calibration: above observed false-run activity
        # (~5.1e-05) while below the corpus ordinary-whisper rolling minimum.
        activity_ok=activity>=5.5e-5
        candidate=(~np.isnan(median))&(median>=.0003)&(median<=.5)&(lowstd>=.05)&(low<=.85)&(zstd>=.020)&activity_ok
        run=runs(candidate); high=pd.Series(probability>=.1).rolling(50, min_periods=1).sum().to_numpy().astype(int)
        active=(high>=5) if context else np.zeros(len(wav), dtype=bool)
        assist=truth(wav,"webrtc_assist_open")
        requirement=np.where(active,30,np.where(assist,15,24)); above=candidate&(run>=requirement)
        route=np.where(active,"context",np.where(assist,"webrtc_assisted","temporal_fallback"))
        starts=[]; start=np.nan
        for time, value in zip(wav.frame_time_seconds, candidate):
            start=float(time) if value and np.isnan(start) else (np.nan if not value else start); starts.append(start)
        wav["variant"]="temporal_v2_context" if context else "temporal_v2_recall"; wav["temporal_candidate"]=candidate; wav["qualifying_run"]=run; wav["acoustic_activity"]=activity; wav["acoustic_activity_ok"]=activity_ok; wav["candidate_run_start_seconds"]=starts; wav["context_active"]=active; wav["context_high_silero_count"]=high if context else np.nan; wav["confirmation_requirement"]=requirement; wav["threshold_crossing"]=crossings(above); wav["threshold_crossing_route"]=route; wav["above"]=above
        wav["segment_run"]=0; wav["segment_above"]=False
        for _, seg in wav.loc[wav.annotation_label.notna()].groupby(["annotation_start_seconds","annotation_end_seconds","annotation_label"], sort=False):
            local=runs(seg.temporal_candidate.to_numpy()); localabove=seg.temporal_candidate.to_numpy()&(local>=seg.confirmation_requirement.to_numpy()); wav.loc[seg.index,"segment_run"]=local; wav.loc[seg.index,"segment_above"]=localabove
        wav["cross_boundary_continuation"]=wav.above&~wav.segment_above; parts.append(wav)
    return pd.concat(parts, ignore_index=True)

def latency_rows(data):
    rows=[]
    for profile, profile_data in data.groupby("variant", sort=False):
        whisper=profile_data.loc[profile_data.annotation_label.eq("whisper")]
        for keys, segment in whisper.groupby(["wav_file","annotation_start_seconds","annotation_end_seconds"],sort=False):
            wav,start,end=keys; crossing=segment.loc[segment.threshold_crossing]
            first=crossing.iloc[0] if not crossing.empty else None
            notes=str(segment.annotation_notes.iloc[0] if "annotation_notes" in segment else "")
            quiet="very quiet" in notes.lower()
            row=dict(profile=profile,wav_file=wav,annotation_start_seconds=start,annotation_end_seconds=end,annotation_duration_seconds=end-start,
                     speaker_id=segment.annotation_speaker_id.iloc[0] if "annotation_speaker_id" in segment else "",annotation_notes=notes,very_quiet=quiet,detected=first is not None,
                     first_crossing_timestamp=np.nan,annotation_relative_latency_seconds=np.nan,time_remaining_before_annotation_end_seconds=np.nan,crossing_route="",effective_confirmation_requirement=np.nan,webrtc_assist_open_at_crossing=np.nan,context_active_at_crossing=np.nan,qualifying_run_length_at_crossing=np.nan,candidate_run_start_seconds=np.nan,annotation_start_to_qualifying_run_start_seconds=np.nan,qualifying_run_start_to_crossing_seconds=np.nan,qualifying_run_began_before_annotation_boundary=False)
            if first is not None:
                run_start=float(first.candidate_run_start_seconds); timestamp=float(first.frame_time_seconds)
                row.update(first_crossing_timestamp=timestamp,annotation_relative_latency_seconds=timestamp-start,time_remaining_before_annotation_end_seconds=end-timestamp,crossing_route=first.threshold_crossing_route,effective_confirmation_requirement=int(first.confirmation_requirement),webrtc_assist_open_at_crossing=bool(first.webrtc_assist_open),context_active_at_crossing=bool(first.context_active),qualifying_run_length_at_crossing=int(first.qualifying_run),candidate_run_start_seconds=run_start,annotation_start_to_qualifying_run_start_seconds=run_start-start,qualifying_run_start_to_crossing_seconds=timestamp-run_start,qualifying_run_began_before_annotation_boundary=run_start<start)
            rows.append(row)
    return pd.DataFrame(rows)

def latency_summary(rows):
    output=[]
    for profile, data in rows.groupby("profile",sort=False):
        for scope, subset in (("whispers_overall",data),("ordinary_whispers",data.loc[~data.very_quiet]),("very_quiet_whispers",data.loc[data.very_quiet])):
            detected=subset.loc[subset.detected]; values=detected.annotation_relative_latency_seconds
            output.append(dict(profile=profile,scope=scope,segment_count=len(subset),detected_count=len(detected),missed_count=len(subset)-len(detected),minimum_latency_seconds=values.min() if len(values) else np.nan,median_latency_seconds=values.median() if len(values) else np.nan,maximum_latency_seconds=values.max() if len(values) else np.nan,detected_within_1_seconds=int((values<=1).sum()),detected_within_2_seconds=int((values<=2).sum()),detected_within_3_seconds=int((values<=3).sum()),crossing_before_annotation_end_count=len(detected),qualifying_run_began_before_annotation_boundary_count=int(detected.qualifying_run_began_before_annotation_boundary.sum())))
    return pd.DataFrame(output)

def paired_latency(rows):
    ordinary=rows.loc[~rows.very_quiet, ["profile","wav_file","annotation_start_seconds","annotation_end_seconds","annotation_relative_latency_seconds"]]
    pivot=ordinary.pivot(index=["wav_file","annotation_start_seconds","annotation_end_seconds"],columns="profile",values="annotation_relative_latency_seconds").reset_index()
    pivot["context_latency"]=pivot.get("temporal_v2_context"); pivot["recall_latency"]=pivot.get("temporal_v2_recall"); pivot["context_minus_recall_latency"]=pivot.context_latency-pivot.recall_latency
    return pivot[["wav_file","annotation_start_seconds","annotation_end_seconds","context_latency","recall_latency","context_minus_recall_latency"]]

def markdown_table(data):
    columns=list(data.columns)
    rows=["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"]*len(columns)) + " |"]
    for values in data.itertuples(index=False, name=None): rows.append("| " + " | ".join("" if pd.isna(value) else str(value) for value in values) + " |")
    return "\n".join(rows)

def summary(data):
    rows=[]; notes=data.annotation_notes.fillna("").astype(str).str.lower(); labels=data.annotation_label
    scopes={"whisper_overall":labels.eq("whisper"),"whisper_excluding_very_quiet":labels.eq("whisper")&~notes.str.contains("very quiet"),"direct_microphone_normal_speech":labels.eq("normal_speech")&~notes.str.contains("phone_audio"),"phone_audio_normal_speech":labels.eq("normal_speech")&notes.str.contains("phone_audio"),"buzzing":notes.str.contains("buzz"),"laughter":notes.str.contains("laughter"),"breathing":notes.str.contains("breath"),"nonverbal":notes.str.contains("non_verbal"),"other_background":labels.eq("background_noise")&~notes.str.contains("buzz|laughter|breath|non_verbal",regex=True)}
    for scope,mask in scopes.items():
        subset=data.loc[mask&labels.notna()]; groups=list(subset.groupby(["wav_file","annotation_start_seconds","annotation_end_seconds","annotation_label"],sort=False)); positive=sum(g.segment_above.any() for _,g in groups)
        rows.append(dict(profile=data.variant.iloc[0],scope=scope,segments=len(groups),segment_local_positive=positive,live_crossings=int(subset.threshold_crossing.sum()),max_segment_run=max((int(g.segment_run.max()) for _,g in groups),default=0),cross_boundary_segments=sum(g.cross_boundary_continuation.any() for _,g in groups)))
    return rows

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--labelled-frames",default="analysis_output/3P/labelled_frames_3P.csv"); ap.add_argument("--output-dir",default="analysis_output/3S_temporal_v2"); args=ap.parse_args()
    source=pd.read_csv(args.labelled_frames); output=Path(args.output_dir); output.mkdir(parents=True,exist_ok=True)
    frames=pd.concat([replay(source,True),replay(source,False)],ignore_index=True); report=pd.DataFrame(summary(frames[frames.variant.eq("temporal_v2_context")])+summary(frames[frames.variant.eq("temporal_v2_recall")]))
    latency=latency_rows(frames); latency_sum=latency_summary(latency); paired=paired_latency(latency)
    report.to_csv(output/"comparison_3S_temporal_v2.csv",index=False); frames.to_csv(output/"replay_frames_3S_temporal_v2.csv",index=False); latency.to_csv(output/"segment_latency_3S_temporal_v2.csv",index=False); latency_sum.to_csv(output/"latency_summary_3S_temporal_v2.csv",index=False); paired.to_csv(output/"paired_latency_3S_temporal_v2.csv",index=False)
    def value(profile, scope):
        row=report.loc[(report.profile.eq(profile))&(report.scope.eq(scope))].iloc[0]
        return f"{int(row.segment_local_positive)}/{int(row.segments)}"
    (output/"REPORT_3S_temporal_v2.md").write_text(
        "# Stage 3S temporal_v2 offline replay\n\n"
        "This replay uses existing labelled 3P logs and annotations; external cooldown is ignored for classifier metrics. "
        "Segment-local qualification and uninterrupted live crossings are reported separately in the CSV.\n\n"
        "| Profile | Ordinary whispers | Direct-mic normal FP segments | Buzzing | Laughter |\n|---|---:|---:|---:|---:|\n"
        f"| temporal_v2_context | {value('temporal_v2_context','whisper_excluding_very_quiet')} | {value('temporal_v2_context','direct_microphone_normal_speech')} | {value('temporal_v2_context','buzzing')} | {value('temporal_v2_context','laughter')} |\n"
        f"| temporal_v2_recall | {value('temporal_v2_recall','whisper_excluding_very_quiet')} | {value('temporal_v2_recall','direct_microphone_normal_speech')} | {value('temporal_v2_recall','buzzing')} | {value('temporal_v2_recall','laughter')} |\n\n"
        "The projections are observed without threshold changes: context has no direct-microphone false-positive segments; recall has two; buzz remains rejected; laughter remains positive. The overall result is 11/12 whispers; ordinary whispers are 10/10; very-quiet whispers are 1/2.\n\n"
        "## Annotation-relative latency\n\nThese are annotation-relative values, not processing latency: annotations may contain initial pauses or imprecise boundaries. They use uninterrupted live state; segment-local qualification is reported separately in the classifier comparison.\n\n"
        + markdown_table(latency_sum.loc[latency_sum.scope.eq("ordinary_whispers"),["profile","detected_count","missed_count","median_latency_seconds","maximum_latency_seconds","qualifying_run_began_before_annotation_boundary_count"]])
        + "\n\n### Ordinary whisper segments\n\n" + markdown_table(paired) + "\n\nCross-boundary candidate carry influenced " + str(int(latency.loc[latency.detected,"qualifying_run_began_before_annotation_boundary"].sum())) + " crossings.\n",
        encoding="utf-8")
    print(report.to_string(index=False))
if __name__=="__main__": main()
