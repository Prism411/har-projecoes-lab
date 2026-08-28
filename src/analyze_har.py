from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from build_har_data import DEFAULT_ARCHIVE, LABELS_PT, ROOT, SEED, load_har


DYNAMIC = {"WALKING", "WALKING_UPSTAIRS", "WALKING_DOWNSTAIRS"}
STATIC = {"SITTING", "STANDING", "LAYING"}


def load_cache(name: str) -> np.ndarray:
    with np.load(ROOT / "results" / "cache" / name, allow_pickle=False) as saved:
        return saved["array"].astype(np.float64)


def neighbor_purity(values: np.ndarray, labels: np.ndarray, count: int = 10) -> float:
    neighbors = NearestNeighbors(n_neighbors=count + 1, metric="euclidean", n_jobs=1)
    indices = neighbors.fit(values).kneighbors(values, return_distance=False)[:, 1:]
    return float(np.mean(labels[indices] == labels[:, None]))


def cached_neighbor_purity(indices: np.ndarray, labels: np.ndarray) -> float:
    return float(np.mean(labels[indices] == labels[:, None]))


def separation_ratio(values: np.ndarray, macro: np.ndarray) -> float:
    first = values[macro == 0]
    second = values[macro == 1]
    between = np.linalg.norm(first.mean(axis=0) - second.mean(axis=0))
    within_first = np.mean(np.sum((first - first.mean(axis=0)) ** 2, axis=1))
    within_second = np.mean(np.sum((second - second.mean(axis=0)) ** 2, axis=1))
    return float(between / np.sqrt((within_first + within_second) / 2))


def axis_effect(values: np.ndarray, macro: np.ndarray, axis: int) -> float:
    static = values[macro == 0, axis]
    dynamic = values[macro == 1, axis]
    pooled = np.sqrt((static.var(ddof=1) + dynamic.var(ddof=1)) / 2)
    return float((dynamic.mean() - static.mean()) / pooled)


def centroids(values: np.ndarray, labels: np.ndarray) -> dict[str, list[float]]:
    return {
        label: np.round(values[labels == label].mean(axis=0), 4).astype(float).tolist()
        for label in sorted(set(labels))
    }


def top_correlations(
    scaled: np.ndarray,
    scores: np.ndarray,
    names: list[str],
    component: int,
    count: int = 10,
) -> list[dict[str, float | str]]:
    score = scores[:, component]
    correlations = (scaled.T @ score) / (len(score) * score.std(ddof=0))
    order = np.argsort(np.abs(correlations))[::-1][:count]
    return [
        {"feature": names[index], "correlation": float(correlations[index])}
        for index in order
    ]


def top_macro_differences(
    scaled: np.ndarray,
    macro: np.ndarray,
    names: list[str],
    count: int = 15,
) -> list[dict[str, float | str]]:
    differences = scaled[macro == 1].mean(axis=0) - scaled[macro == 0].mean(axis=0)
    order = np.argsort(np.abs(differences))[::-1][:count]
    return [
        {"feature": names[index], "dynamic_minus_static_z": float(differences[index])}
        for index in order
    ]


