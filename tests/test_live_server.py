from __future__ import annotations

import sys
import unittest
from pathlib import Path
from html.parser import HTMLParser
from typing import Any

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_server  # noqa: E402
from live_server import (  # noqa: E402
    ACCESS_TOKEN,
    sanitizar_comando,
    MessageValidationError,
    SessionHub,
    app,
    sanitize_mobile_message,
)


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"] or "")
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"] or "")


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.fechado = False

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.fechado = True


class LiveServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_pages_and_health_are_served(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["service"], "har-live-relay")
        # O título identifica a página, não um número de participante: quem
        # atribui número é o relay, e a aba dizia "Participante 31" para todo
        # mundo — inclusive para quem conduz a aula.
        self.assertIn("<title>Captura de movimento", self.client.get("/mobile").text)
        self.assertIn("<title>Monitor ao vivo", self.client.get("/dashboard").text)
        self.assertIn("<title>Comando da turma", self.client.get("/admin").text)

    def test_security_headers_are_present(self) -> None:
        response = self.client.get("/mobile")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertIn("accelerometer=(self)", response.headers["permissions-policy"])

    def test_local_assets_referenced_by_pages_exist(self) -> None:
        for page_name in ("mobile.html", "dashboard.html"):
            parser = AssetParser()
            parser.feed((ROOT / "live" / page_name).read_text(encoding="utf-8"))
            for asset in parser.assets:
                if not asset.startswith("/assets/"):
                    continue
                target = ROOT / "live" / asset.removeprefix("/assets/")
                self.assertTrue(target.is_file(), f"Asset ausente em {page_name}: {asset}")



class SessionHubTest(unittest.IsolatedAsyncioTestCase):
    async def test_mobile_samples_are_relayed_to_dashboard(self) -> None:
        local_hub = SessionHub()
        dashboard = FakeWebSocket()
        local_hub._dashboards["TESTE"].add(dashboard)  # type: ignore[arg-type]

        await local_hub.relay_from_mobile(
            "TESTE",
            {
                "type": "samples",
                "sequence": 1,
                "sent_at": 1000,
                "samples": [
                    {
                        "t": 980,
                        "acceleration": [0.1, 0.2, 0.3],
                        "rotation_deg_s": [1.0, 2.0, 3.0],
                    }
                ],
            },
            31,
        )

        self.assertEqual(len(dashboard.messages), 1)
        relayed = dashboard.messages[0]
        self.assertEqual(relayed["session"], "TESTE")
        self.assertEqual(relayed["samples"][0]["acceleration"], [0.1, 0.2, 0.3])
        self.assertIn("server_received_at", relayed)


class SinalDeVidaTest(unittest.IsolatedAsyncioTestCase):
    """O "Participante 31 que nunca saía da sala".

    O navegador responde ao ping do WebSocket sozinho, mesmo com a aba
    congelada em segundo plano ou com o túnel segurando a conexão de uma
    página já fechada. Sem um batimento vindo do JavaScript, esse aparelho
    ficava no roster para sempre e a turma via um fantasma na lista.
    """

    async def test_aparelho_calado_sai_da_sala(self) -> None:
        import time as relogio

        local_hub = SessionHub()
        telefone = FakeWebSocket()
        local_hub._mobiles["TESTE"].add(telefone)  # type: ignore[arg-type]
        local_hub._participantes["TESTE"][telefone] = 31  # type: ignore[index]
        local_hub._nomes["TESTE"][31] = "Vitoria"
        local_hub._ultimo_sinal[telefone] = (  # type: ignore[index]
            relogio.monotonic() - live_server.LIMITE_DE_SILENCIO - 1
        )

        expirados = await local_hub.expirar_silenciosos()

        self.assertEqual(expirados, [telefone])
        self.assertTrue(telefone.fechado)

    async def test_quem_deu_sinal_recente_permanece(self) -> None:
        """Um aluno parado esperando a contagem não pode ser expulso."""
        import time as relogio

        local_hub = SessionHub()
        telefone = FakeWebSocket()
        local_hub._mobiles["TESTE"].add(telefone)  # type: ignore[arg-type]
        local_hub._participantes["TESTE"][telefone] = 31  # type: ignore[index]
        local_hub._ultimo_sinal[telefone] = relogio.monotonic()  # type: ignore[index]

        self.assertEqual(await local_hub.expirar_silenciosos(), [])
        self.assertFalse(telefone.fechado)

    async def test_batimento_renova_o_prazo(self) -> None:
        import time as relogio

        local_hub = SessionHub()
        telefone = FakeWebSocket()
        local_hub._ultimo_sinal[telefone] = (  # type: ignore[index]
            relogio.monotonic() - live_server.LIMITE_DE_SILENCIO - 1
        )
        local_hub.anotar_sinal(telefone)  # type: ignore[arg-type]

        self.assertEqual(await local_hub.expirar_silenciosos(), [])

    def test_keepalive_e_vocabulario_valido(self) -> None:
        """Se o relay recusar o batimento, três deles derrubam o aluno."""
        self.assertEqual(
            sanitize_mobile_message({"type": "keepalive"}), {"type": "keepalive"}
        )


