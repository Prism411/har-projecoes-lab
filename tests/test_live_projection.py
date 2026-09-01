"""Testes do caminho iPhone → espaço compartilhado com o HAR."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from live_features import PASSO_JANELA, TAMANHO_JANELA, TAXA_HZ, extrair  # noqa: E402
from live_projection import (  # noqa: E402
    GRAVIDADE,
    EspacoCompartilhado,
    GravacaoInsuficiente,
    formar_janelas,
    preparar_series,
)


def gravacao_sintetica(
    segundos: float = 8.0,
    hertz: float = 60.0,
    aceleracao_g: tuple[float, float, float] = (0.1, 0.2, 0.3),
    rotacao_deg: tuple[float, float, float] = (10.0, 20.0, 30.0),
    linear: bool = True,
) -> list[dict]:
    """Gravação em unidades de navegador: m/s² e graus por segundo."""
    total = int(segundos * hertz)
    amostras = []
    for indice in range(total):
        instante = 1_000_000.0 + indice * (1000.0 / hertz)
        aceleracao = [valor * GRAVIDADE for valor in aceleracao_g]
        amostras.append(
            {
                "t": instante,
                "interval_ms": 1000.0 / hertz,
                "acceleration": aceleracao if linear else [None, None, None],
                "acceleration_gravity": [aceleracao[0], aceleracao[1], aceleracao[2] + GRAVIDADE],
                "rotation_deg_s": list(rotacao_deg),
                "orientation_deg": [0.0, 0.0, 0.0],
            }
        )
    return amostras


class TestUnidades:
    def test_aceleracao_vira_g(self):
        series, _ = preparar_series(gravacao_sintetica(aceleracao_g=(0.5, -0.25, 1.0)))
        assert series[0].mean() == pytest.approx(0.5, abs=1e-3)
        assert series[1].mean() == pytest.approx(-0.25, abs=1e-3)
        assert series[2].mean() == pytest.approx(1.0, abs=1e-3)

    def test_rotacao_vira_radianos(self):
        series, _ = preparar_series(gravacao_sintetica(rotacao_deg=(180.0, -90.0, 45.0)))
        assert series[3].mean() == pytest.approx(np.pi, abs=1e-3)
        assert series[4].mean() == pytest.approx(-np.pi / 2, abs=1e-3)
        assert series[5].mean() == pytest.approx(np.pi / 4, abs=1e-3)

    def test_ordem_dos_canais_segue_a_uci(self):
        series, _ = preparar_series(
            gravacao_sintetica(aceleracao_g=(1.0, 2.0, 3.0), rotacao_deg=(0.0, 0.0, 0.0))
        )
        assert series.shape[0] == 6
        assert series[0].mean() < series[1].mean() < series[2].mean()

    def test_gravidade_estimada_quando_falta_aceleracao_linear(self):
        series, relatorio = preparar_series(gravacao_sintetica(linear=False))
        assert "gravidade estimada" in relatorio["origem_da_aceleracao"]
        # a parcela constante some junto com a gravidade
        assert abs(series[2].mean()) < 0.2


class TestReamostragem:
    def test_grade_de_50hz(self):
        series, relatorio = preparar_series(gravacao_sintetica(segundos=10.0, hertz=60.0))
        assert relatorio["taxa_observada_hz"] == pytest.approx(60.0, abs=1.0)
        assert series.shape[1] == pytest.approx(10.0 * TAXA_HZ, abs=2)

    def test_taxa_baixa_tambem_chega_a_50hz(self):
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0, hertz=25.0))
        assert series.shape[1] == pytest.approx(10.0 * TAXA_HZ, abs=2)

    def test_amostras_fora_de_ordem_sao_ordenadas(self):
        amostras = gravacao_sintetica(segundos=6.0)
        embaralhadas = [amostras[i] for i in np.random.RandomState(0).permutation(len(amostras))]
        series_ordenada, _ = preparar_series(amostras)
        series_embaralhada, _ = preparar_series(embaralhadas)
        assert np.allclose(series_ordenada, series_embaralhada, atol=1e-6)

    def test_gravacao_curta_e_recusada(self):
        with pytest.raises(GravacaoInsuficiente):
            preparar_series(gravacao_sintetica(segundos=1.0))


class TestJanelas:
    def test_tamanho_e_passo_da_uci(self):
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0))
        janelas = formar_janelas(series)
        assert janelas.shape[1:] == (6, TAMANHO_JANELA)
        esperado = (series.shape[1] - TAMANHO_JANELA) // PASSO_JANELA + 1
        assert len(janelas) == esperado

    def test_sobreposicao_de_metade(self):
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0))
        janelas = formar_janelas(series)
        assert np.allclose(janelas[0][:, PASSO_JANELA:], janelas[1][:, :PASSO_JANELA])

    def test_caracteristicas_tem_dimensao_estavel(self):
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0))
        matriz, nomes = extrair(formar_janelas(series))
        assert matriz.shape[1] == len(nomes)
        assert np.isfinite(matriz).all()


@pytest.fixture(scope="module")
def espaco():
    try:
        return EspacoCompartilhado()
    except FileNotFoundError:
        pytest.skip("modelos ausentes; rode src/build_live_space.py")


@pytest.fixture(scope="module")
def har():
    """O dataset da UCI tem 61 MB e não é versionado: quem clona baixa à parte.

    Sem este aviso, um clone novo mostra dois erros de arquivo ausente como se
    o código estivesse quebrado.
    """
    from build_har_data import load_har

    arquivo = RAIZ.parent / "datasets" / "uci-har-smartphones.zip"
    if not arquivo.exists():
        pytest.skip(f"dataset ausente em {arquivo} — baixe da UCI para rodar estes testes")
    return load_har(arquivo)


class TestProjecao:
    def test_ajuste_nao_muda_com_dado_novo(self, espaco):
        """Os modelos só transformam: projetar duas vezes dá o mesmo ponto."""
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0))
        janelas = formar_janelas(series)
        centro_antes = espaco.umap._raw_data.mean(axis=0).copy()
        primeira = espaco.projetar(janelas).coordenadas
        segunda = espaco.projetar(janelas).coordenadas
        assert np.allclose(primeira, segunda)
        assert np.allclose(centro_antes, espaco.umap._raw_data.mean(axis=0))

    def test_janela_do_har_disfarcada_de_iphone_volta_ao_lugar(self, espaco, har):
        """Ida e volta: um sinal real do HAR, convertido para unidades de
        navegador e reprocessado pelo caminho do iPhone, precisa cair perto de
        onde o próprio HAR o coloca."""
        indice = 100
        janela = har.inertial_signals[indice]
        amostras = [
            {
                "t": 1_000_000.0 + posicao * (1000.0 / TAXA_HZ),
                "interval_ms": 1000.0 / TAXA_HZ,
                "acceleration": [float(janela[eixo, posicao]) * GRAVIDADE for eixo in (0, 1, 2)],
                "acceleration_gravity": [0.0, 0.0, GRAVIDADE],
                "rotation_deg_s": [float(np.rad2deg(janela[3 + eixo, posicao])) for eixo in (0, 1, 2)],
                "orientation_deg": [0.0, 0.0, 0.0],
            }
            for posicao in range(TAMANHO_JANELA)
        ]
        series, _ = preparar_series(amostras)
        assert np.allclose(series, janela, atol=1e-3)

        direto, _ = extrair(janela[None, :, :])
        pela_rota_do_iphone, _ = extrair(formar_janelas(series))
        assert np.allclose(direto, pela_rota_do_iphone, rtol=1e-3, atol=1e-4)

        projecao = espaco.projetar(formar_janelas(series), rotulos_har=list(har.labels))
        assert projecao.situacoes[0] == "dentro"
        atividades = [vizinho["atividade"] for vizinho in projecao.vizinhos[0]]
        assert atividades.count(har.labels[indice]) >= 5

    def test_ruido_puro_cai_fora_da_distribuicao(self, espaco):
        gerador = np.random.RandomState(7)
        janelas = gerador.normal(loc=0.0, scale=8.0, size=(2, 6, TAMANHO_JANELA))
        projecao = espaco.projetar(janelas)
        assert all(situacao == "fora" for situacao in projecao.situacoes)

    def test_diagnostico_traz_percentil_e_vizinhos(self, espaco, har):
        series, _ = preparar_series(gravacao_sintetica(segundos=10.0))
        projecao = espaco.projetar(formar_janelas(series), rotulos_har=list(har.labels))
        assert len(projecao.coordenadas) == len(projecao.situacoes)
        assert all(0.0 <= percentil <= 100.0 for percentil in projecao.percentis_de_distancia)
        assert all(len(grupo) == 10 for grupo in projecao.vizinhos)
