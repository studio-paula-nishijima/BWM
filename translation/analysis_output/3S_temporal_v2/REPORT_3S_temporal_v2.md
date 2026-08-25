# Stage 3S temporal_v2 offline replay

This replay uses existing labelled 3P logs and annotations; external cooldown is ignored for classifier metrics. Segment-local qualification and uninterrupted live crossings are reported separately in the CSV.

| Profile | Ordinary whispers | Direct-mic normal FP segments | Buzzing | Laughter |
|---|---:|---:|---:|---:|
| temporal_v2_context | 10/10 | 0/19 | 0/6 | 1/2 |
| temporal_v2_recall | 10/10 | 2/19 | 0/6 | 1/2 |

The projections are observed without threshold changes: context has no direct-microphone false-positive segments; recall has two; buzz remains rejected; laughter remains positive. The overall result is 11/12 whispers; ordinary whispers are 10/10; very-quiet whispers are 1/2.

## Annotation-relative latency

These are annotation-relative values, not processing latency: annotations may contain initial pauses or imprecise boundaries. They use uninterrupted live state; segment-local qualification is reported separately in the classifier comparison.

| profile | detected_count | missed_count | median_latency_seconds | maximum_latency_seconds | qualifying_run_began_before_annotation_boundary_count |
| --- | --- | --- | --- | --- | --- |
| temporal_v2_context | 10 | 0 | 2.0700000000000003 | 3.0200000000000005 | 1 |
| temporal_v2_recall | 10 | 0 | 1.9800000000000002 | 3.0200000000000005 | 1 |

### Ordinary whisper segments

| wav_file | annotation_start_seconds | annotation_end_seconds | context_latency | recall_latency | context_minus_recall_latency |
| --- | --- | --- | --- | --- | --- |
| 2_speak_whisper.wav | 5.16 | 8.71 | 0.54 | 0.3899999999999997 | 0.15000000000000036 |
| 2_whisper.wav | 1.87 | 10.0 | 1.94 | 1.94 | 0.0 |
| 2_whisper2.wav | 2.38 | 10.0 | 3.0200000000000005 | 3.0200000000000005 | 0.0 |
| 4_kaspar_whisper_1m_5.wav | 1.57 | 6.52 | 2.12 | 2.12 | 0.0 |
| 4_kaspar_whisper_50cm_6.wav | 2.59 | 9.38 | 2.2699999999999996 | 2.2699999999999996 | 0.0 |
| 4_kaspar_whisper_soln_50cm_9.wav | 1.7 | 8.09 | 2.0200000000000005 | 2.0200000000000005 | 0.0 |
| silent_whisper.wav | 5.0 | 10.0 | 2.6799999999999997 | 0.9100000000000001 | 1.7699999999999996 |
| silent_whisper_speak.wav | 2.8 | 5.5 | 0.8300000000000001 | 0.8300000000000001 | 0.0 |
| whispered_question.wav | 2.0 | 5.34 | 0.9100000000000001 | 0.45999999999999996 | 0.4500000000000002 |
| whispered_question2.wav | 2.08 | 8.68 | 2.4799999999999995 | 2.4799999999999995 | 0.0 |

Cross-boundary candidate carry influenced 2 crossings.
