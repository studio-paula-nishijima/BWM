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
  --model sentence-transformers/all-MiniLM-L6-v2
```

The first model use downloads and caches the model locally; later builds and
queries use that cache offline. The generated `.npy` embeddings and JSON index
metadata remain ignored because they derive from copyrighted source text.

## Query and evaluate

```bash
translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py query \
  --model sentence-transformers/all-MiniLM-L6-v2 --top-k 5 \
  --text "How does the water feel today?"

translation/river_culture_venv/bin/python translation/tools/river_culture_retrieval.py evaluate \
  --model sentence-transformers/all-MiniLM-L6-v2 --top-k 5 \
  --output files/river_culture/river_culture_evaluation_minilm.json
```

Query output preserves raw rank and score, complete chunk wording, chunk IDs,
ordered canonical `passage_ids`, page/chapter provenance, and propagated layout
flags. `grouped_regions` is an optional page-overlap grouping for human review;
it never alters `raw_results`.

## Model shortlist

The configuration intentionally evaluates a small shortlist:

1. `sentence-transformers/all-MiniLM-L6-v2`: compact English baseline and
   initial preferred Pi candidate.
2. `BAAI/bge-small-en-v1.5`: stronger English semantic candidate; it uses its
   recommended query instruction.
3. `intfloat/multilingual-e5-small`: multilingual candidate; it uses E5's
   `query:`/`passage:` prefixes and is expected to cost more memory/storage.

Do not make a final multilingual decision from model cards alone. Compare the
human judgments in the editable evaluation set, then measure the selected model
on the Pi while Whisper is also running. If visitor questions will reliably be
translated upstream, an English model remains the operationally simpler choice;
otherwise multilingual E5 is the appropriate candidate to test first.

## Reproducibility and safety

Index metadata records the SHA-256 of Stage 4 chunks/report, Stage 4 corpus
source and chunk settings, model identifier/prefixes, vector dimension, metric,
and build/resource measurements. Querying rejects a changed chunk/report file
or an inconsistent embedding shape. The tool deliberately does not apply score
thresholds, select display quotations, remove citations, or exclude suspicious
layout material.
