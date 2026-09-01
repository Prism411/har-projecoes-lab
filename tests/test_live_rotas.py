"""Rotas do relay: laboratório na mesma origem, artefatos e proteção por token."""

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
        # o t-SNE não pode ser anunciado como transform de dado novo
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
        """Um reinício do servidor não pode apagar o que já foi gravado."""
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
        """Movimento corporal não pode ficar legível para outras contas."""
        import stat

        arquivo = tmp_path / "gravacoes-iphone.json"
        monkeypatch.setattr(live_server, "GRAVACOES_ARQUIVO", arquivo)
        hub = live_server.SessionHub()
        hub._projetadas.append({"atividade": "WALKING", "coordenadas": [[1.0, 2.0]]})
        hub._gravar_no_disco()
        modo = stat.S_IMODE(arquivo.stat().st_mode)
        assert modo == 0o600, oct(modo)

    def test_escrita_e_atomica(self, tmp_path, monkeypatch):
        """Uma falha no meio da escrita não pode deixar o arquivo truncado."""
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


class TestSalaComVariosParticipantes:
    def test_faixa_reservada_ao_ao_vivo(self):
        """1 a 30 são da UCI: quem grava pelo navegador entra a partir de 31."""
        normalizar = live_server.SessionHub.normalizar_participante
        assert normalizar("48") == 48
        assert normalizar(" 32 ") == 32
        assert normalizar("999") == 999

    def test_numero_fora_da_faixa_ou_invalido_vira_o_primeiro(self):
        normalizar = live_server.SessionHub.normalizar_participante
        for entrada in (None, "", "abc", "0", "30", "1000", "-5", "31.5", "'; DROP TABLE"):
            assert normalizar(entrada) == live_server.PRIMEIRO_PARTICIPANTE, entrada

    @pytest.mark.asyncio
    async def test_gravacoes_simultaneas_nao_se_misturam(self):
        """Numa sala os lotes chegam intercalados; cada um tem seu acumulador."""
        hub = live_server.SessionHub()
        lote = lambda valor: {
            "type": "samples",
            "recording": True,
            "samples": [{"t": float(valor), "acceleration": [valor, 0, 0]}],
        }
        for numero in (32, 34, 48):
            await hub._acompanhar_gravacao(
                "AULA", {"type": "recording", "status": "started"}, numero
            )
        # intercalando de propósito, como acontece de verdade
        for rodada in range(3):
            for numero in (32, 34, 48):
                await hub._acompanhar_gravacao("AULA", lote(numero + rodada), numero)

        for numero in (32, 34, 48):
            acumulado = hub._gravacoes[("AULA", numero)]
            assert len(acumulado) == 3, numero
            valores = [amostra["acceleration"][0] for amostra in acumulado]
            assert valores == [numero, numero + 1, numero + 2], numero

    @pytest.mark.asyncio
    async def test_mesma_pessoa_em_salas_diferentes_nao_colide(self):
        hub = live_server.SessionHub()
        for sala in ("AULA", "OUTRA"):
            await hub._acompanhar_gravacao(
                sala, {"type": "recording", "status": "started"}, 31
            )
        await hub._acompanhar_gravacao(
            "AULA",
            {"type": "samples", "recording": True, "samples": [{"t": 1.0}]},
            31,
        )
        assert len(hub._gravacoes[("AULA", 31)]) == 1
        assert len(hub._gravacoes[("OUTRA", 31)]) == 0


