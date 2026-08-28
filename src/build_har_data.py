from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import io
import itertools
import json
import platform
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

import numpy as np
from colorspacious import cspace_convert
from pynndescent import NNDescent
from scipy.spatial.distance import cdist
from scipy.stats import spearmanr
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import pairwise_distances, silhouette_score
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
import sklearn
import umap


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT.parent / "datasets" / "uci-har-smartphones.zip"
SEED = 42
QUALITY_K = (5, 10, 15, 30, 50)
EVAL_SIZE = 2000
UMAP_3D_KEY = "umap3d/equilibrado/seed-42"

PROJECTIONS = {
    "pca/pc1-pc2": {"tech": "pca"},
    "tsne/perplexidade-10/seed-42": {"tech": "tsne", "perplexity": 10},
    "tsne/perplexidade-30/seed-42": {"tech": "tsne", "perplexity": 30},
    "tsne/perplexidade-50/seed-42": {"tech": "tsne", "perplexity": 50},
    "umap/local/seed-42": {"tech": "umap", "n_neighbors": 10, "min_dist": 0.05},
    "umap/equilibrado/seed-42": {"tech": "umap", "n_neighbors": 30, "min_dist": 0.10},
    "umap/amplo/seed-42": {"tech": "umap", "n_neighbors": 100, "min_dist": 0.50},
}

BASE_COLORS = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9")
SYMBOLS = (
    "circle",
    "rect",
    "triangle",
    "diamond",
    "roundRect",
    "path://M-1,-4 L1,-4 L1,-1 L4,-1 L4,1 L1,1 L1,4 L-1,4 L-1,1 L-4,1 L-4,-1 L-1,-1 Z",
)
LABELS_PT = {
    "WALKING": "Andando",
    "WALKING_UPSTAIRS": "Subindo escada",
    "WALKING_DOWNSTAIRS": "Descendo escada",
    "SITTING": "Sentado",
    "STANDING": "Em pé",
    "LAYING": "Deitado",
}
SIGNAL_CHANNELS = (
    ("body_acc_x", "Aceleração corporal X", "g"),
    ("body_acc_y", "Aceleração corporal Y", "g"),
    ("body_acc_z", "Aceleração corporal Z", "g"),
    ("body_gyro_x", "Giroscópio X", "rad/s"),
    ("body_gyro_y", "Giroscópio Y", "rad/s"),
    ("body_gyro_z", "Giroscópio Z", "rad/s"),
)


@dataclass
class HarData:
    features: np.ndarray
    inertial_signals: np.ndarray
    label_ids: np.ndarray
    labels: np.ndarray
    subjects: np.ndarray
    splits: np.ndarray
    source_rows: np.ndarray
    activity_names: list[str]
    feature_names: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera projeções reais do HAR para o protótipo.")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def loadtxt(archive: ZipFile, member: str, dtype: type[np.floating] | type[np.integer]) -> np.ndarray:
    return np.loadtxt(io.BytesIO(archive.read(member)), dtype=dtype)


