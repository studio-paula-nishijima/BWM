import importlib.util
import unittest
from pathlib import Path
import pandas as pd

spec=importlib.util.spec_from_file_location("replay",Path(__file__).resolve().parents[1]/"tools"/"replay_temporal_v2.py")
replay=importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)

def frames(profile="temporal_v2_context", crossings=(1.0,), start=.0, end=2.):
    values=[]
    for time in (0.,1.,2.):
        values.append(dict(variant=profile,wav_file="x.wav",annotation_label="whisper" if time<end else None,annotation_start_seconds=start,annotation_end_seconds=end,annotation_speaker_id="s",annotation_notes="",frame_time_seconds=time,threshold_crossing=time in crossings,threshold_crossing_route="fallback",confirmation_requirement=24,webrtc_assist_open=False,context_active=False,qualifying_run=24,candidate_run_start_seconds=-.1))
    return pd.DataFrame(values)

class LatencyTests(unittest.TestCase):
    def test_first_crossing_start_end_and_miss(self):
        rows=replay.latency_rows(frames(crossings=(0.,1.)))
        self.assertEqual(rows.first_crossing_timestamp.iloc[0],0.)
        self.assertEqual(rows.annotation_relative_latency_seconds.iloc[0],0.)
        self.assertTrue(pd.isna(replay.latency_rows(frames(crossings=(2.,))).annotation_relative_latency_seconds.iloc[0]))

    def test_carry_and_scope_medians(self):
        data=pd.concat([frames(crossings=(1.,)),frames("temporal_v2_recall",crossings=())],ignore_index=True)
        rows=replay.latency_rows(data); summary=replay.latency_summary(rows)
        self.assertTrue(rows.loc[rows.profile.eq("temporal_v2_context"),"qualifying_run_began_before_annotation_boundary"].iloc[0])
        self.assertEqual(int(summary.loc[summary.scope.eq("ordinary_whispers"),"detected_count"].sum()),1)

    def test_paired_profile_latency(self):
        rows=replay.latency_rows(pd.concat([frames("temporal_v2_context",(1.,)),frames("temporal_v2_recall",(0.,))]))
        paired=replay.paired_latency(rows)
        self.assertEqual(paired.context_minus_recall_latency.iloc[0],1.)


if __name__=="__main__": unittest.main()