class GestaoDaTurmaTest(unittest.IsolatedAsyncioTestCase):
    """Quem conduz a aula precisa arrumar a lista sem apagar tudo de todos."""

    def hub_com_gente(self) -> tuple[SessionHub, FakeWebSocket]:
        local_hub = SessionHub()
        telefone = FakeWebSocket()
        local_hub._mobiles["AULA"].add(telefone)  # type: ignore[arg-type]
        local_hub._participantes["AULA"][telefone] = 31  # type: ignore[index]
        local_hub._nomes["AULA"][31] = "Jder"
        local_hub._projetadas = [
            {"participante": 31, "nome": "Jder", "coordenadas": [[0, 0]]},
            {"participante": 32, "nome": "Ana", "coordenadas": [[1, 1]]},
        ]
        return local_hub, telefone

    async def test_renomear_corrige_tambem_o_que_ja_foi_gravado(self) -> None:
        """Só na sala não bastaria: a gravação guarda o nome de quando foi feita."""
        local_hub, _ = self.hub_com_gente()
        local_hub._gravar_no_disco = lambda: None  # type: ignore[method-assign]

        resultado = await local_hub.gerenciar(
            "AULA", {"acao": "renomear", "participante": 31, "nome": "Jader"}
        )

        self.assertEqual(resultado["gravacoes"], 1)
        self.assertEqual(local_hub._nomes["AULA"][31], "Jader")
        self.assertEqual(local_hub._projetadas[0]["nome"], "Jader")
        self.assertEqual(local_hub._projetadas[1]["nome"], "Ana")  # não encosta em quem não é

    async def test_remover_fecha_o_aparelho_daquela_pessoa(self) -> None:
        local_hub, telefone = self.hub_com_gente()
        outro = FakeWebSocket()
        local_hub._participantes["AULA"][outro] = 32  # type: ignore[index]

        resultado = await local_hub.gerenciar("AULA", {"acao": "remover", "participante": 31})

        self.assertEqual(resultado["aparelhos"], 1)
        self.assertTrue(telefone.fechado)
        self.assertFalse(outro.fechado)

    async def test_esquecer_apaga_so_as_gravacoes_de_um(self) -> None:
        local_hub, _ = self.hub_com_gente()
        local_hub._gravar_no_disco = lambda: None  # type: ignore[method-assign]

        resultado = await local_hub.gerenciar("AULA", {"acao": "esquecer", "participante": 31})

        self.assertEqual(resultado["gravacoes"], 1)
        self.assertEqual([g["participante"] for g in local_hub._projetadas], [32])


class DemonstracaoTest(unittest.TestCase):
    """A rede de segurança da aula: mapa nunca vazio, e nada inventado."""

    def test_demonstrar_nao_exige_participante(self) -> None:
        comando = sanitizar_comando({"acao": "demonstrar", "atividade": "WALKING"})
        self.assertEqual(comando["type"], "gestao")
        self.assertEqual(comando["atividade"], "WALKING")
        self.assertNotIn("participante", comando)

    def test_demonstrar_so_aceita_atividade_do_experimento(self) -> None:
        """Rotular a simulação com uma atividade inventada seria pior que nada."""
        for atividade in ("DANCANDO", "", None, 42):
            with self.assertRaises(MessageValidationError):
                sanitizar_comando({"acao": "demonstrar", "atividade": atividade})

    def test_demonstrar_nao_vira_mensagem_para_os_aparelhos(self) -> None:
        self.assertEqual(
            sanitizar_comando({"acao": "demonstrar", "atividade": "SITTING"})["type"],
            "gestao",
        )