def load_har(outer_path: Path) -> HarData:
    with ZipFile(outer_path) as outer:
        inner_bytes = outer.read("UCI HAR Dataset.zip")
    with ZipFile(io.BytesIO(inner_bytes)) as archive:
        prefix = "UCI HAR Dataset/"
        activity_lines = archive.read(prefix + "activity_labels.txt").decode("utf-8").splitlines()
        activities = {int(line.split()[0]): line.split(maxsplit=1)[1] for line in activity_lines}
        feature_lines = archive.read(prefix + "features.txt").decode("utf-8").splitlines()
        feature_names = [line.split(maxsplit=1)[1] for line in feature_lines]

        arrays: dict[str, np.ndarray] = {}
        signal_arrays: dict[str, np.ndarray] = {}
        for split in ("train", "test"):
            base = f"{prefix}{split}/"
            arrays[f"X_{split}"] = loadtxt(archive, base + f"X_{split}.txt", np.float32)
            arrays[f"y_{split}"] = loadtxt(archive, base + f"y_{split}.txt", np.int16)
            arrays[f"subject_{split}"] = loadtxt(archive, base + f"subject_{split}.txt", np.int16)
            for channel, _, _ in SIGNAL_CHANNELS:
                signal_arrays[f"{channel}_{split}"] = loadtxt(
                    archive,
                    base + f"Inertial Signals/{channel}_{split}.txt",
                    np.float32,
                )

    features = np.vstack([arrays["X_train"], arrays["X_test"]]).astype(np.float32, copy=False)
    inertial_signals = np.stack(
        [
            np.vstack(
                [signal_arrays[f"{channel}_train"], signal_arrays[f"{channel}_test"]]
            )
            for channel, _, _ in SIGNAL_CHANNELS
        ],
        axis=1,
    ).astype(np.float32, copy=False)
    label_ids = np.concatenate([arrays["y_train"], arrays["y_test"]]).astype(np.int16, copy=False)
    subjects = np.concatenate([arrays["subject_train"], arrays["subject_test"]]).astype(np.int16, copy=False)
    splits = np.array(["train"] * len(arrays["X_train"]) + ["test"] * len(arrays["X_test"]), dtype=object)
    source_rows = np.concatenate([
        np.arange(1, len(arrays["X_train"]) + 1, dtype=np.int32),
        np.arange(1, len(arrays["X_test"]) + 1, dtype=np.int32),
    ])
    labels = np.array([activities[int(value)] for value in label_ids], dtype=object)

    if features.shape != (10299, 561):
        raise ValueError(f"Dimensão HAR inesperada: {features.shape}")
    if inertial_signals.shape != (10299, 6, 128):
        raise ValueError(f"Dimensão dos sinais inerciais inesperada: {inertial_signals.shape}")
    if not np.isfinite(features).all():
        raise ValueError("HAR contém valores não finitos.")
    if not np.isfinite(inertial_signals).all():
        raise ValueError("Sinais inerciais do HAR contêm valores não finitos.")

    return HarData(
        features=features,
        inertial_signals=inertial_signals,
        label_ids=label_ids,
        labels=labels,
        subjects=subjects,
        splits=splits,
        source_rows=source_rows,
        activity_names=[activities[index] for index in sorted(activities)],
        feature_names=feature_names,
    )


def cache_array(
    cache_dir: Path,
    name: str,
    force: bool,
    compute: Callable[[], tuple[np.ndarray, dict[str, float | int]]],
) -> tuple[np.ndarray, dict[str, float | int]]:
    path = cache_dir / f"{name}.npz"
    if path.exists() and not force:
        with np.load(path, allow_pickle=False) as saved:
            metadata = json.loads(str(saved["metadata"].item()))
            return saved["array"], metadata
    array, metadata = compute()
    np.savez_compressed(path, array=array.astype(np.float32), metadata=json.dumps(metadata))
    return array, metadata


