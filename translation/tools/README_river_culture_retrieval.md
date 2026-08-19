# River Culture semantic retrieval (Retrieval Stage 5)

This Stage 5 tool embeds Stage 4's derived chunks, not canonical passages.
It uses exact cosine search (normalized float32 embeddings plus a dot product),
which is simpler than an ANN dependency and is ample for 1,622 chunks.

## Pi setup and build

From `/home/raspi/BWM`, after Stage 4 has produced its ignored local JSONL:

```bash
python3.11 -m venv --system-site-packages translation/river_culture_venv
translation/river_culture_venv/bin/python -m pip install -r translation/requirements/requirements_river_culture_retrieval.txt

translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py build \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

The first model use downloads and caches the model locally; later builds and
queries use that cache offline. The generated `.npy` embeddings and JSON index
metadata remain ignored because they derive from copyrighted source text.

## Query and evaluate

```bash
translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py query \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --top-k 8 \
  --text "How does the water feel today?"

translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py evaluate \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --top-k 8 \
  --output files/river_culture/river_culture_evaluation_multilingual_minilm.json
```

Query output preserves raw rank and score, complete chunk wording, chunk IDs,
ordered canonical `passage_ids`, page/chapter provenance, and propagated layout
flags. `grouped_regions` is an optional page-overlap grouping for human review;
it never alters `raw_results`.

## Future ASR/retrieval routes

The retrieval layer accepts query text and is deliberately agnostic about how it
was produced. The English corpus supports two future routes, both retained for
evaluation on the same captured whispered utterances:

1. **Route A:** multilingual ASR directly translates to English, then an
   English embedding model searches the English corpus.
2. **Route B:** multilingual ASR transcribes in the original language, then a
   multilingual embedding model searches the English corpus.

Multilingual embeddings are therefore not mandatory. Select the route by
retrieval quality on real whispered input, especially quiet, incomplete, noisy,
or imperfectly recognized utterances; transcription accuracy is only a
secondary diagnostic. The future ASR output mode and embedding backend must
remain independently configurable. No ASR, translation, or language-specific
routing is implemented in this stage.

The current EN/DE/IT equivalent text set exercises Route B directly. For an
English-backend model, `evaluate` instead sends the matching English question
for every language variant and records it as `retrieval_query`; this is a
controlled Route A proxy, not a claim about ASR translation quality. Later ASR
evaluation must record both outputs for the same source audio before comparing
the routes.

## Model shortlist

The configuration intentionally evaluates a small shortlist:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: compact
   multilingual direct-retrieval baseline for English, German, and Italian.
2. `intfloat/multilingual-e5-small`: multilingual candidate using E5's
   `query:`/`passage:` prefixes; it is expected to cost more memory/storage.
3. `sentence-transformers/all-MiniLM-L6-v2`: compact English Route A candidate
   for translated query text.

The editable set contains equivalent English/German/Italian questions and a
smaller PT-BR probe set. Dutch and Austrian German are recorded as future
extensions; Austrian German should initially be evaluated as a German variant,
not with a bespoke route. Evaluation reports page-overlap consistency against
each English query. Compare human judgments and that consistency signal, then
measure the route/model combinations on the Pi while Whisper is also running.
Do not assume either direct translation or direct multilingual retrieval wins
until that downstream retrieval comparison is complete.

## Reproducibility and safety

Index metadata records the SHA-256 of Stage 4 chunks/report, Stage 4 corpus
source and chunk settings, model identifier/prefixes, vector dimension, metric,
and build/resource measurements. Querying rejects a changed chunk/report file
or an inconsistent embedding shape. The tool deliberately does not apply score
thresholds, select display quotations, remove citations, or exclude suspicious
layout material.