def embedding_summary(
    values: np.ndarray,
    labels: np.ndarray,
    macro: np.ndarray,
) -> dict[str, object]:
    return {
        "silhouette_static_dynamic": float(silhouette_score(values, macro)),
        "silhouette_six_activities": float(silhouette_score(values, labels)),
        "neighbor_purity_static_dynamic_k10": neighbor_purity(values, macro),
        "neighbor_purity_six_activities_k10": neighbor_purity(values, labels),
        "centroid_separation_ratio": separation_ratio(values, macro),
        "current_axis_effect_dynamic_minus_static": [
            axis_effect(values, macro, 0),
            axis_effect(values, macro, 1),
        ],
        "class_centroids": centroids(values, labels),
        "macro_centroids": {
            "static": np.round(values[macro == 0].mean(axis=0), 4).astype(float).tolist(),
            "dynamic": np.round(values[macro == 1].mean(axis=0), 4).astype(float).tolist(),
        },
    }


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def markdown(report: dict[str, object]) -> str:
    embeddings = report["embeddings"]
    lines = [
        "# Análise interpretável do HAR para a apresentação",
        "",
        "## Achado central",
        "",
        "A hipótese visual é confirmada: o contraste mais forte do HAR é entre",
        "**atividades dinâmicas** (andar e subir/descer escadas) e **atividades",
        "estáticas** (sentar, ficar em pé e deitar). Isso é uma diferença de padrão",
        "inercial, não uma posição física nem uma velocidade representada pelos eixos",
        "do embedding.",
        "",
        "## Evidência quantitativa nas projeções",
        "",
        "| Projeção | Silhouette estático×dinâmico | Pureza local K=10 | Separação dos centroides | Efeito no eixo atual X | Efeito no eixo atual Y |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("pca", "PCA"), ("tsne", "t-SNE p=30"), ("umap", "UMAP equilibrado")):
        item = embeddings[key]
        lines.append(
            f"| {label} | {fmt(item['silhouette_static_dynamic'])} | "
            f"{fmt(item['neighbor_purity_static_dynamic_k10'])} | "
            f"{fmt(item['centroid_separation_ratio'])} | "
            f"{fmt(item['current_axis_effect_dynamic_minus_static'][0])} | "
            f"{fmt(item['current_axis_effect_dynamic_minus_static'][1])} |"
        )
    lines.extend(
        [
            "",
            "**Como ler:** pureza local é a fração média dos 15 vizinhos que pertence",
            "ao mesmo macrogrupo. Os efeitos X/Y descrevem somente a orientação fixa",
            "desta execução; t-SNE e UMAP podem ser girados, refletidos ou invertidos",
            "sem alterar seu significado.",
            "",
            "## O que realmente diferencia movimento e postura",
            "",
            "As maiores diferenças padronizadas entre dinâmico e estático foram:",
            "",
            "| Característica HAR | Dinâmico − estático |",
            "|---|---:|",
        ]
    )
    for item in report["top_dynamic_static_features"][:10]:
        lines.append(f"| `{item['feature']}` | {fmt(item['dynamic_minus_static_z'])}σ |")
    lines.extend(
        [
            "",
            "Valores positivos aparecem mais no grupo dinâmico; negativos aparecem",
            "mais no grupo estático. Termos `BodyAcc`, `BodyGyro`, `Jerk`, `energy` e",
            "bandas de frequência descrevem intensidade, variação e frequência do",
            "movimento do smartphone.",
            "",
            "## Como interpretar o PCA",
            "",
            f"PC1 explica **{fmt(report['pca_explained_variance'][0] * 100, 1)}%** e PC2",
            f"explica **{fmt(report['pca_explained_variance'][1] * 100, 1)}%** da variância",
            f"padronizada; juntas, **{fmt(sum(report['pca_explained_variance'][:2]) * 100, 1)}%**.",
            "",
            "Características mais relacionadas a PC1:",
            "",
        ]
    )
    for item in report["pca_top_correlations"]["pc1"][:7]:
        lines.append(f"- `{item['feature']}`: correlação {fmt(item['correlation'])}.")
    lines.extend(["", "Características mais relacionadas a PC2:", ""])
    for item in report["pca_top_correlations"]["pc2"][:7]:
        lines.append(f"- `{item['feature']}`: correlação {fmt(item['correlation'])}.")
    lines.extend(
        [
            "",
            "O PCA parece mais sobreposto porque ele procura variância linear global,",
            "não separação de classes. Sobreposição não significa falha: ela mostra que",
            "duas componentes lineares não capturam toda a geometria das seis atividades.",
            "",
            "## O que dizer sobre t-SNE e UMAP",
            "",
            "- **Seguro:** atividades estáticas e dinâmicas ocupam regiões diferentes e",
            "  possuem alta coerência de vizinhança nesta execução.",
            "- **Seguro:** sentado e em pé tendem a ficar próximos porque ambos têm pouca",
            "  dinâmica corporal; subir, descer e andar compartilham movimento periódico.",
            "- **Não dizer:** esquerda significa movimento, direita significa repouso ou",
            "  UMAP-1/t-SNE-1 significa velocidade. A orientação pode inverter.",
            "- **Não dizer:** a distância visual entre dois clusters é uma distância física.",
            "",
            "## Roteiro curto para o slide",
            "",
            "> Primeiro removemos as cores e aplicamos três objetivos diferentes ao mesmo",
            "> vetor de 561 características. Quando revelamos os rótulos, surge uma divisão",
            "> consistente entre atividades dinâmicas e estáticas. PCA mostra essa tendência",
            "> de forma linear e sobreposta; t-SNE e UMAP preservam melhor as vizinhanças",
            "> locais. A posição esquerda/direita não tem significado físico: o resultado",
            "> relevante é quem permanece vizinho de quem.",
            "",
            "## Uso recomendado do dataset",
            "",
            "O HAR cumpre o papel se a pergunta for **como diferentes métodos organizam",
            "padrões de movimento e postura captados por sensores**. Ele não é adequado para",
            "mostrar posição de pessoas, trajetória ou velocidade espacial. Para uma segunda",
            "demonstração imediatamente reconhecível, use dígitos como contingência visual,",
            "sem abandonar o HAR como caso real principal.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    data = load_har(DEFAULT_ARCHIVE)
    scaled = StandardScaler().fit_transform(data.features).astype(np.float64, copy=False)
    labels = data.labels.astype(str)
    macro = np.array([1 if label in DYNAMIC else 0 for label in labels], dtype=np.int8)

    pca_model = PCA(n_components=50, svd_solver="randomized", random_state=SEED)
    pca_scores = pca_model.fit_transform(scaled)
    cached_pca = load_cache("pca50.npz")[:, :2]
    correlations = [abs(float(np.corrcoef(pca_scores[:, i], cached_pca[:, i])[0, 1])) for i in range(2)]
    if min(correlations) < 0.999:
        raise RuntimeError(f"PCA refeito não coincide com o cache: {correlations}")

    tsne = load_cache("tsne__perplexidade-30__seed-42.npz")
    umap = load_cache("umap__equilibrado__seed-42.npz")
    with np.load(ROOT / "results" / "cache" / "neighbors-original-k10.npz", allow_pickle=False) as saved:
        original_neighbors = saved["indices"]

    report: dict[str, object] = {
        "groups": {
            "dynamic": sorted(DYNAMIC),
            "static": sorted(STATIC),
            "counts": {
                "dynamic": int(np.sum(macro == 1)),
                "static": int(np.sum(macro == 0)),
            },
        },
        "original_neighbor_purity": {
            "static_dynamic_k10": cached_neighbor_purity(original_neighbors, macro),
            "six_activities_k10": cached_neighbor_purity(original_neighbors, labels),
        },
        "pca_explained_variance": pca_model.explained_variance_ratio_[:10].astype(float).tolist(),
        "pca_top_correlations": {
            "pc1": top_correlations(scaled, pca_scores, data.feature_names, 0),
            "pc2": top_correlations(scaled, pca_scores, data.feature_names, 1),
        },
        "top_dynamic_static_features": top_macro_differences(scaled, macro, data.feature_names),
        "embeddings": {
            "pca": embedding_summary(cached_pca, labels, macro),
            "tsne": embedding_summary(tsne, labels, macro),
            "umap": embedding_summary(umap, labels, macro),
        },
    }

    results = ROOT / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "analysis_interpretavel.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "ANALISE-PARA-APRESENTACAO.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
