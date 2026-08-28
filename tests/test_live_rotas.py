"""rotas do relay: laboratorio na mesma origem, artefatos e protecao por token."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import live_server  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    return TestClient(live_server.app)


class TestLaboratorio:
    def test_laboratorio_e_servido_na_mesma_origem(self, cliente):
        resposta = cliente.get("/laboratorio/")
        assert resposta.status_code == 200
        assert "HAR_DADOS" in resposta.text or "har-data.js" in resposta.text

    def test_assets_do_laboratorio_sao_relativos(self, cliente):
        pagina = cliente.get("/laboratorio/").text
        assert './har-data.js' in pagina
        assert './har-live-data.js' in pagina
        assert 'src="/web/' not in pagina

    def test_arquivo_da_vista_har_live_traz_as_tres_tecnicas(self, cliente):
        resposta = cliente.get("/laboratorio/har-live-data.js")
        assert resposta.status_code == 200
        for chave in ("harlive/pca-comum-128", "harlive/tsne-comum-128", "harlive/umap-comum-128"):
            assert chave in resposta.text
        # o t-sne nao pode ser anunciado como transform de dado novo
        assert "INTERPOLAÇÃO" in resposta.text

    def test_nao_serve_caminho_arbitrario(self, cliente):
        for alvo in (
            "/laboratorio/../src/live_server.py",
            "/laboratorio/..%2f..%2fsrc%2flive_server.py",
            "/assets/../../src/live_server.py",
        ):
            resposta = cliente.get(alvo)
            assert resposta.status_code in (403, 404, 400), alvo
            assert "ACCESS_TOKEN" not in resposta.text

    def test_csp_do_laboratorio_nao_vaza_para_a_captura(self, cliente):
        laboratorio = cliente.get("/laboratorio/").headers["content-security-policy"]
        captura = cliente.get("/mobile").headers["content-security-policy"]
        assert "'unsafe-eval'" in laboratorio  # motor de template e ECharts
        assert "'unsafe-eval'" not in captura
        for politica in (laboratorio, captura):
            assert "frame-ancestors 'none'" in politica
            assert "object-src 'none'" in politica
            assert "http://" not in politica and "https://" not in politica


ROTAS_PROTEGIDAS = (
    "/api/har-live/referencia",
    "/api/har-live/metricas",
    "/api/har-live/gravacoes",
)


class TestAutenticacaoDasRotas:
    def test_sem_token_todas_recusam(self, cliente):
        for rota in ROTAS_PROTEGIDAS:
            resposta = cliente.get(rota)
            assert resposta.status_code == 403, rota
            assert "erro" in resposta.json()

    def test_token_errado_recusa(self, cliente):
        for rota in ROTAS_PROTEGIDAS:
            assert cliente.get(f"{rota}?token=nao-e-o-token").status_code == 403, rota

    def test_token_certo_por_query_e_por_cabecalho(self, cliente):
        for rota in ROTAS_PROTEGIDAS:
            por_query = cliente.get(f"{rota}?token={live_server.ACCESS_TOKEN}")
            por_cabecalho = cliente.get(rota, headers={"X-HAR-Token": live_server.ACCESS_TOKEN})
            assert por_query.status_code in (200, 404), rota
            assert por_cabecalho.status_code == por_query.status_code, rota

    def test_recusa_nao_vaza_o_token(self, cliente):
        corpo = cliente.get("/api/har-live/gravacoes").text
        assert live_server.ACCESS_TOKEN not in corpo


class TestArtefatosHarLive:
    def test_referencia_e_metricas_respondem_ou_avisam(self, cliente):
        for rota in ("/api/har-live/referencia", "/api/har-live/metricas"):
            resposta = cliente.get(f"{rota}?token={live_server.ACCESS_TOKEN}")
            assert resposta.status_code in (200, 404)
            if resposta.status_code == 404:
                assert "erro" in resposta.json()

    def test_health_declara_se_o_espaco_existe(self, cliente):
        corpo = cliente.get("/api/health").json()
        assert corpo["ok"] is True
        assert isinstance(corpo["har_live"], bool)

    def test_gravacoes_tem_forma_estavel(self, cliente):
        corpo = cliente.get(
            f"/api/har-live/gravacoes?token={live_server.ACCESS_TOKEN}"
        ).json()
        assert isinstance(corpo["gravacoes"], list)
        for gravacao in corpo["gravacoes"]:
            assert {"atividade", "coordenadas", "situacoes"} <= set(gravacao)


class TestToken:
    def test_websockets_exigem_token(self, cliente):
        for rota in ("/ws/mobile", "/ws/dashboard"):
            with pytest.raises(Exception):
                with cliente.websocket_connect(f"{rota}?session=P31&token=errado"):
                    pass

    def test_token_correto_conecta(self, cliente):
        rota = f"/ws/dashboard?session=P31&token={live_server.ACCESS_TOKEN}"
        with cliente.websocket_connect(rota) as ws:
            assert ws.receive_json()["type"] == "relay-status"


class TestPersistencia:
    def test_gravacoes_sobrevivem_a_reinicio(self, tmp_path, monkeypatch):
        """um reinicio do servidor nao pode apagar o que ja foi gravado."""
        arquivo = tmp_path / "gravacoes-iphone.json"
        monkeypatch.setattr(live_server, "GRAVACOES_ARQUIVO", arquivo)

        primeiro = live_server.SessionHub()
        primeiro._projetadas.append(
            {"atividade": "WALKING", "coordenadas": [[1.0, 2.0]], "situacoes": ["dentro"]}
        )
        primeiro._gravar_no_disco()

        segundo = live_server.SessionHub()
        assert len(segundo.gravacoes_projetadas()) == 1
        assert segundo.gravacoes_projetadas()[0]["atividade"] == "WALKING"

    def test_arquivo_corrompido_nao_derruba_o_servidor(self, tmp_path, monkeypatch):
        arquivo = tmp_path / "gravacoes-iphone.json"
        arquivo.write_text("{isso nao e json", encoding="utf-8")
        monkeypatch.setattr(live_server, "GRAVACOES_ARQUIVO", arquivo)
        assert live_server.SessionHub().gravacoes_projetadas() == []

    def test_arquivo_e_legivel_apenas_pelo_dono(self, tmp_path, monkeypatch):
        """movimento corporal nao pode ficar legivel pra outras contas."""
        import stat

        arquivo = tmp_path / "gravacoes-iphone.json"
        monkeypatch.setattr(live_server, "GRAVACOES_ARQUIVO", arquivo)
        hub = live_server.SessionHub()
        hub._projetadas.append({"atividade": "WALKING", "coordenadas": [[1.0, 2.0]]})
        hub._gravar_no_disco()
        modo = stat.S_IMODE(arquivo.stat().st_mode)
        assert modo == 0o600, oct(modo)

    def test_escrita_e_atomica(self, tmp_path, monkeypatch):
        """uma falha no meio da escrita nao pode deixar o arquivo truncado."""
        arquivo = tmp_path / "gravacoes-iphone.json"
        monkeypatch.setattr(live_server, "GRAVACOES_ARQUIVO", arquivo)
        hub = live_server.SessionHub()
        hub._projetadas.append({"atividade": "WALKING", "coordenadas": [[1.0, 2.0]]})
        hub._gravar_no_disco()
        conteudo_bom = arquivo.read_text(encoding="utf-8")

        def falhar(*_args, **_kwargs):
            raise OSError("disco cheio")

        monkeypatch.setattr(live_server.json, "dump", falhar)
        hub._projetadas.append({"atividade": "SITTING", "coordenadas": [[3.0, 4.0]]})
        hub._gravar_no_disco()

        assert arquivo.read_text(encoding="utf-8") == conteudo_bom
        assert not arquivo.with_suffix(".parcial").exists()
