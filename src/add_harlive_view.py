"""acrescenta ao laboratorio a vista do espaco compartilhado com o iphone.

nao mexe no `har-data.js` oficial. entra por um arquivo a parte,
`web/har-live-data.js`, que se funde ao `window.HAR_DADOS` antes do app subir:
cada amostra ganha a projecao `harlive/comum-128` e o painel fica do lado de
PCA, t-SNE e UMAP, com os mesmos filtros.

a vista oficial de 561 caracteristicas continua intacta; esta e o espaco de 128
caracteristicas extraidas igual do HAR e do navegador -- unico lugar onde uma
gravacao nova entra de fato por `transform()`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

ESPACO = RAIZ / "results" / "live-space"
DESTINO = RAIZ / "web" / "har-live-data.js"
CHAVES = {
    "pca": "harlive/pca-comum-128",
    "umap": "harlive/umap-comum-128",
    "tsne": "harlive/tsne-comum-128",
}
VIZINHANCAS = (5, 10, 15, 30, 50)


def confiabilidade(altas: np.ndarray, baixas: np.ndarray, k: int) -> tuple[float, float]:
    """trustworthiness e continuity entre o espaco de entrada e a projecao."""
    total = len(altas)
    vizinhos_altas = NearestNeighbors(n_neighbors=k + 1).fit(altas).kneighbors(return_distance=False)[:, 1:]
    vizinhos_baixas = NearestNeighbors(n_neighbors=k + 1).fit(baixas).kneighbors(return_distance=False)[:, 1:]
    ordem_altas = np.argsort(np.argsort(np.linalg.norm(altas[:, None] - altas[None], axis=2), axis=1), axis=1)
    ordem_baixas = np.argsort(np.argsort(np.linalg.norm(baixas[:, None] - baixas[None], axis=2), axis=1), axis=1)

    soma_trust = 0.0
    soma_cont = 0.0
    for indice in range(total):
        intrusos = np.setdiff1d(vizinhos_baixas[indice], vizinhos_altas[indice], assume_unique=False)
        soma_trust += np.sum(ordem_altas[indice, intrusos] - k)
        ausentes = np.setdiff1d(vizinhos_altas[indice], vizinhos_baixas[indice], assume_unique=False)
        soma_cont += np.sum(ordem_baixas[indice, ausentes] - k)
    normalizador = 2.0 / (total * k * (2 * total - 3 * k - 1))
    return 1 - normalizador * soma_trust, 1 - normalizador * soma_cont


def sobreposicao(altas: np.ndarray, baixas: np.ndarray, k: int) -> float:
    va = NearestNeighbors(n_neighbors=k + 1).fit(altas).kneighbors(return_distance=False)[:, 1:]
    vb = NearestNeighbors(n_neighbors=k + 1).fit(baixas).kneighbors(return_distance=False)[:, 1:]
    return float(np.mean([len(set(a) & set(b)) / k for a, b in zip(va, vb)]))


def metricas_de(altas, baixas, rotulos, amostra, parametros, entrada, tempo_ms):
    """mesmas medidas que o laboratorio mostra pras projecoes oficiais."""
    a, b = altas[amostra], baixas[amostra]
    trust, cont, overlap = {}, {}, {}
    for k in VIZINHANCAS:
        valor_trust, valor_cont = confiabilidade(a, b, k)
        trust[str(k)] = float(valor_trust)
        cont[str(k)] = float(valor_cont)
        overlap[str(k)] = sobreposicao(a, b, k)
    triangulo = np.triu_indices(len(amostra), k=1)
    distancias_altas = np.linalg.norm(a[:, None] - a[None], axis=2)[triangulo]
    distancias_baixas = np.linalg.norm(b[:, None] - b[None], axis=2)[triangulo]
    return {
        "tempo_ms": tempo_ms,
        "parametros": dict(parametros, entrada=entrada),
        "trustworthiness": trust,
        "continuity": cont,
        "knn_overlap": overlap,
        "distance_spearman": float(spearmanr(distancias_altas, distancias_baixas).statistic),
        "silhouette_labels_2d": float(silhouette_score(b, rotulos[amostra])),
        "trustworthiness_k10": trust["10"],
        "continuity_k10": cont["10"],
    }


def main() -> int:
    inicio = time.perf_counter()
    referencia = json.loads((ESPACO / "referencia.json").read_text(encoding="utf-8"))
    espaco = json.loads((ESPACO / "metricas.json").read_text(encoding="utf-8"))

    import joblib

    modelos = joblib.load(ESPACO / "modelos.joblib")
    altas = modelos["umap"]._raw_data
    rotulos = np.array(referencia["atividades"])
    amostra = np.random.RandomState(42).choice(len(altas), 2000, replace=False)

    projecoes = {
        "pca": (
            np.array(referencia["coordenadas_pca"], dtype=np.float64),
            {"n_components": 2, "metric": "euclidean", "seed": espaco["semente"]},
            "128D comuns ao HAR e ao navegador, padronizadas · PC1 e PC2",
        ),
        "umap": (
            np.array(referencia["coordenadas"], dtype=np.float64),
            {
                "n_neighbors": espaco["parametros"]["vizinhos_umap"],
                "min_dist": espaco["parametros"]["distancia_minima_umap"],
                "metric": "euclidean",
                "seed": espaco["semente"],
            },
            "128D comuns ao HAR e ao navegador, padronizadas",
        ),
        "tsne": (
            np.array(referencia["coordenadas_tsne"], dtype=np.float64),
            {"perplexity": 30, "init": "pca", "seed": espaco["semente"]},
            "128D comuns · gravação posicionada por INTERPOLAÇÃO entre vizinhos, "
            "não por transform (t-SNE não possui um)",
        ),
    }

    pacote = {"chaves": CHAVES, "coordenadas": {}, "metricas": {}}
    for tecnica, (coordenadas, parametros, entrada) in projecoes.items():
        print(f"medindo {tecnica}…", flush=True)
        medidas = metricas_de(
            altas, coordenadas, rotulos, amostra, parametros, entrada,
            int((time.perf_counter() - inicio) * 1000),
        )
        pacote["coordenadas"][tecnica] = [
            [round(float(x), 4), round(float(y), 4)] for x, y in coordenadas
        ]
        pacote["metricas"][tecnica] = medidas
        print(
            f"  trust k10 {medidas['trustworthiness_k10']:.4f} · "
            f"cont k10 {medidas['continuity_k10']:.4f} · "
            f"silhueta {medidas['silhouette_labels_2d']:.4f}",
            flush=True,
        )

    pacote["resumo"] = {
        "caracteristicas": espaco["caracteristicas"],
        "acuracia_knn10": espaco["acuracia_knn10"],
        "variancia_pca": espaco["variancia_pca"],
    }

    corpo = json.dumps(pacote, ensure_ascii=False, separators=(",", ":"))
    DESTINO.write_text(
        "/* GERADO POR src/add_harlive_view.py. Espaço de características comuns\n"
        "   ao HAR e ao iPhone; some ao har-data.js sem alterá-lo. */\n"
        "(() => {\n"
        f"  const pacote = {corpo};\n"
        "  const dados = window.HAR_DADOS;\n"
        "  if (!dados || !Array.isArray(dados.amostras)) return;\n"
        "  Object.keys(pacote.chaves).forEach(tecnica => {\n"
        "    const chave = pacote.chaves[tecnica];\n"
        "    const pontos = pacote.coordenadas[tecnica];\n"
        "    const total = Math.min(dados.amostras.length, pontos.length);\n"
        "    for (let i = 0; i < total; i += 1) {\n"
        "      dados.amostras[i].projecoes[chave] = pontos[i];\n"
        "    }\n"
        "    dados.metricas[chave] = pacote.metricas[tecnica];\n"
        "  });\n"
        "  dados.har_live = pacote.resumo;\n"
        "  window.HAR_LIVE_CHAVES = pacote.chaves;\n"
        "})();\n",
        encoding="utf-8",
    )
    print(f"\n{DESTINO.name} gerado ({DESTINO.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