def timed(call: Callable[[], np.ndarray]) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def compute_rank_structure(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    distances = pairwise_distances(values, metric="euclidean", n_jobs=-1)
    order = np.argsort(distances, axis=1).astype(np.int32, copy=False)
    ranks = np.empty_like(order, dtype=np.int32)
    rows = np.arange(len(values), dtype=np.int32)[:, None]
    ranks[rows, order] = np.arange(len(values), dtype=np.int32)[None, :]
    return order, ranks


def quality_metrics(
    high_values: np.ndarray,
    low_values: np.ndarray,
    labels: np.ndarray,
    high_order: np.ndarray,
    high_ranks: np.ndarray,
    random_state: int,
) -> dict[str, object]:
    low_order, low_ranks = compute_rank_structure(low_values)
    sample_count = len(low_values)
    rows = np.arange(sample_count)[:, None]
    trust: dict[str, float] = {}
    continuity: dict[str, float] = {}
    overlap: dict[str, float] = {}

    for neighbor_count in QUALITY_K:
        denominator = sample_count * neighbor_count * (2 * sample_count - 3 * neighbor_count - 1)
        low_neighbors = low_order[:, 1 : neighbor_count + 1]
        high_neighbors = high_order[:, 1 : neighbor_count + 1]

        high_rank_for_low = high_ranks[rows, low_neighbors]
        low_rank_for_high = low_ranks[rows, high_neighbors]
        trust_penalty = np.maximum(high_rank_for_low - neighbor_count, 0).sum(dtype=np.float64)
        continuity_penalty = np.maximum(low_rank_for_high - neighbor_count, 0).sum(dtype=np.float64)

        trust[str(neighbor_count)] = float(1 - (2 * trust_penalty / denominator))
        continuity[str(neighbor_count)] = float(1 - (2 * continuity_penalty / denominator))
        overlap[str(neighbor_count)] = float(np.mean(np.sum(high_rank_for_low <= neighbor_count, axis=1) / neighbor_count))

    rng = np.random.default_rng(random_state)
    first = rng.integers(0, sample_count, size=50_000)
    second = rng.integers(0, sample_count, size=50_000)
    valid = first != second
    first, second = first[valid], second[valid]
    high_dist = np.linalg.norm(high_values[first] - high_values[second], axis=1)
    low_dist = np.linalg.norm(low_values[first] - low_values[second], axis=1)
    distance_correlation = float(spearmanr(high_dist, low_dist).statistic)

    return {
        "trustworthiness": trust,
        "continuity": continuity,
        "knn_overlap": overlap,
        "distance_spearman": distance_correlation,
        "silhouette_labels_2d": float(silhouette_score(low_values, labels, metric="euclidean")),
    }


def nearest_neighbors(values: np.ndarray, count: int) -> np.ndarray:
    model = NearestNeighbors(n_neighbors=count + 1, metric="euclidean", n_jobs=-1)
    indices = model.fit(values).kneighbors(values, return_distance=False)
    result = np.empty((len(values), count), dtype=np.int32)
    for row_index, row in enumerate(indices):
        filtered = row[row != row_index][:count]
        if len(filtered) != count:
            raise RuntimeError("Não foi possível remover o próprio ponto da lista k-NN.")
        result[row_index] = filtered
    return result


def class_adjacency(
    labels: np.ndarray,
    activity_names: list[str],
    original_neighbors: np.ndarray,
    embeddings: dict[str, np.ndarray],
) -> np.ndarray:
    class_index = {name: index for index, name in enumerate(activity_names)}
    encoded = np.array([class_index[name] for name in labels], dtype=np.int16)
    adjacency = np.zeros((len(activity_names), len(activity_names)), dtype=np.float64)

    def accumulate(neighbors: np.ndarray, weight: float) -> None:
        for source in range(len(labels)):
            source_class = encoded[source]
            target_classes = encoded[neighbors[source]]
            for target_class in target_classes:
                if source_class == target_class:
                    continue
                adjacency[source_class, target_class] += weight
                adjacency[target_class, source_class] += weight

    accumulate(original_neighbors, 2.0)
    for embedding in embeddings.values():
        accumulate(nearest_neighbors(embedding, 10), 1.0)
    return adjacency


def hex_to_rgb(color: str) -> np.ndarray:
    return np.array([int(color[index : index + 2], 16) for index in (1, 3, 5)], dtype=np.float64) / 255.0


def rgb_to_hex(rgb: np.ndarray) -> str:
    values = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    return "#" + "".join(f"{value:02X}" for value in values)


def monochromacy(rgb: np.ndarray) -> np.ndarray:
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
    gray = np.where(luminance <= 0.0031308, 12.92 * luminance, 1.055 * luminance ** (1 / 2.4) - 0.055)
    return np.repeat(gray[:, None], 3, axis=1)


def simulate_palette(rgb: np.ndarray) -> dict[str, np.ndarray]:
    simulations = {"padrao": rgb}
    cvd_types = {
        "protanopia": "protanomaly",
        "deuteranopia": "deuteranomaly",
        "tritanopia": "tritanomaly",
    }
    for output_name, cvd_type in cvd_types.items():
        simulated = cspace_convert(
            rgb,
            {"name": "sRGB1+CVD", "cvd_type": cvd_type, "severity": 100},
            "sRGB1",
        )
        simulations[output_name] = np.clip(simulated, 0, 1)
    simulations["monocromacia"] = monochromacy(rgb)
    return simulations


def optimize_colors(activity_names: list[str], adjacency: np.ndarray) -> tuple[list[dict[str, object]], dict[str, object]]:
    rgb = np.stack([hex_to_rgb(color) for color in BASE_COLORS])
    simulations = simulate_palette(rgb)
    lab = {name: cspace_convert(values, "sRGB1", "CIELab") for name, values in simulations.items()}
    distances = {name: cdist(values, values, metric="euclidean") for name, values in lab.items()}
    upper = np.triu_indices(len(activity_names), 1)
    pair_weights = adjacency[upper]
    max_weight = float(pair_weights.max()) if pair_weights.size and pair_weights.max() > 0 else 1.0
    importance = 0.2 + 0.8 * (pair_weights / max_weight)

    best_score = -np.inf
    best_permutation: tuple[int, ...] | None = None
    best_minimum = 0.0
    for permutation in itertools.permutations(range(len(activity_names))):
        adjusted: list[float] = []
        raw: list[float] = []
        for mode, matrix in distances.items():
            assigned = matrix[np.ix_(permutation, permutation)][upper]
            adjusted.extend((assigned / importance).tolist())
            raw.extend(assigned.tolist())
        score = float(min(adjusted) + 0.01 * np.average(raw, weights=np.tile(pair_weights + 1, len(distances))))
        if score > best_score:
            best_score = score
            best_minimum = float(min(raw))
            best_permutation = permutation

    if best_permutation is None:
        raise RuntimeError("Otimização de cores não encontrou solução.")

    classes: list[dict[str, object]] = []
    for index, activity in enumerate(activity_names):
        color_index = best_permutation[index]
        classes.append(
            {
                "id": activity,
                "label_pt": LABELS_PT.get(activity, activity.replace("_", " ").title()),
                "cor": BASE_COLORS[color_index],
                "cor_cvd": {
                    mode: rgb_to_hex(values[color_index])
                    for mode, values in simulations.items()
                    if mode != "padrao"
                },
                "simbolo": SYMBOLS[index],
            }
        )
    audit = {
        "metodo": "720 permutações; maximização da pior distância CIELAB ponderada pela adjacência entre classes",
        "score": best_score,
        "menor_delta_e_simulado": best_minimum,
        "permutacao_indices": list(best_permutation),
        "matriz_adjacencia": np.rint(adjacency).astype(int).tolist(),
    }
    return classes, audit


def compute_original_neighbors(values: np.ndarray, cache_dir: Path, force: bool) -> tuple[np.ndarray, dict[str, float | int]]:
    path = cache_dir / "neighbors-original-k10.npz"
    if path.exists() and not force:
        with np.load(path, allow_pickle=False) as saved:
            return saved["indices"], json.loads(str(saved["metadata"].item()))

    started = time.perf_counter()
    index = NNDescent(
        values,
        n_neighbors=15,
        metric="euclidean",
        random_state=SEED,
        n_jobs=-1,
        low_memory=True,
        verbose=True,
    )
    raw_indices, _ = index.neighbor_graph
    indices = np.empty((len(values), 10), dtype=np.int32)
    for row_index, row in enumerate(raw_indices):
        filtered = row[row != row_index][:10]
        if len(filtered) != 10:
            raise RuntimeError("NNDescent retornou menos de dez vizinhos úteis.")
        indices[row_index] = filtered
    metadata = {"runtime_seconds": time.perf_counter() - started, "n_neighbors_index": 15}
    np.savez_compressed(path, indices=indices, metadata=json.dumps(metadata))
    return indices, metadata


def projection_coordinates(
    scaled: np.ndarray,
    pca50: np.ndarray,
    pca_model: PCA,
    cache_dir: Path,
    force: bool,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, object]]]:
    embeddings: dict[str, np.ndarray] = {"pca/pc1-pc2": pca50[:, :2].copy()}
    metadata: dict[str, dict[str, object]] = {
        "pca/pc1-pc2": {
            "tempo_ms": int(round(getattr(pca_model, "_runtime_seconds", 0.0) * 1000)),
            "variancia_explicada": pca_model.explained_variance_ratio_[:2].astype(float).tolist(),
            "variancia_explicada_acumulada": float(pca_model.explained_variance_ratio_[:2].sum()),
            "parametros": {"entrada": "561D padronizado", "solver": "randomized"},
        }
    }

    for key, config in PROJECTIONS.items():
        if config["tech"] == "pca":
            continue
        cache_name = key.replace("/", "__").replace(".", "p")
        if config["tech"] == "tsne":
            perplexity = int(config["perplexity"])

            def compute_tsne(perplexity: int = perplexity) -> tuple[np.ndarray, dict[str, float | int]]:
                model = TSNE(
                    n_components=2,
                    perplexity=perplexity,
                    learning_rate="auto",
                    init="pca",
                    max_iter=1000,
                    metric="euclidean",
                    method="barnes_hut",
                    angle=0.5,
                    random_state=SEED,
                    n_jobs=-1,
                    verbose=1,
                )
                result, elapsed = timed(lambda: model.fit_transform(pca50))
                return result, {"runtime_seconds": elapsed, "kl_divergence": float(model.kl_divergence_)}

            embedding, timing = cache_array(cache_dir, cache_name, force, compute_tsne)
            metadata[key] = {
                "tempo_ms": int(round(float(timing["runtime_seconds"]) * 1000)),
                "kl_divergence": float(timing["kl_divergence"]),
                "parametros": {
                    "perplexidade": perplexity,
                    "entrada": "PCA50",
                    "learning_rate": "auto",
                    "max_iter": 1000,
                    "seed": SEED,
                },
            }
        else:
            neighbor_count = int(config["n_neighbors"])
            min_dist = float(config["min_dist"])

            def compute_umap(
                neighbor_count: int = neighbor_count,
                min_dist: float = min_dist,
            ) -> tuple[np.ndarray, dict[str, float | int]]:
                model = umap.UMAP(
                    n_components=2,
                    n_neighbors=neighbor_count,
                    min_dist=min_dist,
                    metric="euclidean",
                    init="spectral",
                    random_state=SEED,
                    low_memory=True,
                    n_jobs=1,
                    verbose=True,
                )
                result, elapsed = timed(lambda: model.fit_transform(scaled))
                return result, {"runtime_seconds": elapsed}

            embedding, timing = cache_array(cache_dir, cache_name, force, compute_umap)
            metadata[key] = {
                "tempo_ms": int(round(float(timing["runtime_seconds"]) * 1000)),
                "parametros": {
                    "n_neighbors": neighbor_count,
                    "min_dist": min_dist,
                    "metric": "euclidean",
                    "entrada": "561D padronizado",
                    "seed": SEED,
                },
            }
        embeddings[key] = embedding.astype(np.float32, copy=False)
    return embeddings, metadata