class TestComandoDaTurma:
    def test_admin_tem_token_proprio(self):
        """O token dos alunos circula na sala inteira; ele não pode comandar."""
        assert live_server.ADMIN_TOKEN != live_server.ACCESS_TOKEN

    def test_pagina_de_admin_existe(self, cliente):
        assert cliente.get("/admin").status_code == 200

    def test_token_de_aluno_nao_abre_o_canal_de_comando(self, cliente):
        rota = f"/ws/admin?session=AULA&token={live_server.ACCESS_TOKEN}"
        with pytest.raises(Exception):
            with cliente.websocket_connect(rota):
                pass

    def test_token_de_admin_abre_o_canal(self, cliente):
        rota = f"/ws/admin?session=AULA&token={live_server.ADMIN_TOKEN}"
        with cliente.websocket_connect(rota) as ws:
            assert ws.receive_json()["type"] == "relay-status"

    def test_status_anuncia_quem_conectou_antes_de_gravar(self, cliente):
        """O laboratório monta o filtro "Quem" com esta lista.

        Uma pessoa entra na sala assim que conecta, muito antes de existir
        qualquer janela dela. Se `turma` passar a listar só quem já gravou, o
        filtro volta a mostrar a sala vazia com a turma inteira presente.
        """
        aluno = f"/ws/mobile?session=SALA&token={live_server.ACCESS_TOKEN}&participante=31"
        painel = f"/ws/dashboard?session=SALA&token={live_server.ACCESS_TOKEN}"
        with cliente.websocket_connect(painel) as visor:
            assert visor.receive_json()["type"] == "relay-status"
            with cliente.websocket_connect(aluno) as telefone:
                telefone.send_json(
                    {"type": "hello", "role": "mobile", "secure": True,
                     "user_agent": "iPhone", "nome": "Vitoria"}
                )
                telefone.receive_json()  # participante-atribuido
                encontrou = False
                for _ in range(4):
                    mensagem = visor.receive_json()
                    if mensagem.get("type") != "relay-status":
                        continue
                    if any(p["nome"] == "Vitoria" for p in mensagem["turma"]):
                        encontrou = True
                        break
                assert encontrou, "quem conectou não chegou ao filtro do laboratório"

    def test_apagar_avisa_os_paineis_abertos(self, cliente):
        """Apagar tem que chegar ao laboratório que já está aberto.

        As gravações ficam na memória da página depois de absorvidas. Sem este
        aviso, apagar sumia com o dado no relay e a tela seguia desenhando as
        mesmas pessoas até alguém recarregar — o laboratório deixava de ser
        tempo real e virava um acumulador que nunca esquece.
        """
        painel = f"/ws/dashboard?session=AULA&token={live_server.ACCESS_TOKEN}"
        with cliente.websocket_connect(painel) as visor:
            assert visor.receive_json()["type"] == "relay-status"
            resposta = cliente.delete(
                f"/api/har-live/gravacoes?token={live_server.ADMIN_TOKEN}"
            )
            assert resposta.status_code == 200
            aviso = None
            for _ in range(4):
                mensagem = visor.receive_json()
                if mensagem.get("type") == "gravacoes-apagadas":
                    aviso = mensagem
                    break
            assert aviso is not None, "painel aberto não soube do apagamento"

    def test_apagar_exige_token_de_admin(self, cliente):
        assert cliente.delete("/api/har-live/gravacoes").status_code == 403
        assert cliente.delete(
            f"/api/har-live/gravacoes?token={live_server.ACCESS_TOKEN}"
        ).status_code == 403
        assert cliente.delete(
            f"/api/har-live/gravacoes?token={live_server.ADMIN_TOKEN}"
        ).status_code == 200


class TestVocabularioDeComandos:
    def test_acoes_permitidas(self):
        for acao in ("preparar", "iniciar", "parar", "limpar"):
            comando = live_server.sanitizar_comando(
                {"acao": acao, "atividade": "WALKING", "duracao_ms": 10000}
            )
            assert comando["acao"] == acao

    def test_acao_desconhecida_e_recusada(self):
        for acao in ("desligar", "rm -rf", "", None, 42, "INICIAR"):
            with pytest.raises(live_server.MessageValidationError):
                live_server.sanitizar_comando({"acao": acao})

    def test_atividade_invalida_e_recusada(self):
        with pytest.raises(live_server.MessageValidationError):
            live_server.sanitizar_comando({"acao": "iniciar", "atividade": "CORRER"})

    def test_duracao_fora_da_faixa_e_recusada(self):
        for duracao in (0, 500, 999999):
            with pytest.raises(live_server.MessageValidationError):
                live_server.sanitizar_comando(
                    {"acao": "iniciar", "atividade": "WALKING", "duracao_ms": duracao}
                )

    def test_comando_nao_carrega_campo_estranho(self):
        comando = live_server.sanitizar_comando(
            {"acao": "parar", "executar": "algo perigoso", "extra": 1}
        )
        assert set(comando) == {"type", "acao"}


class TestNomeDoParticipante:
    def test_nome_simples_passa(self):
        assert live_server.nome_de_pessoa("Ana") == "Ana"
        assert live_server.nome_de_pessoa("  Maria Clara  ") == "Maria Clara"

    def test_nome_longo_demais_e_recusado(self):
        """Recusar é melhor que truncar: o campo do celular já limita o tamanho,
        então um nome gigante só chega aqui se alguém contornou a página."""
        with pytest.raises(live_server.MessageValidationError):
            live_server.nome_de_pessoa("A" * 80)

    def test_simbolos_perigosos_saem_do_nome(self):
        limpo = live_server.nome_de_pessoa("Ana <b>x</b>")
        assert "<" not in limpo and ">" not in limpo
        assert limpo.startswith("Ana")
        assert len(limpo) <= live_server.MAX_NOME

    def test_nome_vazio_ou_so_simbolo_e_recusado(self):
        for entrada in ("", "   ", "<<>>", "@@@@"):
            with pytest.raises(live_server.MessageValidationError):
                live_server.nome_de_pessoa(entrada)


