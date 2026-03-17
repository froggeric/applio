#!/usr/bin/env python3
"""
RVC Model and Index Merger - Standalone CLI Tool

Merges RVC voice models (.pth) and/or FAISS indexes (.index) for voice conversion.

Usage:
    # Merge models only
    python merge_rvc.py --model-a model_a.pth --model-b model_b.pth --ratio 0.5 --output merged.pth

    # Merge indexes only
    python merge_rvc.py --index-a a.index --index-b b.index --output merged.index

    # Merge both
    python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 \
        --index-a a.index --index-b b.index \
        --output merged.pth --index-output merged.index

    # Dry run (validate without merging)
    python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 --dry-run
"""

import argparse
import os
import sys
from collections import OrderedDict
from multiprocessing import cpu_count

import numpy as np
import torch

# Optional dependencies with graceful error handling
try:
    import faiss
except ImportError:
    faiss = None

try:
    from sklearn.cluster import MiniBatchKMeans
except ImportError:
    MiniBatchKMeans = None


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


def merge_indexes(
    path_a: str, path_b: str, output_path: str, dry_run: bool = False
) -> bool:
    """
    Merge two FAISS indexes by reconstructing and reindexing vectors.

    Args:
        path_a: Path to first index (.index)
        path_b: Path to second index (.index)
        output_path: Path for merged index output
        dry_run: If True, only validate without saving

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

        # RVC uses 768-dim embeddings (HuBERT)
        if idx_a.d != 768:
            print(f"  Warning: Expected 768 dimensions, got {idx_a.d}")

        total_vectors = idx_a.ntotal + idx_b.ntotal
        print(f"  Combined vectors: {total_vectors:,}")

        if dry_run:
            print("\n  [DRY RUN] Would merge indexes successfully")
            return True

        # Reconstruct vectors
        print("  Reconstructing vectors from Index A...")
        vecs_a = idx_a.reconstruct_n(0, idx_a.ntotal)

        print("  Reconstructing vectors from Index B...")
        vecs_b = idx_b.reconstruct_n(0, idx_b.ntotal)

        # Concatenate
        print("  Concatenating vectors...")
        all_vecs = np.vstack([vecs_a, vecs_b]).astype("float32")
        print(f"  Total shape: {all_vecs.shape}")

        # Shuffle for better index quality
        print("  Shuffling vectors...")
        np.random.shuffle(all_vecs)

        # KMeans clustering for large datasets
        if all_vecs.shape[0] > 200000:
            if MiniBatchKMeans is None:
                print(
                    "  Warning: sklearn not available, skipping KMeans clustering"
                )
            else:
                print(
                    f"  Large dataset ({all_vecs.shape[0]:,} vectors), applying KMeans clustering..."
                )
                kmeans = MiniBatchKMeans(
                    n_clusters=10000,
                    verbose=True,
                    batch_size=256 * cpu_count(),
                    compute_labels=False,
                    init="random",
                    random_state=42,
                )
                all_vecs = kmeans.fit(all_vecs).cluster_centers_.astype("float32")
                print(f"  Reduced to {all_vecs.shape[0]:,} cluster centers")

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
                print(f"    Progress: {progress}%", end="\r")

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

  # Merge two indexes
  python merge_rvc.py --index-a voice_a.index --index-b voice_b.index --output merged.index

  # Merge both models and indexes
  python merge_rvc.py --model-a a.pth --model-b b.pth --ratio 0.5 \
      --index-a a.index --index-b b.index \
      --output merged.pth --index-output merged.index

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
    model_group.add_argument(
        "--output",
        type=str,
        help="Output path for merged model (.pth)",
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

    # General arguments
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs without creating output files",
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
        if not args.output and not args.dry_run:
            print("Error: --output is required for model merging (or use --dry-run)")
            return 1
        if not 0.0 <= args.ratio <= 1.0:
            print(f"Error: --ratio must be between 0.0 and 1.0, got {args.ratio}")
            return 1

    # Validate index arguments
    if has_index_args:
        if not args.index_a or not args.index_b:
            print("Error: Both --index-a and --index-b are required for index merging")
            return 1
        if not args.index_output and not args.dry_run:
            print(
                "Error: --index-output is required for index merging (or use --dry-run)"
            )
            return 1

    # Execute merges
    success = True

    if has_model_args:
        if not merge_models(
            args.model_a, args.model_b, args.ratio, args.output or "", args.dry_run
        ):
            success = False

    if has_index_args:
        if not merge_indexes(
            args.index_a, args.index_b, args.index_output or "", args.dry_run
        ):
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