def projection_umap_3d(
    scaled: np.ndarray,
    cache_dir: Path,
    force: bool,
) -> tuple[np.ndarray, dict[str, object]]:
    cache_name = UMAP_3D_KEY.replace("/", "__").replace(".", "p")

    def compute() -> tuple[np.ndarray, dict[str, float]]:
        model = umap.UMAP(
            n_components=3,
            n_neighbors=30,
            min_dist=0.10,
            metric="euclidean",
            init="spectral",
            random_state=SEED,
            low_memory=True,
            n_jobs=1,
            verbose=True,
        )
        result, elapsed = timed(lambda: model.fit_transform(scaled))
        return result, {"runtime_seconds": elapsed}

    embedding, timing = cache_array(cache_dir, cache_name, force, compute)
    metadata: dict[str, object] = {
        "tempo_ms": int(round(float(timing["runtime_seconds"]) * 1000)),
        "parametros": {
            "n_components": 3,
            "n_neighbors": 30,
            "min_dist": 0.10,
            "metric": "euclidean",
            "entrada": "561D padronizado",
            "seed": SEED,
        },
    }
    return embedding.astype(np.float32, copy=False), metadata


def json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def deflate_base64(values: np.ndarray) -> str:
    raw = np.ascontiguousarray(values).tobytes(order="C")
    return base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    cache_dir = root / "results" / "cache"
    results_dir = root / "results"
    web_dir = root / "web"
    cache_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)

    print("[1/9] Carregando HAR oficial…", flush=True)
    data = load_har(args.archive)
    ids = np.array([f"har_{index:05d}" for index in range(1, len(data.features) + 1)], dtype=object)

    print("[2/9] Padronizando os 561 atributos…", flush=True)
    scaled = StandardScaler().fit_transform(data.features).astype(np.float32, copy=False)

    print("[3/9] Calculando PCA50…", flush=True)
    pca_cache = cache_dir / "pca50.npz"
    if pca_cache.exists() and not args.force:
        with np.load(pca_cache, allow_pickle=False) as saved:
            pca50 = saved["array"]
            pca_metadata = json.loads(str(saved["metadata"].item()))
        pca_model = PCA(n_components=50, svd_solver="randomized", random_state=SEED)
        pca_model.explained_variance_ratio_ = np.array(pca_metadata["explained_variance_ratio"], dtype=np.float64)
        pca_model._runtime_seconds = float(pca_metadata["runtime_seconds"])
    else:
        pca_model = PCA(n_components=50, svd_solver="randomized", random_state=SEED)
        pca50, elapsed = timed(lambda: pca_model.fit_transform(scaled))
        pca_model._runtime_seconds = elapsed
        pca_metadata = {
            "runtime_seconds": elapsed,
            "explained_variance_ratio": pca_model.explained_variance_ratio_.astype(float).tolist(),
        }
        np.savez_compressed(pca_cache, array=pca50.astype(np.float32), metadata=json.dumps(pca_metadata))
    pca50 = pca50.astype(np.float32, copy=False)

    print("[4/9] Calculando PCA, t-SNE e UMAP 2D…", flush=True)
    embeddings, metrics = projection_coordinates(scaled, pca50, pca_model, cache_dir, args.force)

    print("[5/9] Calculando UMAP 3D…", flush=True)
    embedding_3d, metrics_3d = projection_umap_3d(scaled, cache_dir, args.force)

    print("[6/9] Calculando vizinhos originais aproximados…", flush=True)
    original_neighbors, neighbor_metadata = compute_original_neighbors(scaled, cache_dir, args.force)

    print("[7/9] Avaliando embeddings em subamostra estratificada…", flush=True)
    splitter = StratifiedShuffleSplit(n_splits=1, train_size=EVAL_SIZE, random_state=SEED)
    evaluation_indices, _ = next(splitter.split(scaled, data.labels))
    high_eval = scaled[evaluation_indices]
    labels_eval = data.labels[evaluation_indices]
    high_order, high_ranks = compute_rank_structure(high_eval)
    for key, embedding in embeddings.items():
        print(f"  métricas: {key}", flush=True)
        quality = quality_metrics(
            high_eval,
            embedding[evaluation_indices],
            labels_eval,
            high_order,
            high_ranks,
            SEED,
        )
        metrics[key].update(quality)
        metrics[key]["trustworthiness_k10"] = quality["trustworthiness"]["10"]
        metrics[key]["continuity_k10"] = quality["continuity"]["10"]

    print(f"  métricas: {UMAP_3D_KEY}", flush=True)
    quality_3d = quality_metrics(
        high_eval,
        embedding_3d[evaluation_indices],
        labels_eval,
        high_order,
        high_ranks,
        SEED,
    )
    quality_3d["silhouette_labels_3d"] = quality_3d.pop("silhouette_labels_2d")
    metrics_3d.update(quality_3d)
    metrics_3d["trustworthiness_k10"] = quality_3d["trustworthiness"]["10"]
    metrics_3d["continuity_k10"] = quality_3d["continuity"]["10"]

    print("[8/9] Otimizando cores segundo adjacência e simulações CVD…", flush=True)
    adjacency = class_adjacency(data.labels, data.activity_names, original_neighbors, embeddings)
    classes, color_audit = optimize_colors(data.activity_names, adjacency)

    print("[9/9] Exportando har-data.js e métricas…", flush=True)
    rounded = {key: np.round(values.astype(np.float64), 5) for key, values in embeddings.items()}
    rounded_3d = np.round(embedding_3d.astype(np.float64), 5)
    feature_multiplier = 12.0
    quantized_features = np.rint(scaled * feature_multiplier).clip(-127, 127).astype(np.int8)
    signal_max = np.max(np.abs(data.inertial_signals), axis=(0, 2)).astype(np.float64)
    signal_multipliers = 32767.0 / np.maximum(signal_max, 1e-12)
    quantized_signals = np.rint(
        data.inertial_signals * signal_multipliers[None, :, None]
    ).clip(-32767, 32767).astype("<i2")
    activity_means = {
        activity: np.round(scaled[data.labels == activity].mean(axis=0), 4).astype(float).tolist()
        for activity in data.activity_names
    }
    records: list[dict[str, object]] = []
    for index, sample_id in enumerate(ids):
        records.append(
            {
                "id": str(sample_id),
                "label": str(data.labels[index]),
                "meta": {
                    "subject": int(data.subjects[index]),
                    "split": str(data.splits[index]),
                    "source_row": int(data.source_rows[index]),
                },
                "projecoes": {
                    key: [float(values[index, 0]), float(values[index, 1])]
                    for key, values in rounded.items()
                },
                "projecoes_3d": {
                    UMAP_3D_KEY: [
                        float(rounded_3d[index, 0]),
                        float(rounded_3d[index, 1]),
                        float(rounded_3d[index, 2]),
                    ]
                },
                "vizinhos_originais_k10": [str(ids[neighbor]) for neighbor in original_neighbors[index]],
            }
        )

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "umap_learn": importlib.metadata.version("umap-learn"),
        "pynndescent": importlib.metadata.version("pynndescent"),
        "colorspacious": importlib.metadata.version("colorspacious"),
    }
    payload = {
        "dataset": {
            "id": "har",
            "nome": "Human Activity Recognition Using Smartphones — dados reais",
            "n_amostras_total": len(records),
            "n_features_originais": data.features.shape[1],
            "participantes": int(np.unique(data.subjects).size),
            "fonte": "UCI Machine Learning Repository, DOI 10.24432/C54S4K",
            "classes": classes,
        },
        "protocolo": {
            "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
            "archive_sha256": sha256(args.archive),
            "seed": SEED,
            "preprocessamento": "StandardScaler nos 561 atributos",
            "tsne_entrada": "PCA50 calculado a partir dos atributos padronizados",
            "umap_entrada": "561 atributos padronizados",
            "umap_3d": {
                "chave": UMAP_3D_KEY,
                "n_components": 3,
                "n_neighbors": 30,
                "min_dist": 0.10,
            },
            "rotulos_usados_no_fit": False,
            "vizinhos_originais": "NNDescent aproximado nos 561 atributos padronizados",
            "avaliacao_amostras": EVAL_SIZE,
            "avaliacao_k": list(QUALITY_K),
            "versoes": versions,
            "vizinhos_runtime_seconds": neighbor_metadata["runtime_seconds"],
            "otimizacao_cores": color_audit,
        },
        "interpretacao": {
            "feature_names": data.feature_names,
            "features": {
                "shape": list(quantized_features.shape),
                "encoding": "deflate+base64/int8",
                "quantization_multiplier": feature_multiplier,
                "clipped_fraction": float(np.mean(np.abs(scaled * feature_multiplier) > 127)),
                "data": deflate_base64(quantized_features),
            },
            "activity_mean_z": activity_means,
            "signals": {
                "shape": list(quantized_signals.shape),
                "encoding": "deflate+base64/int16-le",
                "sampling_hz": 50,
                "window_seconds": 2.56,
                "channels": [
                    {"id": channel, "label": label, "unit": unit}
                    for channel, label, unit in SIGNAL_CHANNELS
                ],
                "quantization_multipliers": signal_multipliers.tolist(),
                "data": deflate_base64(quantized_signals),
            },
        },
        "amostras": records,
        "metricas": metrics,
        "metricas_3d": {UMAP_3D_KEY: metrics_3d},
    }
    payload = json_ready(payload)
    js = (
        "/* GERADO AUTOMATICAMENTE. HAR oficial: 10.299 amostras; não editar manualmente. */\n"
        "window.HAR_DADOS="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + ";\n"
    )
    (web_dir / "har-data.js").write_text(js, encoding="utf-8")
    (results_dir / "metrics.json").write_text(
        json.dumps(
            {
                "protocolo": payload["protocolo"],
                "metricas": metrics,
                "metricas_3d": payload["metricas_3d"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Dados: {web_dir / 'har-data.js'} ({(web_dir / 'har-data.js').stat().st_size / 1024 / 1024:.2f} MiB)")


if __name__ == "__main__":
    main()