class TestControleDeTaxa:
    def test_ritmo_normal_de_captura_passa(self):
        """Um aparelho a 50 Hz manda ~2 mensagens por segundo."""
        taxa = live_server.ControleDeTaxa()
        assert not any(taxa.excedeu() for _ in range(10))

    def test_inundacao_e_barrada(self):
        taxa = live_server.ControleDeTaxa(teto=5, janela=5.0)
        resultados = [taxa.excedeu() for _ in range(40)]
        assert not resultados[0] and any(resultados)
        assert resultados[-1] is True

    def test_janela_desliza(self, monkeypatch):
        relogio = {"t": 1000.0}
        monkeypatch.setattr(live_server.time, "monotonic", lambda: relogio["t"])
        taxa = live_server.ControleDeTaxa(teto=2, janela=1.0)
        for _ in range(3):
            taxa.excedeu()
        assert taxa.excedeu() is True
        relogio["t"] += 2.0          # passou a janela
        assert taxa.excedeu() is False


class TestNumeroSemColisao:
    @pytest.mark.asyncio
    async def test_cada_aparelho_recebe_um_numero_proprio(self):
        """O QR da aula é um só: sem isto, a turma inteira entraria como 31."""
        hub = live_server.SessionHub()
        numeros = [(await hub.reservar_participante("AULA", 31))[0] for _ in range(3)]
        assert numeros == [31, 32, 33]

    @pytest.mark.asyncio
    async def test_numero_de_quem_saiu_nunca_vai_para_outra_pessoa(self):
        """O risco silencioso: duas pessoas sob o mesmo identificador.

        Reciclando, bastava alguém sair para o 31 ir ao próximo da fila — e as
        gravações de duas pessoas diferentes ficavam indistinguíveis, com
        "apagar as gravações do participante 31" pegando as duas.
        """
        hub = live_server.SessionHub()
        primeiro, _ = await hub.reservar_participante("AULA", 31)
        # ninguém está conectado: o número dele está "livre"
        seguinte, _ = await hub.reservar_participante("AULA", 31)
        assert seguinte != primeiro

    @pytest.mark.asyncio
    async def test_quem_recarrega_reave_o_proprio_numero(self):
        hub = live_server.SessionHub()
        numero, chave = await hub.reservar_participante("AULA", 31)
        devolvido, mesma = await hub.reservar_participante("AULA", numero, chave)
        assert (devolvido, mesma) == (numero, chave)

    @pytest.mark.asyncio
    async def test_sem_a_chave_ninguem_assume_numero_alheio(self):
        """A página é pública e o endereço circula: pedir 31 não basta."""
        hub = live_server.SessionHub()
        numero, _ = await hub.reservar_participante("AULA", 31)
        intruso, _ = await hub.reservar_participante("AULA", numero, "chave-errada")
        assert intruso != numero
        sem_chave, _ = await hub.reservar_participante("AULA", numero)
        assert sem_chave != numero

    @pytest.mark.asyncio
    async def test_numero_ocupado_nao_volta_nem_com_a_chave_certa(self):
        """Duas abas do mesmo aparelho não podem virar o mesmo participante."""
        hub = live_server.SessionHub()
        numero, chave = await hub.reservar_participante("AULA", 31)
        hub._participantes["AULA"] = {object(): numero}
        outro, _ = await hub.reservar_participante("AULA", numero, chave)
        assert outro != numero

    @pytest.mark.asyncio
    async def test_salas_diferentes_nao_disputam_numero(self):
        hub = live_server.SessionHub()
        await hub.reservar_participante("AULA", 31)
        numero, _ = await hub.reservar_participante("OUTRA", 31)
        assert numero == live_server.PRIMEIRO_PARTICIPANTE

    @pytest.mark.asyncio
    async def test_sala_lotada_recusa_em_vez_de_repetir_numero(self):
        hub = live_server.SessionHub()
        hub._ultimo_numero["AULA"] = live_server.ULTIMO_PARTICIPANTE
        with pytest.raises(live_server.SalaLotada):
            await hub.reservar_participante("AULA", 31)


class TestNomeNaoFicaFantasma:
    @pytest.mark.asyncio
    async def test_nome_sai_quando_o_aparelho_sai(self):
        """Um nome esquecido volta a assombrar quem herdar o número."""
        hub = live_server.SessionHub()
        aparelho = object()
        hub._participantes["AULA"][aparelho] = 31
        await hub.registrar_nome("AULA", 31, "Ana")
        assert hub.nome_de("AULA", 31) == "Ana"

        await hub.disconnect("mobile", "AULA", aparelho)
        # o próximo a receber o 31 não pode herdar "Ana"
        assert hub.nome_de("AULA", 31) == "Participante 31"

    @pytest.mark.asyncio
    async def test_nome_de_outro_participante_sobrevive(self):
        hub = live_server.SessionHub()
        a, b = object(), object()
        hub._participantes["AULA"][a] = 31
        hub._participantes["AULA"][b] = 32
        await hub.registrar_nome("AULA", 31, "Ana")
        await hub.registrar_nome("AULA", 32, "Bruno")
        await hub.disconnect("mobile", "AULA", a)
        assert hub.nome_de("AULA", 31) == "Participante 31"
        assert hub.nome_de("AULA", 32) == "Bruno"
