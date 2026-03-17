#!/usr/bin/env python3
"""
RVC Model and Index Merger - Standalone CLI Tool

Merges RVC voice models (.pth) and/or FAISS indexes (.index) for voice conversion.

Index merging supports two modes:

  * Equal concatenation (default): Both indexes contribute equally to k-NN
    retrieval.  Vectors from A and B are concatenated 1:1, shuffled, and
    re-indexed.  This is backward-compatible with the original behaviour.

  * Weighted concatenation (--use-weighted): Bias k-NN retrieval toward one
    model's features by replicating the dominant model's vectors.  For
    example, --ratio 0.7 with --use-weighted replicates A's vectors so that
    ~70 % of the combined index comes from model A.  Each replicated copy
    adds a tiny amount of noise (1e-6) to avoid exact duplicates.  A cap of
    20 extra copies prevents absurd replication.  If the combined count
    exceeds --max-total-vectors (default 500 000), both sets are
    proportionally downsampled to preserve the target ratio.

Index construction uses IVF,Flat (matching Applio's extract_index.py):
  n_ivf = min(16 * sqrt(n), n // 39), nprobe = 1, batch_size = 8192.
For datasets > 200K vectors, MiniBatchKMeans (10 000 clusters) reduces
the set before building the index.

Limitations:
  - k-NN saturation: at extreme ratios (> 0.9 or < 0.1) the replicated
    vectors may dominate the top-k results, reducing the contribution of the
    minority model regardless of the ratio.
  - Index size growth: weighted mode increases index file size proportional
    to the replication count.

Deterministic behaviour is controlled by --random-seed (default 42).

Usage:
    # Merge models only
    python merge_rvc.py --model-a model_a.pth --model-b model_b.pth --ratio 0.5 --output merged.pth

    # Merge indexes only (equal concatenation)
    python merge_rvc.py --index-a a.index --index-b b.index --index-output merged.index

    # Merge indexes with weighted concatenation (70% model A features)
    python merge_rvc.py --index-a a.index --index-b b.index --index-output merged.index \\
        --use-weighted --ratio 0.7

    # Merge both model + index with weighting
    python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.7 \\
        --index-a a.index --index-b b.index \\
        --output merged.pth --index-output merged.index --use-weighted

    # Dry run (validate without merging)
    python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 --dry-run
"""

import argparse
import gc
import hashlib
import json
import math
import os
import re
import sys
from collections import OrderedDict

import numpy as np

# PyTorch and faiss have a known memory allocator conflict:
# faiss.train() SIGSEGVs when PyTorch's allocator has been loaded.
# When RESING_SKIP_TORCH=1 (set by subprocess index merge), skip torch import.
if os.environ.get("RESING_SKIP_TORCH"):
    torch = None
else:
    try:
        import torch
    except ImportError:
        torch = None

# Optional dependencies with graceful error handling
try:
    import faiss
except ImportError:
    faiss = None


def validate_file_exists(path: str, description: str) -> bool:
    """Validate that a file exists and is readable."""
    if not os.path.exists(path):
        print(f"Error: {description} not found: {path}")
        return False
    if not os.path.isfile(path):
        print(f"Error: {description} is not a file: {path}")
        return False
    if not os.access(path, os.R_OK):
        print(f"Error: {description} is not readable: {path}")
        return False
    return True


def validate_output_path(path: str) -> bool:
    """Validate that output directory exists and is writable."""
    directory = os.path.dirname(path) or "."
    if not os.path.exists(directory):
        print(f"Error: Output directory does not exist: {directory}")
        return False
    if not os.access(directory, os.W_OK):
        print(f"Error: Output directory is not writable: {directory}")
        return False
    return True


