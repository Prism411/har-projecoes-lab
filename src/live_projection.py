"""Leva uma gravação do iPhone para o espaço compartilhado com o HAR.

O caminho é o da especificação: converter unidades, reamostrar para 50 Hz,
formar janelas de 128 com passo 64, extrair as características de
`live_features` e aplicar os modelos ajustados SOMENTE no HAR. Nada é
reajustado com o dado novo.

O resultado traz, além das coordenadas, um diagnóstico de domínio: um iPhone
preso na cintura não é o Samsung Galaxy S II do experimento original, e uma
janela distante deve ser lida como mudança de domínio, não como atividade
errada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np

from live_features import PASSO_JANELA, TAMANHO_JANELA, TAXA_HZ, extrair

GRAVIDADE = 9.80665
RAIZ = Path(__file__).resolve().parents[1]
DIRETORIO_MODELOS = RAIZ / "results" / "live-space"

# Fração de amostras que precisa existir para a janela ser considerada medida,
# e não preenchida por interpolação de lacunas grandes.
COBERTURA_MINIMA = 0.80


class GravacaoInsuficiente(ValueError):
    pass


@dataclass
class Projecao:
    coordenadas: np.ndarray
    coordenadas_pca: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    coordenadas_tsne: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    coordenadas_3d: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    distancias_ao_har: np.ndarray = field(default_factory=lambda: np.empty(0))
    percentis_de_distancia: np.ndarray = field(default_factory=lambda: np.empty(0))
    situacoes: list[str] = field(default_factory=list)
    vizinhos: list[list[dict[str, Any]]] = field(default_factory=list)
    diagnostico: dict[str, Any] = field(default_factory=dict)


def _para_vetor(amostras: Sequence[dict], chave: str) -> np.ndarray:
    return np.array(
        [
            [
                np.nan if valor is None else float(valor)
                for valor in (amostra.get(chave) or [None, None, None])
            ]
            for amostra in amostras
        ],
        dtype=np.float64,
    )


def _remover_gravidade(com_gravidade: np.ndarray, tempos: np.ndarray) -> np.ndarray:
    """Estima a gravidade por média móvel e devolve a parcela corporal.

    Só é usada quando o Safari não entrega aceleração linear nativa. A UCI usa
    um Butterworth de 0,3 Hz; aqui a janela móvel cumpre o mesmo papel de
    separar o componente quase constante.
    """
    duracao = max(tempos[-1] - tempos[0], 1.0) / 1000.0
    if duracao <= 0:
        return com_gravidade
    amostras_por_segundo = len(tempos) / duracao
    largura = max(int(round(amostras_por_segundo * 3.0)), 3)
    nucleo = np.ones(largura) / largura
    gravidade = np.stack(
        [
            np.convolve(np.pad(eixo, (largura // 2, largura // 2), mode="edge"), nucleo, mode="valid")[
                : len(eixo)
            ]
            for eixo in com_gravidade.T
        ],
        axis=1,
    )
    return com_gravidade - gravidade


def preparar_series(amostras: Sequence[dict]) -> tuple[np.ndarray, dict[str, Any]]:
    """Converte as amostras do navegador em seis séries a 50 Hz.

    Devolve (6, n) na ordem body_acc x/y/z em g e body_gyro x/y/z em rad/s,
    junto com um relatório do que foi feito.
    """
    if len(amostras) < TAMANHO_JANELA // 2:
        raise GravacaoInsuficiente(
            f"A gravação tem {len(amostras)} leituras; o mínimo é {TAMANHO_JANELA // 2}."
        )

    tempos = np.array([float(amostra["t"]) for amostra in amostras], dtype=np.float64)
    ordem = np.argsort(tempos)
    tempos = tempos[ordem]
    amostras = [amostras[indice] for indice in ordem]

    linear = _para_vetor(amostras, "acceleration")
    com_gravidade = _para_vetor(amostras, "acceleration_gravity")
    rotacao = _para_vetor(amostras, "rotation_deg_s")

    proporcao_linear = float(np.isfinite(linear).all(axis=1).mean())
    if proporcao_linear >= 0.5:
        aceleracao = linear
        origem = "aceleração linear nativa do Safari"
    elif np.isfinite(com_gravidade).all(axis=1).mean() >= 0.5:
        aceleracao = _remover_gravidade(com_gravidade, tempos)
        origem = "gravidade estimada por média móvel de 3 s"
    else:
        raise GravacaoInsuficiente("A gravação não traz aceleração utilizável.")

    if not np.isfinite(rotacao).all(axis=1).mean() >= 0.5:
        raise GravacaoInsuficiente("A gravação não traz rotação utilizável.")

    # unidades do HAR: aceleração em g, rotação em rad/s
    aceleracao = aceleracao / GRAVIDADE
    rotacao = np.deg2rad(rotacao)

    duracao_s = (tempos[-1] - tempos[0]) / 1000.0
    if duracao_s <= 0:
        raise GravacaoInsuficiente("A gravação não tem duração positiva.")
    taxa_observada = (len(tempos) - 1) / duracao_s

    # grade regular de 50 Hz, como no HAR
    total = int(np.floor(duracao_s * TAXA_HZ)) + 1
    if total < TAMANHO_JANELA:
        raise GravacaoInsuficiente(
            f"A gravação cobre {duracao_s:.1f} s; são necessários "
            f"{TAMANHO_JANELA / TAXA_HZ:.2f} s para uma janela."
        )
    grade = tempos[0] + np.arange(total) * (1000.0 / TAXA_HZ)

    series = []
    for bloco in (aceleracao, rotacao):
        for indice in range(3):
            eixo = bloco[:, indice]
            valido = np.isfinite(eixo)
            if valido.sum() < 2:
                raise GravacaoInsuficiente("Um dos eixos não tem leituras suficientes.")
            series.append(np.interp(grade, tempos[valido], eixo[valido]))

    relatorio = {
        "leituras_recebidas": len(tempos),
        "duracao_s": round(duracao_s, 2),
        "taxa_observada_hz": round(taxa_observada, 1),
        "amostras_reamostradas": total,
        "origem_da_aceleracao": origem,
        "proporcao_linear_nativa": round(proporcao_linear, 3),
    }
    return np.stack(series, axis=0), relatorio


def formar_janelas(series: np.ndarray) -> np.ndarray:
    """Corta (6, n) em (janelas, 6, 128) com passo 64, como a UCI."""
    total = series.shape[1]
    inicios = range(0, total - TAMANHO_JANELA + 1, PASSO_JANELA)
    janelas = [series[:, inicio : inicio + TAMANHO_JANELA] for inicio in inicios]
    if not janelas:
        raise GravacaoInsuficiente("A gravação não cobre uma janela inteira.")
    return np.stack(janelas, axis=0)


class EspacoCompartilhado:
    """Modelos ajustados no HAR, usados apenas para transformar."""

    def __init__(self, diretorio: Path | None = None) -> None:
        diretorio = diretorio or DIRETORIO_MODELOS
        caminho = diretorio / "modelos.joblib"
        if not caminho.exists():
            raise FileNotFoundError(
                f"Modelos ausentes em {caminho}. Rode src/build_live_space.py."
            )
        pacote = joblib.load(caminho)
        self.escalador = pacote["escalador"]
        self.pca = pacote["pca"]
        self.umap = pacote["umap"]
        self.tsne_referencia = pacote.get("tsne_referencia")
        self.umap3d = pacote.get("umap3d")
        self.nomes = pacote["nomes_das_caracteristicas"]
        self._referencia_pca = self.umap._raw_data
        self._limiares: np.ndarray | None = None
        self.aquecer()

    def aquecer(self) -> None:
        """Paga o custo da primeira projeção antes de alguém precisar dela.

        O UMAP compila código na primeira chamada e leva alguns segundos; numa
        aula isso apareceria como o mapa travado logo no primeiro aluno.
        """
        descartavel = np.zeros((1, 6, 128), dtype=np.float64)
        descartavel[:, :, ::2] = 0.01  # sinal mínimo para não ser rejeitado
        try:
            caracteristicas, _ = extrair(descartavel)
            reduzidas = self.pca.transform(self.escalador.transform(caracteristicas))
            self.umap.transform(reduzidas)
            self._distribuicao_de_distancias()
        except Exception:
            pass  # aquecer é otimização; falhar aqui não pode derrubar o servidor

    def _distribuicao_de_distancias(self) -> np.ndarray:
        """Distâncias típicas entre vizinhos dentro do próprio HAR."""
        if self._limiares is None:
            gerador = np.random.RandomState(42)
            indices = gerador.choice(len(self._referencia_pca), 1500, replace=False)
            amostra = self._referencia_pca[indices]
            distancias = []
            for ponto in amostra[:500]:
                separacao = np.linalg.norm(self._referencia_pca - ponto, axis=1)
                separacao.sort()
                distancias.append(separacao[1:11].mean())
            self._limiares = np.array(distancias)
        return self._limiares

    def projetar_ao_vivo(self, janelas: np.ndarray) -> dict[str, list[list[float]]]:
        """Só as coordenadas, para o mapa se mexer durante a gravação.

        Roda em lote de propósito: o custo do UMAP é quase todo fixo, então 30
        janelas de uma vez custam praticamente o mesmo que uma.
        """
        caracteristicas, _ = extrair(janelas)
        reduzidas = self.pca.transform(self.escalador.transform(caracteristicas))
        umap = self.umap.transform(reduzidas)

        tsne = np.empty((len(reduzidas), 2))
        if self.tsne_referencia is not None:
            for posicao, ponto in enumerate(reduzidas):
                separacao = np.linalg.norm(self._referencia_pca - ponto, axis=1)
                proximos = np.argpartition(separacao, 10)[:10]
                pesos = 1.0 / np.maximum(separacao[proximos], 1e-6)
                pesos = pesos / pesos.sum()
                tsne[posicao] = (self.tsne_referencia[proximos] * pesos[:, None]).sum(axis=0)

        arredondar = lambda m: [[round(float(x), 4), round(float(y), 4)] for x, y in m]
        return {
            "pca": arredondar(reduzidas[:, :2]),
            "umap": arredondar(umap),
            "tsne": arredondar(tsne),
        }

    def projetar_em_3d(self, reduzidas: np.ndarray) -> list[list[float]]:
        """Terceira dimensão do espaço comum, para a vista 3D do laboratório."""
        if self.umap3d is None:
            return []
        coordenadas = self.umap3d.transform(reduzidas)
        return [[round(float(v), 4) for v in ponto] for ponto in coordenadas]

    def projetar(self, janelas: np.ndarray, rotulos_har: Sequence[str] | None = None) -> Projecao:
        caracteristicas, _ = extrair(janelas)
        reduzidas = self.pca.transform(self.escalador.transform(caracteristicas))
        coordenadas = self.umap.transform(reduzidas)
        # PCA é linear: as duas primeiras componentes saem do próprio transform.
        coordenadas_pca = reduzidas[:, :2]
        coordenadas_tsne = np.empty((len(reduzidas), 2))

        referencia = self._distribuicao_de_distancias()
        distancias = np.empty(len(reduzidas))
        vizinhos: list[list[dict[str, Any]]] = []
        for posicao, ponto in enumerate(reduzidas):
            separacao = np.linalg.norm(self._referencia_pca - ponto, axis=1)
            proximos = np.argsort(separacao)[:10]
            distancias[posicao] = separacao[proximos].mean()
            # O t-SNE não tem transform(). A posição é uma média dos vizinhos
            # mais próximos, ponderada pelo inverso da distância — interpolação,
            # e não uma projeção nova. O rótulo da vista precisa dizer isso.
            if self.tsne_referencia is not None:
                pesos = 1.0 / np.maximum(separacao[proximos], 1e-6)
                pesos = pesos / pesos.sum()
                coordenadas_tsne[posicao] = (
                    self.tsne_referencia[proximos] * pesos[:, None]
                ).sum(axis=0)
            vizinhos.append(
                [
                    {
                        "indice": int(indice),
                        "distancia": round(float(separacao[indice]), 3),
                        "atividade": (rotulos_har[int(indice)] if rotulos_har is not None else None),
                    }
                    for indice in proximos
                ]
            )

        percentis = np.array(
            [float((referencia < valor).mean() * 100.0) for valor in distancias]
        )
        situacoes = [
            "dentro" if percentil < 95 else ("limítrofe" if percentil < 99.5 else "fora")
            for percentil in percentis
        ]
        return Projecao(
            coordenadas=coordenadas,
            coordenadas_pca=coordenadas_pca,
            coordenadas_tsne=coordenadas_tsne,
            coordenadas_3d=np.array(self.projetar_em_3d(reduzidas) or []),
            distancias_ao_har=distancias,
            percentis_de_distancia=percentis,
            situacoes=situacoes,
            vizinhos=vizinhos,
        )
