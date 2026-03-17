# RVC Voice Model Merging — Algorithm Documentation

**Tool:** `merge_rvc.py`
**Location:** `/Volumes/ssd/ai/github/applio-macOS-native-app/merge_rvc.py`
**Date:** 2026-03-17

---

## Table of Contents

1. [Overview](#1-overview)
2. [RVC Architecture Primer](#2-rvc-architecture-primer)
3. [Model Merging Algorithm](#3-model-merging-algorithm)
4. [Index Merging Algorithm](#4-index-merging-algorithm)
5. [Weighted Index Concatenation](#5-weighted-index-concatenation)
6. [FAISS Index Construction](#6-faiss-index-construction)
7. [Validation Rules](#7-validation-rules)
8. [Memory Management and Process Isolation](#8-memory-management-and-process-isolation)
9. [CLI Reference](#9-cli-reference)
10. [Auto-Naming and Metadata](#10-auto-naming-and-metadata)
11. [Limitations and Known Issues](#11-limitations-and-known-issues)

---

## 1. Overview

RVC (Retrieval-based Voice Conversion) models consist of two independent files that must both be merged to produce a usable blended voice:

| File | Format | Content | Purpose |
|------|--------|---------|---------|
| `.pth` | PyTorch checkpoint | Neural network weights (457 layers) | Defines the voice conversion model |
| `.index` | FAISS IVF,Flat | 768-dim feature vectors from HuBERT encoder | Guides timbre retrieval during inference |

Both files are merged independently with different algorithms. The `.pth` uses **linear weight interpolation**; the `.index` uses **vector concatenation with optional replication** (a novel addition not found in upstream RVC/Applio).

The `--ratio` parameter (0.0–1.0) controls the blend: higher values bias toward Model A.

---

## 2. RVC Architecture Primer

Understanding what gets merged requires understanding the RVC V2 inference pipeline:

```
Input Audio
    |
    v
[F0 Extraction]  → pitch contour (pm / harvest / crepe / rmvpe)
    |
    v
[HuBERT Encoder] → 768-dim content features per frame
    |
    v
[Speaker Lookup] → uses .index file (FAISS k-NN search, k=8)
    |                  finds closest training features → speaker embedding
    v
[Generator (Synthesizer)] → converts content + speaker embedding → output audio
```

During inference (from `rvc/infer/pipeline.py:378-388`):

1. HuBERT extracts 768-dim content features from each audio frame
2. The `.index` file is searched with `faiss.search(k=8)` to find the 8 nearest training feature vectors
3. Those 8 vectors are `reconstruct_n`-ed from the FAISS index
4. A weighted sum is computed using inverse-distance-squared weighting
5. This produces a speaker embedding that is fed to the generator

**Key insight:** The `.index` file determines *which* training speaker characteristics are retrieved. The `.pth` file determines *how* the generator transforms content into that speaker's voice. Both must be consistent for good results.

---

## 3. Model Merging Algorithm

### 3.1 Format Handling

RVC checkpoints have evolved across formats. The merger handles both:

**New format (current):**
```python
{
    "weight": { "enc_p.0.weight": Tensor, ... },   # 457 keys
    "config": [...],
    "sr": "40k",
    "f0": 1,
    "version": "v2",
    "vocoder": "HiFi-GAN"
}
```

**Old format:**
```python
{
    "model": { "enc_p.0.weight": Tensor, ... },
    "sr": "40k",
    ...
}
```

The `extract_model_weights()` function normalizes both to a flat `{"weight": {...}}` dict. Keys containing `"enc_q"` (the content encoder quantizer, not used in inference) are filtered out.

### 3.2 Validation Checks

Before merging, the following checks are performed. Any failure aborts:

| Check | Field | Requirement |
|-------|-------|-------------|
| Sample rate | `sr` | Both models must match (e.g., `"40k"` == `"40k"`) |
| Pitch guidance | `f0` | Both must match (0 = no pitch, 1 = pitch-guided) |
| RVC version | `version` | Both must match (`v1` vs `v2` are incompatible) |
| Vocoder | `vocoder` | Both must use the same vocoder |
| Embedder | `embedder_model` | If both present, must match |
| Architecture | sorted weight keys | Both must have identical layer names and count |

### 3.3 Weight Interpolation

For each of the 457 weight layers, the merged weight is computed as:

```
W_merged[k] = ratio * W_A[k] + (1 - ratio) * W_B[k]
```

All arithmetic is done in `float32` precision, then stored as `float16` (`.half()`) to match RVC's storage format.

**Special case — speaker embedding truncation:**

The `emb_g.weight` layer stores per-speaker embeddings. If Model A and B have different numbers of speakers (different first dimension), the merge truncates to the smaller count:

```python
min_speakers = min(W_A["emb_g.weight"].shape[0], W_B["emb_g.weight"].shape[0])
W_merged["emb_g.weight"] = ratio * W_A[:min_speakers] + (1 - ratio) * W_B[:min_speakers]
```

### 3.4 Output Checkpoint

The merged checkpoint preserves metadata from Model A:

```python
{
    "weight": { ... 457 merged layers ... },
    "config": ckpt_A["config"],
    "sr": "40000",
    "f0": 1,
    "version": "v2",
    "vocoder": "HiFi-GAN",
    "info": "Merged from model.pth and model.pth with ratio 0.50",
    # Optional: embedder_model, model_name, author, speakers_id
}
```

---

## 4. Index Merging Algorithm

### 4.1 What the Index Contains

The `.index` file is a FAISS `IVF{n_ivf},Flat` index containing 768-dimensional vectors. Each vector is a HuBERT feature extracted from one frame of the training audio. During inference, these vectors are searched with k-NN to find the most similar training features, which produce the speaker embedding.

Typical sizes:
- Small model: ~10,000–50,000 vectors
- Medium model: ~100,000–200,000 vectors
- Large model: ~200,000–500,000 vectors

### 4.2 Reconstruction

FAISS IVF indexes store vectors partitioned into inverted lists. To get the raw vectors back:

```python
idx = faiss.read_index("model.index")
vectors = idx.reconstruct_n(0, idx.ntotal)  # shape: (ntotal, 768)
```

This reconstructs all vectors by iterating through all inverted lists.

### 4.3 Equal Concatenation (Default)

The default mode combines both indexes 1:1:

```
Index A vectors (n_a vectors, 768-dim)     ──┐
                                             ├──> shuffle ──> build new IVF index
Index B vectors (n_b vectors, 768-dim)     ──┘
```

Steps:
1. Load both indexes with `faiss.read_index()`
2. Reconstruct all vectors from both with `reconstruct_n(0, ntotal)`
3. Concatenate: `np.vstack([vecs_a, vecs_b])` → shape `(n_a + n_b, 768)`
4. Shuffle with deterministic seed (`np.random.RandomState(seed)`)
5. If total > 190,000 vectors, subsample uniformly
6. Build new IVF,Flat index (see Section 6)
7. Save with `faiss.write_index()`

**Effect on inference:** With equal concatenation, the merged index contains features from both training datasets. During k-NN search (k=8), approximately half the retrieved neighbors will come from each model, producing a speaker embedding that blends both voices equally.

### 4.4 Why Shuffle

Without shuffling, vectors from Model A (first `n_a` rows) and Model B (remaining rows) would cluster together in the FAISS inverted lists. This would cause poor k-NN recall because the index partitions would split along the A/B boundary rather than along natural feature similarity.

Shuffling ensures vectors are distributed uniformly across inverted lists, so each IVF cell contains a representative mix of both models.

---

## 5. Weighted Index Concatenation

### 5.1 Motivation

Standard RVC/Applio provides no way to bias the index toward one model's features. The model weights (`--ratio`) control the generator, but the index always contributes equally from both models. This creates an asymmetry: setting `--ratio 0.8` biases the generator 80/20 toward A, but the index still retrieves 50/50.

Weighted concatenation (`--use-weighted`) resolves this by making the index bias match the model bias.

### 5.2 Algorithm

The approach replicates the dominant model's vectors so that the proportion of A-vectors in the combined pool approximately matches `--ratio`.

**Derivation:**

Given `n_a` vectors from A and `n_b` vectors from B, we want:
```
(n_a * m) / (n_a * m + n_b) ≈ ratio
```
where `m` is the replication multiplier. Solving:
```
m = (ratio * n_b) / ((1 - ratio) * n_a)
```

The number of extra copies to create:
```
extra_copies = ceil(m) - 1    (already have 1 original)
```

### 5.3 Noise Augmentation

Naive replication (copying identical vectors) would create exact duplicates that waste index capacity and degrade k-NN diversity. Each replicated copy adds Gaussian noise:

```
replica_i = original + N(0, 1e-6)
```

The noise scale (1e-6) is chosen to be:
- Large enough to make each replica unique to FAISS
- Small enough to preserve the original feature's semantic meaning
- Much smaller than the typical inter-vector distance (~700–900 L2 norm)

### 5.4 Replication Cap

Extra copies are capped at 20 to prevent absurd replication for extreme ratios:

```
extra_copies = min(extra_copies, 20)
```

At the cap, the actual achieved ratio may differ from the requested ratio. For example, with 175K vectors in A and 200K in B at ratio 0.9:

```
m = (0.9 * 200000) / (0.1 * 175000) = 10.29
extra_copies = min(ceil(10.29) - 1, 20) = min(10, 20) = 10
actual ratio ≈ (175000 * 11) / (175000 * 11 + 200000) ≈ 0.906
```

### 5.5 Proportional Downsampling

When weighted replication produces a combined total exceeding `max_total` (500,000), both sets are proportionally downsampled to preserve the target ratio:

```
scale = max_total / total
n_keep_expanded = max(1, int(expanded_count * scale))
n_keep_other = max(1, int(other_count * scale))
```

This uses `rng.choice(n, k, replace=False)` for deterministic sampling.

### 5.6 Example Calculation

Merging Hanan Ben Ari (175,620 vectors) and Zucchero (130,843 vectors) at `--ratio 0.7`:

```
m = (0.7 * 130843) / (0.3 * 175620) = 91590 / 52686 = 1.739
extra_copies = ceil(1.739) - 1 = 1
expanded_A = 175620 * (1 + 1) = 351240 vectors (A + 1 noisy replica)
combined = 351240 + 130843 = 482083 vectors
actual_ratio = 351240 / 482083 ≈ 0.729
```

Since 482083 < 500000, no downsampling occurs. Final index contains ~73% A features, closely matching the requested 70%.

---

## 6. FAISS Index Construction

### 6.1 Index Type

The merged index uses FAISS `IVF{n_ivf},Flat` — the same type used by Applio's `extract_index.py` and RVC's inference pipeline.

- **IVF** (Inverted File): Partitions vectors into `n_ivf` clusters using k-means. At search time, only the `nprobe` nearest partitions are scanned.
- **Flat**: Stores vectors with exact L2 distance (no quantization). This preserves full precision for k-NN retrieval.

### 6.2 IVF Parameter

The number of inverted lists is computed as:

```python
n_ivf = min(int(16 * sqrt(n)), n // 39)
n_ivf = max(n_ivf, 1)
```

This formula is taken directly from Applio's `extract_index.py` (line 58).

| Vector Count | sqrt(n) | n//39 | n_ivf |
|---|---|---|---|
| 10,000 | 506 | 256 | 506 → capped at 256 |
| 50,000 | 1,131 | 1,282 | 1,131 |
| 100,000 | 1,600 | 2,564 | 1,600 |
| 190,000 | 2,206 | 4,871 | 2,206 |
| 500,000 | 3,577 | 12,820 | 3,577 |

The `n//39` constraint ensures a minimum of ~39 vectors per inverted list, which is necessary for k-means to produce meaningful partitions.

### 6.3 Search Parameters

```python
nprobe = 1
```

At inference time, only 1 inverted list is searched. This is the RVC standard — it prioritizes speed over recall. Each IVF cell typically contains enough candidates to fill the k=8 query.

### 6.4 Training and Adding

```python
merged_idx.train(all_vecs)        # k-means on all vectors to build IVF partitions
for batch in chunks(8192):
    merged_idx.add(batch)          # assign vectors to their nearest centroid
```

The batch size of 8192 matches Applio's implementation.

### 6.5 Large Dataset Handling

When the combined vector count exceeds 190,000, the dataset is uniformly subsampled before index construction:

```python
MAX_INDEX_VECTORS = 190_000
indices = rng.choice(n_total, 190_000, replace=False)
all_vecs = all_vecs[indices]
```

**Why 190,000?**

The upstream Applio uses MiniBatchKMeans (10,000 clusters) to reduce datasets >200K. However, MiniBatchKMeans can consume 4–8 GB of RAM on large datasets and has been observed to SIGSEGV on systems with limited memory. The 190K threshold keeps memory usage under ~1.5 GB (190K * 768 * 4 bytes = ~550 MB for vectors, plus k-means working memory).

**Note:** The upstream reference uses `n_ivf = min(16*sqrt(n), n//39)` without dimension hardcoding, while our tool uses `all_vecs.shape[1]` for the dimension parameter in `index_factory`, making it compatible with non-768-dim models.

---

## 7. Validation Rules

### 7.1 Model Validation

| Rule | Enforcement |
|------|-------------|
| Both `--model-a` and `--model-b` must be provided | CLI arg validation |
| `--output` required unless `--dry-run` | CLI arg validation |
| `--ratio` in [0.0, 1.0] | CLI arg validation |
| Sample rates match | Checkpoint field comparison |
| F0 (pitch guidance) matches | Checkpoint field comparison |
| RVC version matches | Checkpoint field comparison |
| Vocoder matches | Checkpoint field comparison |
| Same weight layer names | Sorted key set comparison |

### 7.2 Index Validation

| Rule | Enforcement |
|------|-------------|
| Both `--index-a` and `--index-b` must be provided | CLI arg validation |
| `--index-output` required unless `--dry-run` | CLI arg validation |
| Dimensions must match | `idx_a.d == idx_b.d` |
| Neither index is empty | `ntotal > 0` for both |
| `--ratio` in [0.01, 0.99] when `--use-weighted` | CLI arg validation |
| Warning if dimension != 768 | Non-fatal warning |

### 7.3 Dry-Run Behavior

The dry-run (`--dry-run`) loads files and performs all validation, then stops before reconstruction or saving. For weighted index mode, it also previews the replication count:

```
[DRY RUN] Weighted concatenation preview:
  Ratio: 0.7 (dominant: A)
  Index A: 175,620 vectors, Index B: 130,843 vectors
  Would replicate A: 1 extra copies

[DRY RUN] Would merge indexes successfully
```

---

## 8. Memory Management and Process Isolation

### 8.1 PyTorch / FAISS Allocator Conflict

A critical bug was discovered during testing: **`faiss.train()` SIGSEGVs when PyTorch's memory allocator has been loaded in the same process**. This occurs because both libraries use custom memory allocators that conflict when loaded together, particularly on macOS with Apple Silicon.

**Symptoms:**
- Model merge alone: works fine
- Index merge alone: works fine
- Both in sequence in the same process: SIGSEGV during `faiss.train()`
- Both via separate processes: works fine

### 8.2 Solution: Subprocess Isolation

When both model and index merges are requested, the tool runs the index merge in a subprocess:

```
Parent process:
  1. Import torch + faiss
  2. merge_models() — loads .pth files, interpolates weights, saves
  3. Launch subprocess with RESING_SKIP_TORCH=1

Child process:
  1. RESING_SKIP_TORCH=1 → skip torch import
  2. Import faiss only
  3. merge_indexes() — loads .index files, reconstructs, builds new index
  4. Exit
```

The `RESING_SKIP_TORCH` environment variable is checked at module import time:

```python
if os.environ.get("RESING_SKIP_TORCH"):
    torch = None       # Skip torch import entirely
else:
    import torch
```

### 8.3 Memory Management in merge_indexes()

Within the index merge function, aggressive memory cleanup is performed between stages:

```python
# After reconstruction
del idx_a, idx_b
gc.collect()

# After concatenation
del vecs_a, vecs_b
gc.collect()
```

For 175K + 130K vectors at 768 dimensions:
- Raw reconstruction: ~900 MB (two copies of all vectors)
- After concatenation: ~900 MB (one combined array)
- After subsampling to 190K: ~550 MB
- After index construction: ~600 MB (FAISS internal + vectors)

---

## 9. CLI Reference

### 9.1 Arguments

```
python merge_rvc.py [OPTIONS]

Model Merging:
  --model-a PATH         First model (.pth)
  --model-b PATH         Second model (.pth)
  --ratio FLOAT          Blend ratio 0.0-1.0 (default: 0.5)

Output:
  --name NAME            Name for the merged model
                         (default: auto-derived from source metadata/folder)
  --output-dir DIR       Output directory, created if needed
                         (default: ./<merge_name>)
  --output PATH          Explicit output path for .pth
                         (overrides --output-dir and suppresses metadata.json)

Index Merging:
  --index-a PATH         First index (.index)
  --index-b PATH         Second index (.index)
  --index-output PATH    Explicit output path for .index
  --use-weighted         Weight concatenation by ratio
  --random-seed INT      Seed for reproducibility (default: 42)

General:
  --dry-run              Validate without creating files
```

### 9.2 Usage Examples

```bash
# Simplest — auto-naming, auto output directory
python merge_rvc.py \
    --model-a '/path/to/Sade/Sade.pth' \
    --model-b '/path/to/Ani Lorak/AnilorakV2.pth' \
    --index-a '/path/to/Sade/Sade.index' \
    --index-b '/path/to/Ani Lorak/AnilorakV2.index'
# Creates: ./Sade + Ani Lorak (0.50)/Sade + Ani Lorak (0.50).{pth,index,metadata.json}

# Custom name
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.5 \
    --name 'Tina Daya' \
    --index-a a.index --index-b b.index
# Creates: ./Tina Daya/Tina Daya.{pth,index,metadata.json}

# Custom output directory
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.7 \
    --name 'My Blend' --output-dir /Volumes/ssd/rvc/merged \
    --index-a a.index --index-b b.index --use-weighted

# Weighted merge — 70% model A generator, 70% A index features
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.7 \
    --index-a a.index --index-b b.index \
    --use-weighted --name 'A Dominant (70)'

# Explicit output paths (no auto-naming, no metadata.json)
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.5 \
    --output /path/to/merged.pth \
    --index-a a.index --index-b b.index \
    --index-output /path/to/merged.index

# Model only (no index merge)
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.6 \
    --name 'Blend 60-40'

# Dry run — validate compatibility without creating files
python merge_rvc.py \
    --model-a a.pth --model-b b.pth --ratio 0.5 --dry-run

# Weighted dry run — preview replication counts
python merge_rvc.py \
    --index-a a.index --index-b b.index \
    --use-weighted --ratio 0.8 --dry-run
```

### 9.3 Deterministic Reproducibility

With the same `--random-seed`, the following are deterministic:
- Vector shuffling order
- Noise added to replicated vectors
- Subsampling selection
- Replication count

FAISS index construction has internal non-determinism (k-means initialization), so the binary `.index` output may differ across runs with the same seed. However, functional equivalence is preserved: same ntotal, same k-NN results.

### 9.4 Output Path Resolution

The tool resolves output paths through this priority chain:

1. If `--output` is set: use that exact path for the `.pth`. No `metadata.json` is written (explicit paths are assumed to be scripted/integrated).
2. If `--name` and/or `--output-dir` are set: create `<output-dir>/<name>.pth` and `<output-dir>/<name>.index`.
3. If neither is set: auto-derive name from sources, create `./<auto-name>/<auto-name>.pth`.

The `metadata.json` is always written when `--output` is not used (i.e., when the tool controls the output directory).

---

## 10. Auto-Naming and Metadata

### 10.1 Auto-Naming Algorithm

When `--name` is not provided, the merge name is derived from source model metadata using `derive_merge_name()`:

**Step 1 — Extract voice names** (`extract_voice_name()`):

For each source model, the voice name is determined by priority:

| Priority | Source | Example input | Example output |
|----------|--------|---------------|----------------|
| 1 | `metadata.json` → `title` field | `"Hanan Ben Ari (Israeli Singer) [RVC V2] [450 Epochs]"` | `"Hanan Ben Ari"` |
| 2 | Parent directory name | `"Hanan Ben Ari - Weights"` | `"Hanan Ben Ari"` |
| 3 | Filename stem | `"added_IVF4503_Flat_nprobe_1_hanan_ba_v2"` | `"hanan_ba"` |

Title cleaning rules (applied in order):
1. Strip parenthetical context: `(Israeli Singer)`, `(Ukrainian Singer)`, etc.
2. Strip bracket suffixes: `[RVC V2]`, `[450 Epochs]`, etc.
3. Strip trailing `- RVC v2 ...` patterns
4. Collapse whitespace

Folder name cleaning rules:
1. Strip `-Weights`, `-Weights-N`, `-RVC`, `_v2` suffixes

Filename cleaning rules:
1. Strip `added_IVF*_Flat_nprobe_*_` prefix
2. Strip `_v2` suffix

**Step 2 — Combine names** (`derive_merge_name()`):

```
"<Name A> + <Name B> (<ratio>)"
```

Examples:
- Equal blend: `"Sade + Ani Lorak (0.50)"`
- Weighted blend: `"Hanan Ben Ari + Zucchero (0.70)"`
- Custom `--name`: `"Tina Daya"`

### 10.2 Source Metadata Loading

`load_model_metadata()` looks for a `metadata.json` file in the same directory as the model file (.pth or .index). This is the standard metadata format from weights.gg / Applio model downloads.

If the file is found and valid JSON, its fields are used for:
- Auto-naming (via the `title` field)
- Merge metadata (source provenance)

If not found, an empty dict is returned and naming falls through to folder/filename heuristics.

### 10.3 Merge Metadata Format

The `metadata.json` written to the output directory has this structure:

```json
{
  "title": "Tina Daya",
  "type": "merged",
  "merge": {
    "ratio": 0.5,
    "weighted_index": false,
    "random_seed": 42,
    "merged_at": "2026-03-17T16:38:38Z"
  },
  "source_a": {
    "path": "/Volumes/ssd/ai/rvc/Sade/Sade.pth",
    "size_bytes": 55193209,
    "md5": "dc6f367b489d66724353dc916d223548",
    "title": "Sade",
    "author": {"name": "tatersalad6636"},
    "description": "...",
    "tags": ["RVC v2", "English", "Artist"],
    "url": "https://...",
    "id": "clvn3ptba07igg4qxxsei9i1w",
    "uploadedAt": "2024-05-01T00:51:03.717Z",
    "type": "v2",
    "torch_version": "v2",
    "torch_f0": 1,
    "torch_info": "1000epoch",
    "torch_sr": "40k"
  },
  "source_b": { "..." },
  "model": {
    "layers": 457,
    "sample_rate": "40000",
    "f0": 1,
    "version": "v2",
    "vocoder": "HiFi-GAN",
    "size_bytes": 55218763,
    "md5": "c0ca5117a029c920947a61d920203169"
  },
  "index": {
    "vectors": 146980,
    "dimension": 768,
    "mode": "equal",
    "ratio": 0.5,
    "size_bytes": 464303979
  }
}
```

**Field reference:**

| Section | Field | Source |
|---------|-------|--------|
| `title` | Merged model name | `--name` or auto-derived |
| `merge.ratio` | Blend ratio used | `--ratio` |
| `merge.weighted_index` | Whether `--use-weighted` was set | CLI flag |
| `merge.random_seed` | Seed for shuffling | `--random-seed` |
| `merge.merged_at` | ISO 8601 UTC timestamp | System clock |
| `source_a/b.path` | Original file path | CLI arg |
| `source_a/b.size_bytes` | Original file size | `os.path.getsize()` |
| `source_a/b.md5` | Original file MD5 | MD5 hex digest |
| `source_a/b.title` | Source model title | Source `metadata.json` |
| `source_a/b.author` | Source model author | Source `metadata.json` |
| `source_a/b.description` | Source description | Source `metadata.json` |
| `source_a/b.tags` | Source tags | Source `metadata.json` |
| `source_a/b.torch_version` | RVC version from torch metadata | Source `metadata.json` → `torchMetadata.version` |
| `source_a/b.torch_f0` | Pitch guidance from torch metadata | Source `metadata.json` → `torchMetadata.f0` |
| `source_a/b.torch_info` | Training info (e.g. "1000epoch") | Source `metadata.json` → `torchMetadata.extra_info.info` |
| `source_a/b.torch_sr` | Sample rate from torch metadata | Source `metadata.json` → `torchMetadata.extra_info.sr` |
| `model.layers` | Number of weight layers in merged .pth | Merged checkpoint |
| `model.sample_rate` | Sample rate | Merged checkpoint |
| `model.f0` | Pitch guidance | Merged checkpoint |
| `model.version` | RVC version | Merged checkpoint |
| `model.vocoder` | Vocoder type | Merged checkpoint |
| `model.size_bytes` | Merged .pth file size | `os.path.getsize()` |
| `model.md5` | Merged .pth MD5 | MD5 hex digest |
| `index.vectors` | Total vectors in merged index | FAISS `index.ntotal` |
| `index.dimension` | Vector dimension | FAISS `index.d` |
| `index.mode` | `"equal"` or `"weighted"` | CLI flags |
| `index.ratio` | Ratio used for index | `--ratio` |
| `index.size_bytes` | Merged .index file size | `os.path.getsize()` |

Source fields that are not present in the source `metadata.json` are omitted from the output rather than set to null.

---

## 11. Limitations and Known Issues

### 11.1 k-NN Saturation at Extreme Ratios

At ratios above 0.9 or below 0.1, the replicated vectors may saturate the top-k results. With k=8 search and 90%+ of vectors coming from one model, it becomes statistically likely that all 8 nearest neighbors are from the dominant model, regardless of the query. This means the minority model's contribution to the speaker embedding effectively vanishes.

**Workaround:** For extreme blends, consider capping `--ratio` at 0.85 / 0.15 and relying more on the model weight ratio for fine control.

### 11.2 Index Size Growth

Weighted mode increases the index file size proportionally to replication. At `--ratio 0.7` with 1 extra copy, the index roughly doubles in size (before the 500K cap). At `--ratio 0.9` with 6 copies, it could grow 6x.

### 11.3 PyTorch / FAISS Conflict

Both model and index merges cannot run in the same process on systems where the two libraries' allocators conflict (observed on macOS with Apple Silicon and faiss-cpu). The tool automatically detects this and runs index merge in a subprocess.

### 11.4 Half-Precision Artifacts

Merged weights are stored as `float16`. Repeated merging (A+B=C, then C+D=E) accumulates rounding errors because each merge converts float32 to float16. For critical applications, prefer merging from the original source models rather than from already-merged intermediates.

### 11.5 Speaker Embedding Truncation

When merging models with different numbers of speakers, the smaller speaker count is used. Speaker embeddings for excess speakers in the larger model are silently discarded.

### 11.6 Subsampling Quality Trade-off

Datasets exceeding 190,000 vectors are uniformly subsampled. This is a simplification compared to Applio's MiniBatchKMeans approach (which reduces to 10,000 cluster centroids). The subsampled index may have slightly lower retrieval quality than a KMeans-reduced one, but avoids the OOM/SIGSEGV issues observed with MiniBatchKMeans on memory-constrained systems.

---

## Appendix A: RVC Inference Pipeline Reference

From `rvc/infer/pipeline.py:378-433`:

```python
# k-NN search in the FAISS index
D, I = index.search(feature, k=8)

# Reconstruct the k nearest vectors
nn_vecs = index.reconstruct_n(0, index.ntotal)
topk_vecs = nn_vecs[I[0]]

# Inverse-distance-squared weighting
nnet = torch.from_numpy(topk_vecs).unsqueeze(0).to(device)
D_star = D[0] / D[0].min()  # normalize distances
w = D_star / D_star.sum()   # inverse-distance weights

# Weighted sum produces speaker embedding
speaker_embedding = (nnet * w.unsqueeze(-1)).sum(dim=1)
```

This is why the index composition matters: the `w` weights and which vectors appear in the top-8 directly determine the speaker characteristics passed to the generator.

## Appendix B: Comparison with ReSing's Quadratic Mixing

IK Multimedia's ReSing implements a different approach called `quadratic_mix` that uses non-linear interpolation for model weights. The key difference:

| Aspect | merge_rvc.py (this tool) | ReSing quadratic_mix |
|--------|--------------------------|---------------------|
| Weight interpolation | Linear: `r*A + (1-r)*B` | Quadratic (non-linear, undisclosed formula) |
| Index handling | Equal or weighted concatenation | ModelMix/IndexMix with blend parameters |
| Control parameter | Single ratio (0–1) | `mix_weights` + `mix_indexes` (separate) |

The weighted index concatenation in this tool was partially inspired by ReSing's approach of controlling index and model blending independently.

## Appendix C: File Sizes

Typical merged output sizes for two 48kHz RVC V2 models:

| Component | Size | Notes |
|-----------|------|-------|
| `.pth` (model) | ~55 MB | Fixed size regardless of ratio |
| `.index` (equal) | ~570 MB | 190K vectors * 768 * 4 bytes + FAISS overhead |
| `.index` (weighted 0.7) | ~570 MB | Replication fits under 500K cap |
| `.index` (weighted 0.9) | ~1.5 GB | 6x replication before cap/downsample |
