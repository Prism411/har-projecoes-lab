"""Ajusta o espaço de projeção compartilhado entre o HAR e o iPhone.

Diferente do laboratório oficial, que projeta as 561 características prontas da
UCI, aqui o scaler, o PCA e o UMAP são ajustados sobre as características de
`live_features`, extraídas dos sinais inerciais. Só assim uma gravação nova pode
passar por `transform()` e cair no mesmo mapa — sem reajustar nada e sem que os
rótulos participem do ajuste.

Saídas em `results/live-space/`:
  modelos.joblib        scaler, PCA e UMAP ajustados
  referencia.json       coordenadas e rótulos das 10.299 janelas
  metricas.json         separabilidade e metadados de reprodutibilidade
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.model_selection import cross_val_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from umap import UMAP

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_har_data import load_har  # noqa: E402
from live_features import extrair  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO_PADRAO = RAIZ.parent / "datasets" / "uci-har-smartphones.zip"
DESTINO = RAIZ / "results" / "live-space"
SEMENTE = 42
COMPONENTES_PCA = 50
VIZINHOS_UMAP = 30
DISTANCIA_MINIMA_UMAP = 0.10
PERPLEXIDADE_TSNE = 30


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    print("carregando o HAR…", flush=True)
    dados = load_har(ARQUIVO_PADRAO)

    print(f"extraindo características de {len(dados.inertial_signals)} janelas…", flush=True)
    caracteristicas, nomes = extrair(dados.inertial_signals)
    print(f"  matriz {caracteristicas.shape}", flush=True)

    escalador = StandardScaler().fit(caracteristicas)
    padronizadas = escalador.transform(caracteristicas)

    pca = PCA(n_components=COMPONENTES_PCA, random_state=SEMENTE).fit(padronizadas)
    reduzidas = pca.transform(padronizadas)
    variancia = float(pca.explained_variance_ratio_.sum())
    print(f"  PCA{COMPONENTES_PCA} preserva {variancia:.1%} da variância", flush=True)

    print("ajustando o UMAP…", flush=True)
    umap = UMAP(
        n_neighbors=VIZINHOS_UMAP,
        min_dist=DISTANCIA_MINIMA_UMAP,
        n_components=2,
        metric="euclidean",
        init="spectral",
        random_state=SEMENTE,
    ).fit(reduzidas)
    coordenadas = umap.embedding_

    print("ajustando o UMAP 3D…", flush=True)
    # O laboratório tem uma vista tridimensional; sem um 3D no espaço comum, a
    # turma ficaria de fora justamente da vista mais vistosa da apresentação.
    umap3d = UMAP(
        n_neighbors=VIZINHOS_UMAP,
        min_dist=DISTANCIA_MINIMA_UMAP,
        n_components=3,
        metric="euclidean",
        init="spectral",
        random_state=SEMENTE,
    ).fit(reduzidas)
    coordenadas_3d = umap3d.embedding_

    print("ajustando o t-SNE…", flush=True)
    # O t-SNE não possui transform(): estas coordenadas servem de referência, e
    # uma gravação nova só pode ser posicionada por interpolação entre vizinhos.
    tsne = TSNE(
        n_components=2,
        perplexity=PERPLEXIDADE_TSNE,
        init="pca",
        random_state=SEMENTE,
        max_iter=1000,
    ).fit_transform(reduzidas)

    print("ajustando o PCA 2D…", flush=True)
    coordenadas_pca = reduzidas[:, :2]

    print("medindo separabilidade…", flush=True)
    rotulos = np.asarray(dados.labels)
    amostra = np.random.RandomState(SEMENTE).choice(
        len(reduzidas), size=min(3000, len(reduzidas)), replace=False
    )
    silhueta_pca = float(silhouette_score(reduzidas[amostra], rotulos[amostra]))
    silhueta_umap = float(silhouette_score(coordenadas[amostra], rotulos[amostra]))
    acuracia = float(
        cross_val_score(
            KNeighborsClassifier(n_neighbors=10),
            reduzidas[amostra],
            rotulos[amostra],
            cv=5,
        ).mean()
    )
    print(f"  silhueta PCA50 {silhueta_pca:.3f} | UMAP {silhueta_umap:.3f}", flush=True)
    print(f"  kNN 10 vizinhos, 5 dobras: {acuracia:.1%}", flush=True)

    joblib.dump(
        {
            "escalador": escalador,
            "pca": pca,
            "umap": umap,
            "umap3d": umap3d,
            "tsne_referencia": tsne.astype(np.float32),
            "nomes_das_caracteristicas": nomes,
        },
        DESTINO / "modelos.joblib",
        compress=3,
    )

    referencia = {
        "coordenadas": np.round(coordenadas, 4).tolist(),
        "coordenadas_pca": np.round(coordenadas_pca, 4).tolist(),
        "coordenadas_tsne": np.round(tsne, 4).tolist(),
        "coordenadas_3d": np.round(coordenadas_3d, 4).tolist(),
        "atividades": rotulos.tolist(),
        "participantes": dados.subjects.tolist(),
        "conjuntos": dados.splits.tolist(),
    }
    (DESTINO / "referencia.json").write_text(
        json.dumps(referencia, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    metricas = {
        "janelas": int(len(caracteristicas)),
        "caracteristicas": int(caracteristicas.shape[1]),
        "variancia_pca": round(variancia, 4),
        "silhueta_pca50": round(silhueta_pca, 4),
        "silhueta_umap": round(silhueta_umap, 4),
        "acuracia_knn10": round(acuracia, 4),
        "semente": SEMENTE,
        "parametros": {
            "componentes_pca": COMPONENTES_PCA,
            "vizinhos_umap": VIZINHOS_UMAP,
            "distancia_minima_umap": DISTANCIA_MINIMA_UMAP,
        },
        "observacao": (
            "Espaço separado da vista oficial de 561 características. "
            "Rótulos não participam do ajuste; entram apenas nas métricas."
        ),
    }
    (DESTINO / "metricas.json").write_text(
        json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nsalvo em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
