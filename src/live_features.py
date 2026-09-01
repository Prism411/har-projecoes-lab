"""Características comuns ao HAR e ao iPhone.

O laboratório oficial usa as 561 características prontas da UCI, que não podem
ser reproduzidas a partir de um sinal novo. Este módulo define um espaço menor e
totalmente reprodutível, extraído com o MESMO código nos dois lados:

- do HAR, sobre as janelas de `Inertial Signals` (body_acc em g, body_gyro em
  rad/s, 128 leituras a 50 Hz);
- do iPhone, sobre janelas construídas com as mesmas unidades e taxa.

A comparabilidade depende de os dois lados passarem por esta função e por mais
nada. Qualquer característica que dependa de detalhes do pré-processamento da
UCI fica de fora de propósito.
"""

from __future__ import annotations

import numpy as np

TAXA_HZ = 50.0
TAMANHO_JANELA = 128
PASSO_JANELA = 64

EIXOS = ("x", "y", "z")
CORPOS = ("acc", "gyro")


def _entropia_espectral(espectro: np.ndarray) -> np.ndarray:
    total = espectro.sum(axis=-1, keepdims=True)
    proporcao = np.divide(
        espectro, total, out=np.zeros_like(espectro), where=total > 0
    )
    seguro = np.where(proporcao > 0, proporcao, 1.0)
    return -(proporcao * np.log(seguro)).sum(axis=-1)


def _momentos(valores: np.ndarray, ordem: int) -> np.ndarray:
    media = valores.mean(axis=-1, keepdims=True)
    desvio = valores.std(axis=-1)
    centrado = valores - media
    numerador = (centrado**ordem).mean(axis=-1)
    denominador = np.where(desvio > 0, desvio**ordem, 1.0)
    return np.where(desvio > 0, numerador / denominador, 0.0)


def _tempo(serie: np.ndarray, sufixo: str) -> tuple[np.ndarray, list[str]]:
    """Dez descritores temporais por série. `serie` tem forma (n, amostras)."""
    ordenada = np.sort(serie, axis=-1)
    quartil1 = np.percentile(serie, 25, axis=-1)
    quartil3 = np.percentile(serie, 75, axis=-1)
    media = serie.mean(axis=-1)
    valores = np.stack(
        [
            media,
            serie.std(axis=-1),
            np.abs(serie - media[:, None]).mean(axis=-1),
            ordenada[:, -1],
            ordenada[:, 0],
            (serie**2).mean(axis=-1),
            quartil3 - quartil1,
            np.sqrt((serie**2).mean(axis=-1)),
            _momentos(serie, 3),
            _momentos(serie, 4),
        ],
        axis=1,
    )
    nomes = [
        f"t_{nome}_{sufixo}"
        for nome in (
            "media", "desvio", "desvio_absoluto", "maximo", "minimo",
            "energia", "amplitude_interquartil", "rms", "assimetria", "curtose",
        )
    ]
    return valores, nomes


def _frequencia(serie: np.ndarray, sufixo: str) -> tuple[np.ndarray, list[str]]:
    """Cinco descritores espectrais por série, via FFT real."""
    janela = np.hanning(serie.shape[-1])
    espectro = np.abs(np.fft.rfft(serie * janela, axis=-1))
    frequencias = np.fft.rfftfreq(serie.shape[-1], d=1.0 / TAXA_HZ)
    total = espectro.sum(axis=-1)
    peso = np.divide(
        espectro, total[:, None], out=np.zeros_like(espectro), where=total[:, None] > 0
    )
    frequencia_media = (peso * frequencias[None, :]).sum(axis=-1)
    indice_dominante = espectro.argmax(axis=-1)
    banda_baixa = espectro[:, frequencias <= 3.0].sum(axis=-1)
    proporcao_baixa = np.divide(
        banda_baixa, total, out=np.zeros_like(total), where=total > 0
    )
    valores = np.stack(
        [
            frequencia_media,
            frequencias[indice_dominante],
            espectro.max(axis=-1),
            _entropia_espectral(espectro),
            proporcao_baixa,
        ],
        axis=1,
    )
    nomes = [
        f"f_{nome}_{sufixo}"
        for nome in (
            "frequencia_media", "frequencia_dominante", "pico",
            "entropia", "proporcao_ate_3hz",
        )
    ]
    return valores, nomes


def nomes_das_caracteristicas() -> list[str]:
    """Nomes na mesma ordem produzida por `extrair`."""
    _, nomes = extrair(np.zeros((1, 6, TAMANHO_JANELA), dtype=np.float64))
    return nomes


def extrair(janelas: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Converte janelas (n, 6, 128) em uma matriz de características.

    A ordem dos seis canais é body_acc x/y/z (g) e body_gyro x/y/z (rad/s),
    idêntica à do `Inertial Signals` da UCI.
    """
    janelas = np.asarray(janelas, dtype=np.float64)
    if janelas.ndim != 3 or janelas.shape[1] != 6:
        raise ValueError(f"Esperado (n, 6, amostras); recebido {janelas.shape}.")

    blocos: list[np.ndarray] = []
    nomes: list[str] = []

    # seis eixos, mais a magnitude de cada corpo: oito séries por janela
    series: list[tuple[np.ndarray, str]] = []
    for indice_corpo, corpo in enumerate(CORPOS):
        base = indice_corpo * 3
        for deslocamento, eixo in enumerate(EIXOS):
            series.append((janelas[:, base + deslocamento, :], f"{corpo}_{eixo}"))
        magnitude = np.sqrt((janelas[:, base : base + 3, :] ** 2).sum(axis=1))
        series.append((magnitude, f"{corpo}_magnitude"))

    for serie, sufixo in series:
        for calcular in (_tempo, _frequencia):
            valores, rotulos = calcular(serie, sufixo)
            blocos.append(valores)
            nomes.extend(rotulos)

    # correlação entre eixos de cada corpo: postura e plano de movimento
    for indice_corpo, corpo in enumerate(CORPOS):
        base = indice_corpo * 3
        for primeiro, segundo in ((0, 1), (0, 2), (1, 2)):
            a = janelas[:, base + primeiro, :]
            b = janelas[:, base + segundo, :]
            centrado_a = a - a.mean(axis=-1, keepdims=True)
            centrado_b = b - b.mean(axis=-1, keepdims=True)
            divisor = np.sqrt((centrado_a**2).sum(axis=-1) * (centrado_b**2).sum(axis=-1))
            correlacao = np.divide(
                (centrado_a * centrado_b).sum(axis=-1),
                divisor,
                out=np.zeros(len(janelas)),
                where=divisor > 0,
            )
            blocos.append(correlacao[:, None])
            nomes.append(f"correlacao_{corpo}_{EIXOS[primeiro]}{EIXOS[segundo]}")

    # área de magnitude do sinal: esforço somado dos três eixos
    for indice_corpo, corpo in enumerate(CORPOS):
        base = indice_corpo * 3
        area = np.abs(janelas[:, base : base + 3, :]).sum(axis=(1, 2)) / janelas.shape[-1]
        blocos.append(area[:, None])
        nomes.append(f"area_magnitude_{corpo}")

    matriz = np.hstack(blocos).astype(np.float32, copy=False)
    if not np.isfinite(matriz).all():
        matriz = np.nan_to_num(matriz, nan=0.0, posinf=0.0, neginf=0.0)
    return matriz, nomes