def load_model_metadata(model_path: str) -> dict:
    """
    Load metadata from a sibling metadata.json in the model's directory.

    Looks for metadata.json next to the model file (.pth or .index).
    Returns an empty dict if not found or unreadable.
    """
    model_dir = os.path.dirname(os.path.abspath(model_path))
    meta_path = os.path.join(model_dir, "metadata.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def extract_voice_name(model_path: str, meta: dict) -> str:
    """
    Derive a short voice name from model path or metadata.

    Priority: metadata title > parent folder name > filename stem.
    Returns a cleaned, filesystem-safe name.
    """
    # 1. Try metadata title (e.g. "Hanan Ben Ari (Israeli Singer) [RVC V2]")
    title = meta.get("title", "")
    if title:
        # Strip parenthetical context: (Israeli Singer), (Ukrainian Singer), etc.
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', title).strip()
        # Strip common suffixes like [RVC V2], [450 Epochs], etc.
        name = re.sub(r'\s*\[.*?\]\s*', ' ', name).strip()
        # Strip trailing " - RVC v2 ..." suffixes
        name = re.sub(r'\s*-\s*RVC\s*v?\d+.*$', '', name, flags=re.IGNORECASE).strip()
        # Clean up extra whitespace
        name = re.sub(r'\s{2,}', ' ', name).strip()
        if name:
            return name

    # 2. Parent folder name (e.g. "Hanan Ben Ari - Weights")
    folder = os.path.basename(os.path.dirname(os.path.abspath(model_path)))
    # Strip common suffixes: -Weights, -Weights-2, _v2, etc.
    name = re.sub(r'[-_]\s*(Weights?|Weights?-\d+|RVC|v\d+)\s*$', '', folder, flags=re.IGNORECASE).strip()
    if name and name != folder:
        return name

    # 3. Filename stem without extension
    stem = os.path.splitext(os.path.basename(model_path))[0]
    # Strip common patterns: added_IVF*_Flat_nprobe_1_*_v2
    name = re.sub(r'^added_IVF\d+_Flat_nprobe_\d+_', '', stem).strip()
    name = re.sub(r'_v\d+$', '', name).strip()
    if name:
        return name

    return folder or "unknown"


def derive_merge_name(path_a: str, path_b: str, ratio: float,
                      meta_a: dict, meta_b: dict) -> str:
    """
    Auto-generate a merged model name from source models.

    Examples:
      "Hanan Ben Ari + Zucchero (0.50)"
      "Hanan Ben Ari + Zucchero (0.70 weighted)"
    """
    name_a = extract_voice_name(path_a, meta_a)
    name_b = extract_voice_name(path_b, meta_b)

    if ratio == 0.5:
        return f"{name_a} + {name_b} (0.50)"
    else:
        return f"{name_a} + {name_b} ({ratio:.2f})"


def write_merge_metadata(output_dir: str, name: str,
                         path_a: str, path_b: str, ratio: float,
                         meta_a: dict, meta_b: dict,
                         use_weighted: bool, random_seed: int,
                         model_result: dict = None,
                         index_result: dict = None) -> None:
    """
    Write a metadata.json describing the merge into output_dir.

    Args:
        output_dir: Directory to write metadata.json into.
        name: Human-readable merge name.
        path_a, path_b: Original model/index paths.
        ratio: Blend ratio used.
        meta_a, meta_b: Parsed source metadata.json dicts.
        use_weighted: Whether weighted index concatenation was used.
        random_seed: Seed used for shuffling.
        model_result: Dict with model merge stats (layers, sr, version, etc.).
        index_result: Dict with index merge stats (vectors, ivf, dimension, etc.).
    """
    entry = {
        "title": name,
        "type": "merged",
        "merge": {
            "ratio": ratio,
            "weighted_index": use_weighted,
            "random_seed": random_seed,
            "merged_at": os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip(),
        },
        "source_a": _build_source_entry(path_a, meta_a),
        "source_b": _build_source_entry(path_b, meta_b),
    }

    if model_result:
        entry["model"] = model_result
    if index_result:
        entry["index"] = index_result

    meta_path = os.path.join(output_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    print(f"  Metadata written to: {meta_path}")


def _build_source_entry(model_path: str, meta: dict) -> dict:
    """Build a source model entry from path + optional metadata.json."""
    entry = {
        "path": model_path,
    }
    if os.path.exists(model_path):
        entry["size_bytes"] = os.path.getsize(model_path)
        entry["md5"] = _md5_file(model_path)
    if meta:
        # Pull useful fields from weights.gg / Applio metadata
        for key in ["title", "author", "description", "tags", "url",
                     "id", "uploadedAt", "type"]:
            if key in meta:
                entry[key] = meta[key]
        if "torchMetadata" in meta:
            tm = meta["torchMetadata"]
            for key in ["version", "f0"]:
                if key in tm:
                    entry[f"torch_{key}"] = tm[key]
            if "extra_info" in tm:
                for key in ["info", "sr"]:
                    if key in tm["extra_info"]:
                        entry[f"torch_{key}"] = tm["extra_info"][key]
    return entry


def _md5_file(path: str) -> str:
    """Compute MD5 hex digest of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_model_weights(ckpt: dict) -> dict:
    """Extract weights from checkpoint, handling both old and new formats."""
    if "model" in ckpt:
        # Old format with "model" key
        a = ckpt["model"]
        opt = OrderedDict()
        opt["weight"] = {}
        for key in a.keys():
            if "enc_q" in key:
                continue
            opt["weight"][key] = a[key]
        return opt["weight"]
    else:
        # New format with "weight" key
        return ckpt.get("weight", {})


def merge_models(
    path_a: str, path_b: str, ratio: float, output_path: str, dry_run: bool = False
) -> bool:
    """
    Merge two RVC voice models via weight interpolation.

    Args:
        path_a: Path to first model (.pth)
        path_b: Path to second model (.pth)
        ratio: Blend ratio (0.0-1.0), higher = more of model A
        output_path: Path for merged model output
        dry_run: If True, only validate without saving

    Returns:
        True on success, False on error
    """
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Merging models...")
    print(f"  Model A: {path_a}")
    print(f"  Model B: {path_b}")
    print(f"  Ratio: {ratio:.2f} (higher = more of Model A)")

    # Validate inputs
    if not validate_file_exists(path_a, "Model A"):
        return False
    if not validate_file_exists(path_b, "Model B"):
        return False
    if not dry_run and not validate_output_path(output_path):
        return False

    try:
        # Load checkpoints
        print("  Loading Model A...")
        ckpt_a = torch.load(path_a, map_location="cpu", weights_only=True)
        print("  Loading Model B...")
        ckpt_b = torch.load(path_b, map_location="cpu", weights_only=True)

        # Normalize sample rates
        sr_a = str(ckpt_a.get("sr", "")).lower().replace("k", "000")
        sr_b = str(ckpt_b.get("sr", "")).lower().replace("k", "000")

        # === VALIDATION CHECKS ===
        errors = []

        # Sample rate check
        if sr_a != sr_b:
            errors.append(f"Sample rates differ: {sr_a} vs {sr_b}")

        # Pitch guidance (f0) check
        f0_a = ckpt_a.get("f0", 1)
        f0_b = ckpt_b.get("f0", 1)
        if f0_a != f0_b:
            errors.append(
                f"Pitch guidance (f0) mismatch: model A has f0={f0_a}, model B has f0={f0_b}"
            )

        # Version check (v1 vs v2)
        version_a = ckpt_a.get("version", "v1")
        version_b = ckpt_b.get("version", "v1")
        if version_a != version_b:
            errors.append(f"Model versions differ: {version_a} vs {version_b}")

        # Vocoder check
        vocoder_a = ckpt_a.get("vocoder", "HiFi-GAN")
        vocoder_b = ckpt_b.get("vocoder", "HiFi-GAN")
        if vocoder_a != vocoder_b:
            errors.append(f"Vocoders differ: {vocoder_a} vs {vocoder_b}")

        # Embedder check (if present)
        embedder_a = ckpt_a.get("embedder_model", None)
        embedder_b = ckpt_b.get("embedder_model", None)
        if embedder_a and embedder_b and embedder_a != embedder_b:
            errors.append(f"Embedder models differ: {embedder_a} vs {embedder_b}")

        if errors:
            print("\n  Validation failed:")
            for err in errors:
                print(f"    - {err}")
            return False

        print("  Validation passed: models are compatible")

        # Extract weights
        weights_a = extract_model_weights(ckpt_a)
        weights_b = extract_model_weights(ckpt_b)

        # Architecture validation
        keys_a = sorted(list(weights_a.keys()))
        keys_b = sorted(list(weights_b.keys()))
        if keys_a != keys_b:
            print(f"\n  Error: Model architectures differ - cannot merge")
            print(f"    Model A has {len(keys_a)} weight keys")
            print(f"    Model B has {len(keys_b)} weight keys")
            return False

        print(f"  Architecture: {len(keys_a)} weight layers")

        if dry_run:
            print("\n  [DRY RUN] Would merge models successfully")
            return True

        # Merge weights
        print("  Merging weights...")
        merged_weights = OrderedDict()
        for key in weights_a.keys():
            if key == "emb_g.weight" and weights_a[key].shape != weights_b[key].shape:
                # Handle different speaker embedding dimensions
                min_shape0 = min(weights_a[key].shape[0], weights_b[key].shape[0])
                merged_weights[key] = (
                    ratio * weights_a[key][:min_shape0].float()
                    + (1 - ratio) * weights_b[key][:min_shape0].float()
                ).half()
                print(f"    {key}: truncated to {min_shape0} speakers")
            else:
                merged_weights[key] = (
                    ratio * weights_a[key].float() + (1 - ratio) * weights_b[key].float()
                ).half()

        # Build output checkpoint
        output_ckpt = OrderedDict()
        output_ckpt["weight"] = merged_weights
        output_ckpt["config"] = ckpt_a.get("config", [])
        output_ckpt["sr"] = sr_a
        output_ckpt["f0"] = f0_a
        output_ckpt["version"] = version_a
        output_ckpt["vocoder"] = vocoder_a
        output_ckpt["info"] = f"Merged from {os.path.basename(path_a)} and {os.path.basename(path_b)} with ratio {ratio:.2f}"

        # Preserve optional metadata
        for key in ["embedder_model", "model_name", "author", "speakers_id"]:
            if key in ckpt_a:
                output_ckpt[key] = ckpt_a[key]

        # Save
        print(f"  Saving to: {output_path}")
        torch.save(output_ckpt, output_path)
        print("  Model merge complete!")
        return True

    except Exception as e:
        print(f"\n  Error merging models: {e}")
        return False


def replicate_vectors_weighted(
    vecs_a: np.ndarray,
    vecs_b: np.ndarray,
    ratio: float,
    max_total: int = 500_000,
    rng: np.random.RandomState = None,
) -> tuple:
    """
    Replicate the dominant model's vectors to achieve a target ratio.

    Given *ratio* (fraction of A in the final index), this function
    replicates A's vectors (or B's when ratio < 0.5) so that the
    combined pool approximates the desired proportion.  Each replicated
    copy receives a tiny amount of Gaussian noise (scale 1e-6) to
    avoid exact duplicates in the FAISS index.

    If the combined total exceeds *max_total*, both sets are
    proportionally downsampled to fit.

    Args:
        vecs_a: Vectors from index A, shape (n_a, d).
        vecs_b: Vectors from index B, shape (n_b, d).
        ratio: Target fraction of A in the final pool (0.0–1.0).
        max_total: Cap on total vectors before proportional downsample.
        rng: Deterministic RNG instance.

    Returns:
        (all_vecs, description_string) where *all_vecs* is float32
        with shape (total, d) and *description_string* summarises
        the operation for caller reporting.
    """
    # Near-equal ratio — nothing to do
    if abs(ratio - 0.5) < 1e-9:
        all_vecs = np.vstack([vecs_a, vecs_b]).astype("float32")
        return all_vecs, "equal (ratio=0.5)"

    if rng is None:
        rng = np.random.RandomState(42)

    n_a = vecs_a.shape[0]
    n_b = vecs_b.shape[0]
    desc_parts = []

    if ratio > 0.5:
        # Target: (n_a * multiplier) / (n_a * multiplier + n_b) ≈ ratio
        # => multiplier = (ratio * n_b) / ((1 - ratio) * n_a)
        multiplier = (ratio * n_b) / ((1 - ratio) * n_a)
        extra_copies = max(0, int(math.ceil(multiplier) - 1))
        extra_copies = min(extra_copies, 20)  # cap absurd replication
        desc_parts.append(f"replicated A: {extra_copies} extra copies")

        parts = [vecs_a.astype("float32")]
        for _ in range(extra_copies):
            noise = rng.randn(*vecs_a.shape).astype("float32") * 1e-6
            parts.append(vecs_a.astype("float32") + noise)
        expanded = np.concatenate(parts, axis=0)
        other = vecs_b.astype("float32")
    else:
        # Mirror logic: replicate B to make it dominant
        multiplier = ((1 - ratio) * n_a) / (ratio * n_b)
        extra_copies = max(0, int(math.ceil(multiplier) - 1))
        extra_copies = min(extra_copies, 20)
        desc_parts.append(f"replicated B: {extra_copies} extra copies")

        parts = [vecs_b.astype("float32")]
        for _ in range(extra_copies):
            noise = rng.randn(*vecs_b.shape).astype("float32") * 1e-6
            parts.append(vecs_b.astype("float32") + noise)
        expanded = np.concatenate(parts, axis=0)
        other = vecs_a.astype("float32")

    # Proportional downsample if exceeding cap
    total = expanded.shape[0] + other.shape[0]
    if total > max_total:
        scale = max_total / total
        n_keep_exp = max(1, int(expanded.shape[0] * scale))
        n_keep_oth = max(1, int(other.shape[0] * scale))
        expanded = expanded[rng.choice(expanded.shape[0], n_keep_exp, replace=False)]
        other = other[rng.choice(other.shape[0], n_keep_oth, replace=False)]
        desc_parts.append(f"downsampled to {max_total:,} total vectors")

    all_vecs = np.vstack([expanded, other])
    desc = f"weighted (ratio={ratio}, {', '.join(desc_parts)})"
    return all_vecs, desc


def merge_indexes(
    path_a: str,
    path_b: str,
    output_path: str,
    dry_run: bool = False,
    use_weighted: bool = False,
    ratio: float = 0.5,
    random_seed: int = 42,
) -> bool:
    """
    Merge two FAISS indexes by reconstructing and reindexing vectors.

    Args:
        path_a: Path to first index (.index)
        path_b: Path to second index (.index)
        output_path: Path for merged index output
        dry_run: If True, only validate without saving
        use_weighted: Bias vector concatenation toward dominant model
        ratio: Blend ratio — controls weighting when *use_weighted* is True
        random_seed: Seed for reproducible shuffling / replication

    Returns:
        True on success, False on error
    """
    if faiss is None:
        print("Error: faiss is not installed. Install with: pip install faiss-cpu")
        return False

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Merging indexes...")
    print(f"  Index A: {path_a}")
    print(f"  Index B: {path_b}")

    # Validate inputs
    if not validate_file_exists(path_a, "Index A"):
        return False
    if not validate_file_exists(path_b, "Index B"):
        return False
    if not dry_run and not validate_output_path(output_path):
        return False

    try:
        # Load indexes
        print("  Loading Index A...")
        idx_a = faiss.read_index(path_a)
        print(f"    Vectors: {idx_a.ntotal:,}, Dimension: {idx_a.d}")

        print("  Loading Index B...")
        idx_b = faiss.read_index(path_b)
        print(f"    Vectors: {idx_b.ntotal:,}, Dimension: {idx_b.d}")

        # Validate dimensions match
        if idx_a.d != idx_b.d:
            print(f"\n  Error: Index dimensions differ: {idx_a.d} vs {idx_b.d}")
            return False

        # Guard: empty indexes
        if idx_a.ntotal == 0 or idx_b.ntotal == 0:
            print("\n  Error: One or both indexes are empty")
            return False

        # RVC uses 768-dim embeddings (HuBERT)
        if idx_a.d != 768:
            print(f"  Warning: Expected 768 dimensions, got {idx_a.d}")

        total_vectors = idx_a.ntotal + idx_b.ntotal
        print(f"  Combined vectors: {total_vectors:,}")

        # Weighted mode validation
        if use_weighted and not (0.01 <= ratio <= 0.99):
            print(f"\n  Error: --ratio must be between 0.01 and 0.99 for weighted mode (got {ratio})")
            return False

        # Dry-run preview (after loading to get ntotal counts)
        if dry_run:
            if use_weighted and abs(ratio - 0.5) >= 1e-9:
                dominant = "A" if ratio > 0.5 else "B"
                print(f"\n  [DRY RUN] Weighted concatenation preview:")
                print(f"    Ratio: {ratio} (dominant: {dominant})")
                print(f"    Index A: {idx_a.ntotal:,} vectors, Index B: {idx_b.ntotal:,} vectors")
                # Preview replication count
                if ratio > 0.5:
                    multiplier = (ratio * idx_b.ntotal) / ((1 - ratio) * idx_a.ntotal)
                    extra = min(max(0, int(math.ceil(multiplier) - 1)), 20)
                    print(f"    Would replicate A: {extra} extra copies")
                else:
                    multiplier = ((1 - ratio) * idx_a.ntotal) / (ratio * idx_b.ntotal)
                    extra = min(max(0, int(math.ceil(multiplier) - 1)), 20)
                    print(f"    Would replicate B: {extra} extra copies")
            print("\n  [DRY RUN] Would merge indexes successfully")
            return True

        # Reconstruct vectors
        print("  Reconstructing vectors from Index A...")
        vecs_a = idx_a.reconstruct_n(0, idx_a.ntotal)

        print("  Reconstructing vectors from Index B...")
        vecs_b = idx_b.reconstruct_n(0, idx_b.ntotal)

        # Free original indexes to reduce memory pressure
        del idx_a, idx_b
        gc.collect()

        # Combine vectors
        rng = np.random.RandomState(random_seed)

        if use_weighted and abs(ratio - 0.5) >= 1e-9:
            print(f"  Weighted concatenation (ratio={ratio})...")
            all_vecs, desc = replicate_vectors_weighted(
                vecs_a, vecs_b, ratio, max_total=500_000, rng=rng
            )
            print(f"  Mode: {desc}")
            del vecs_a, vecs_b
            gc.collect()
        else:
            all_vecs = np.vstack([vecs_a, vecs_b]).astype("float32")
            print("  Concatenating vectors (equal)...")
            del vecs_a, vecs_b
            gc.collect()

        print(f"  Total shape: {all_vecs.shape}")

        # Shuffle for better index quality (deterministic)
        print("  Shuffling vectors...")
        rng.shuffle(all_vecs)

        # Subsample large datasets to stay within memory limits
        MAX_INDEX_VECTORS = 190_000
        if all_vecs.shape[0] > MAX_INDEX_VECTORS:
            print(
                f"  Large dataset ({all_vecs.shape[0]:,} vectors), "
                f"subsampling to {MAX_INDEX_VECTORS:,}..."
            )
            indices = rng.choice(all_vecs.shape[0], MAX_INDEX_VECTORS, replace=False)
            all_vecs = all_vecs[indices]
            print(f"  Subsampled to {all_vecs.shape[0]:,} vectors")

        # Calculate IVF parameter
        n_ivf = min(int(16 * np.sqrt(all_vecs.shape[0])), all_vecs.shape[0] // 39)
        n_ivf = max(n_ivf, 1)  # Ensure at least 1
        print(f"  IVF clusters: {n_ivf}")

        # Create and train index
        print("  Creating merged index...")
        merged_idx = faiss.index_factory(all_vecs.shape[1], f"IVF{n_ivf},Flat")

        # Set nprobe for search
        index_ivf = faiss.extract_index_ivf(merged_idx)
        index_ivf.nprobe = 1

        print("  Training index...")
        merged_idx.train(all_vecs)

        # Add vectors in batches
        print("  Adding vectors...")
        batch_size = 8192
        for i in range(0, all_vecs.shape[0], batch_size):
            batch = all_vecs[i : i + batch_size]
            merged_idx.add(batch)
            if all_vecs.shape[0] > 100000:
                progress = min(100, int((i + batch_size) / all_vecs.shape[0] * 100))
                count = min(i + batch_size, all_vecs.shape[0])
                print(f"    Adding vectors: {count:,} / {all_vecs.shape[0]:,} ({progress}%)")

        print(f"  Added {merged_idx.ntotal:,} vectors to merged index")

        # Save
        print(f"  Saving to: {output_path}")
        faiss.write_index(merged_idx, output_path)
        print("  Index merge complete!")
        return True

    except Exception as e:
        print(f"\n  Error merging indexes: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Merge RVC voice models and/or FAISS indexes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge two models
  python merge_rvc.py --model-a voice_a.pth --model-b voice_b.pth --ratio 0.6 --output merged.pth

  # Merge two indexes (equal concatenation)
  python merge_rvc.py --index-a voice_a.index --index-b voice_b.index --output merged.index

  # Merge both models and indexes
  python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 \
      --index-a a.index --index-b b.index \
      --output merged.pth --index-output merged.index

  # Merge indexes with weighted concatenation (70% model A features)
  python merge_rvc.py --index-a a.index --index-b b.index --output merged.index \
      --use-weighted --ratio 0.7

  # Validate without merging
  python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 --dry-run
""",
    )

    # Model arguments
    model_group = parser.add_argument_group("Model Merging")
    model_group.add_argument(
        "--model-a",
        type=str,
        help="Path to first model (.pth)",
    )
    model_group.add_argument(
        "--model-b",
        type=str,
        help="Path to second model (.pth)",
    )
    model_group.add_argument(
        "--ratio",
        type=float,
        default=0.5,
        help="Blend ratio (0.0-1.0), higher = more of model A (default: 0.5)",
    )

    # Output arguments
    output_group = parser.add_argument_group("Output")
    output_group.add_argument(
        "--name",
        type=str,
        default=None,
        help='Name for the merged model (default: auto-derived from source model names/metadata)',
    )
    output_group.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help='Output directory (created if needed).  Default: "./<merge_name>"',
    )
    output_group.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for merged model (.pth). Overrides --output-dir.",
    )

    # Index arguments
    index_group = parser.add_argument_group("Index Merging")
    index_group.add_argument(
        "--index-a",
        type=str,
        help="Path to first index (.index)",
    )
    index_group.add_argument(
        "--index-b",
        type=str,
        help="Path to second index (.index)",
    )
    index_group.add_argument(
        "--index-output",
        type=str,
        help="Output path for merged index (.index)",
    )
    index_group.add_argument(
        "--use-weighted",
        action="store_true",
        help="Weight index concatenation by ratio (replicate dominant model's vectors)",
    )
    index_group.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for reproducible vector shuffling (default: 42)",
    )

    # General arguments
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs without creating output files",
    )
    parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help=argparse.SUPPRESS,  # Internal: suppress metadata.json when run as subprocess
    )

    args = parser.parse_args()

    # Validate arguments
    has_model_args = args.model_a or args.model_b
    has_index_args = args.index_a or args.index_b

    if not has_model_args and not has_index_args:
        parser.print_help()
        print("\nError: Must provide either model or index arguments")
        return 1

    # Validate model arguments
    if has_model_args:
        if not args.model_a or not args.model_b:
            print("Error: Both --model-a and --model-b are required for model merging")
            return 1
        if not 0.0 <= args.ratio <= 1.0:
            print(f"Error: --ratio must be between 0.0 and 1.0, got {args.ratio}")
            return 1

    # Validate index arguments
    if has_index_args:
        if not args.index_a or not args.index_b:
            print("Error: Both --index-a and --index-b are required for index merging")
            return 1
        if args.use_weighted:
            if not (0.01 <= args.ratio <= 0.99):
                parser.error(
                    f"--ratio must be between 0.01 and 0.99 when using --use-weighted (got {args.ratio})"
                )

    # --- Auto-naming and output paths ---
    # Determine reference paths for metadata lookup (prefer model paths)
    ref_a = args.model_a or args.index_a
    ref_b = args.model_b or args.index_b
    meta_a = load_model_metadata(ref_a)
    meta_b = load_model_metadata(ref_b)

    merge_name = args.name or derive_merge_name(ref_a, ref_b, args.ratio, meta_a, meta_b)

    # Resolve output paths
    if args.output:
        # Explicit --output overrides everything for the .pth
        model_output = args.output
        model_output_dir = os.path.dirname(os.path.abspath(model_output))
    elif has_model_args and not args.dry_run:
        # Auto-generate: --output-dir or "./<merge_name>/"
        model_output_dir = args.output_dir or merge_name
        os.makedirs(model_output_dir, exist_ok=True)
        model_output = os.path.join(model_output_dir, f"{merge_name}.pth")
    else:
        model_output = ""
        model_output_dir = None

    if args.index_output:
        index_output = args.index_output
    elif has_index_args and not args.dry_run:
        # Same directory as model output, or auto-derived
        idx_dir = model_output_dir or args.output_dir or merge_name
        if not os.path.isdir(idx_dir):
            os.makedirs(idx_dir, exist_ok=True)
        index_output = os.path.join(idx_dir, f"{merge_name}.index")
    else:
        index_output = ""

    # --- Execute merges ---
    success = True
    model_result = None
    index_result = None

    if has_model_args:
        print(f"\n  Merge name: {merge_name}")
        if model_output_dir:
            print(f"  Output dir: {model_output_dir}")

        if not merge_models(
            args.model_a, args.model_b, args.ratio, model_output, args.dry_run
        ):
            success = False
        elif not args.dry_run and torch is not None:
            # Collect model stats for metadata
            ckpt = torch.load(model_output, map_location="cpu", weights_only=True)
            model_result = {
                "layers": len(ckpt.get("weight", {})),
                "sample_rate": str(ckpt.get("sr", "")),
                "f0": ckpt.get("f0", 1),
                "version": ckpt.get("version", ""),
                "vocoder": ckpt.get("vocoder", ""),
                "size_bytes": os.path.getsize(model_output),
                "md5": _md5_file(model_output),
            }

    if has_index_args:
        if has_model_args:
            # PyTorch's memory allocator conflicts with faiss.train().
            # Run index merge in a subprocess with a clean environment.
            import subprocess as sp
            child_env = os.environ.copy()
            child_env["RESING_SKIP_TORCH"] = "1"
            cmd = [
                sys.executable, __file__,
                "--index-a", args.index_a,
                "--index-b", args.index_b,
                "--index-output", index_output,
            ]
            if args.dry_run:
                cmd.append("--dry-run")
            if args.use_weighted:
                cmd.extend(["--use-weighted", "--ratio", str(args.ratio)])
            if args.random_seed != 42:
                cmd.extend(["--random-seed", str(args.random_seed)])
            cmd.append("--skip-metadata")
            result = sp.run(cmd, env=child_env)
            if result.returncode != 0:
                success = False
            elif not args.dry_run and faiss is not None:
                # Collect index stats for metadata (in this process, faiss is safe after torch)
                try:
                    idx = faiss.read_index(index_output)
                    index_result = {
                        "vectors": idx.ntotal,
                        "dimension": idx.d,
                        "mode": "weighted" if args.use_weighted else "equal",
                        "ratio": args.ratio,
                        "size_bytes": os.path.getsize(index_output),
                    }
                except Exception:
                    pass
        else:
            print(f"\n  Merge name: {merge_name}")
            if not merge_indexes(
                args.index_a, args.index_b, index_output, args.dry_run,
                use_weighted=args.use_weighted, ratio=args.ratio, random_seed=args.random_seed,
            ):
                success = False
            elif not args.dry_run and faiss is not None:
                try:
                    idx = faiss.read_index(index_output)
                    index_result = {
                        "vectors": idx.ntotal,
                        "dimension": idx.d,
                        "mode": "weighted" if args.use_weighted else "equal",
                        "ratio": args.ratio,
                        "size_bytes": os.path.getsize(index_output),
                    }
                except Exception:
                    pass

    # Write merge metadata.json (skip in subprocess, parent writes once)
    if success and not args.dry_run and not args.skip_metadata:
        meta_dir = model_output_dir or os.path.dirname(os.path.abspath(index_output))
        if os.path.isdir(meta_dir):
            write_merge_metadata(
                meta_dir, merge_name,
                ref_a, ref_b, args.ratio,
                meta_a, meta_b,
                use_weighted=args.use_weighted,
                random_seed=args.random_seed,
                model_result=model_result,
                index_result=index_result,
            )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