class VocabularioDeGestaoTest(unittest.TestCase):
    def test_acoes_de_gestao_sao_aceitas(self) -> None:
        for acao in ("remover", "esquecer"):
            comando = sanitizar_comando({"acao": acao, "participante": 31})
            self.assertEqual(comando["type"], "gestao")
            self.assertEqual(comando["participante"], 31)

    def test_renomear_passa_pelo_saneamento_de_nome(self) -> None:
        comando = sanitizar_comando(
            {"acao": "renomear", "participante": 31, "nome": "  Jader<script>  "}
        )
        self.assertEqual(comando["nome"], "Jaderscript")

    def test_participante_fora_da_faixa_e_recusado(self) -> None:
        for numero in (0, 30, 1000, "31", None):
            with self.assertRaises(MessageValidationError):
                sanitizar_comando({"acao": "remover", "participante": numero})

    def test_gestao_nao_vira_mensagem_para_os_aparelhos(self) -> None:
        """Um comando de gestão que vazasse para os celulares seria um bug feio."""
        self.assertEqual(sanitizar_comando({"acao": "remover", "participante": 31})["type"], "gestao")
        self.assertEqual(sanitizar_comando({"acao": "parar"})["type"], "comando")


class MessageValidationTest(unittest.TestCase):
    def valid_sample(self) -> dict[str, object]:
        return {
            "t": 1787500000000,
            "interval_ms": 20,
            "acceleration": [0.1, 0.2, 0.3],
            "acceleration_gravity": [0.1, 9.8, 0.3],
            "rotation_deg_s": [1.0, 2.0, 3.0],
            "orientation_deg": [120.0, 3.0, -2.0],
        }

    def test_valid_batch_is_sanitized(self) -> None:
        message = sanitize_mobile_message(
            {
                "type": "samples",
                "sequence": 2,
                "sent_at": 1787500000100,
                "recording": True,
                "activity": "WALKING",
                "samples": [self.valid_sample()],
                "server_received_at": "não pode sobrescrever",
            }
        )
        self.assertEqual(message["sequence"], 2)
        self.assertNotIn("server_received_at", message)

    def test_unknown_type_and_oversized_batch_are_rejected(self) -> None:
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message({"type": "admin"})
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message(
                {
                    "type": "samples",
                    "sequence": 1,
                    "sent_at": 1787500000100,
                    "recording": False,
                    "activity": "WALKING",
                    "samples": [self.valid_sample()] * 26,
                }
            )

    def test_unknown_status_and_summary_reason_are_rejected(self) -> None:
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message({"type": "status", "status": "admin"})
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message(
                {
                    "type": "summary",
                    "reason": "qualquer-coisa",
                    "activity": "WALKING",
                    "sample_count": 1,
                    "duration_ms": 20,
                    "observed_hz": 50,
                    "valid_ratio": 1,
                    "linear_ratio": 1,
                }
            )

    def test_non_finite_values_are_rejected(self) -> None:
        sample = self.valid_sample()
        sample["acceleration"] = [float("nan"), 0.0, 0.0]
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message(
                {
                    "type": "samples",
                    "sequence": 1,
                    "sent_at": 1787500000100,
                    "recording": False,
                    "activity": "WALKING",
                    "samples": [sample],
                }
            )

    def test_boolean_strings_are_rejected(self) -> None:
        with self.assertRaises(MessageValidationError):
            sanitize_mobile_message(
                {
                    "type": "samples",
                    "sequence": 1,
                    "sent_at": 1787500000100,
                    "recording": "false",
                    "activity": "WALKING",
                    "samples": [self.valid_sample()],
                }
            )

    def test_websocket_requires_pairing_token(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as context:
            with TestClient(app).websocket_connect("/ws/mobile?session=TESTE"):
                pass
        self.assertEqual(context.exception.code, 1008)
        self.assertGreaterEqual(len(ACCESS_TOKEN), 12)

    def test_dashboard_socket_is_read_only(self) -> None:
        url = f"/ws/dashboard?session=SOMENTELEITURA&token={ACCESS_TOKEN}"
        with TestClient(app).websocket_connect(url) as websocket:
            self.assertEqual(websocket.receive_json()["type"], "relay-status")
            websocket.send_text("não deveria alterar o relay")
            response = websocket.receive_json()
        self.assertEqual(response["type"], "error")
        self.assertIn("somente leitura", response["message"])

    def test_gravity_acceleration_fallback_is_accepted(self) -> None:
        sample = self.valid_sample()
        sample["acceleration"] = [None, None, None]
        message = sanitize_mobile_message(
            {
                "type": "samples",
                "sequence": 3,
                "sent_at": 1787500000100,
                "recording": True,
                "activity": "WALKING",
                "samples": [sample],
            }
        )
        self.assertEqual(message["samples"][0]["acceleration_gravity"], [0.1, 9.8, 0.3])


if __name__ == "__main__":
    unittest.main()
