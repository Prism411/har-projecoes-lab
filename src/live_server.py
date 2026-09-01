from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import secrets
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "live"
LIVE_SPACE_DIR = ROOT / "results" / "live-space"
GRAVACOES_ARQUIVO = ROOT / "gravacoes-iphone.json"
MAX_RECORDING_SAMPLES = 20000
MAX_GRAVACOES_GUARDADAS = 400
# Os participantes 1 a 30 são do experimento original da UCI. Quem grava pelo
# navegador entra a partir de 31, para nunca se confundir com o dataset.
PRIMEIRO_PARTICIPANTE = 31
ULTIMO_PARTICIPANTE = 999
MAX_EMISSORES_POR_SALA = 60
# Um aparelho capturando a 50 Hz manda ~2 mensagens por segundo. O teto abaixo
# dá folga larga para isso e ainda barra inundação: o serviço é público e o
# token dos alunos circula pela sala inteira.
MAX_MENSAGENS_POR_SEGUNDO = 25
# Um aparelho tem que dar sinal de vida a cada BATIMENTO_MS (no mobile.js).
# Três batimentos perdidos e ele sai da sala: o ping do WebSocket não serve
# para isso porque o navegador responde ping sozinho, mesmo com a aba
# congelada em segundo plano — foi assim que um "Participante 31" ficou na
# lista para sempre depois de ninguém mais estar com a página aberta.
LIMITE_DE_SILENCIO = 45.0
INTERVALO_DA_VARREDURA = 10.0
JANELA_DE_TAXA = 5.0
# O mapa se atualiza em lote: o custo do UMAP é quase todo fixo, então juntar as
# janelas de toda a turma num ciclo sai praticamente pelo preço de uma.
INTERVALO_AO_VIVO = 0.6
MAX_JANELAS_POR_CICLO = 90
ACCESS_TOKEN = os.environ.get("HAR_LIVE_TOKEN") or secrets.token_urlsafe(18)
# Quem comanda a turma precisa de uma credencial própria: o token comum está na
# mão de todos os alunos, e com ele qualquer um dispararia a gravação de todos.
ADMIN_TOKEN = os.environ.get("HAR_ADMIN_TOKEN") or secrets.token_urlsafe(18)
MAX_BATCH_SAMPLES = 25
MAX_WEBSOCKET_BYTES = 256 * 1024
ACTIVITIES = {
    "WALKING",
    "WALKING_UPSTAIRS",
    "WALKING_DOWNSTAIRS",
    "SITTING",
    "STANDING",
    "LAYING",
}
STATUS_VALUES = {"sensors-granted", "calibrating", "calibrated"}
# Duas famílias, de responsabilidades diferentes: uma vira mensagem para os
# aparelhos da turma, a outra age no próprio relay e não chega a celular nenhum.
ACOES_DE_COMANDO = {"preparar", "iniciar", "parar", "limpar"}
ACOES_DE_GESTAO = {"remover", "renomear", "esquecer"}
MAX_NOME = 24
SUMMARY_REASONS = {"completed", "manual", "connection-lost", "page-hidden"}


class SalaLotada(Exception):
    """A sala esgotou os números disponíveis."""


class MessageValidationError(ValueError):
    pass


def finite_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
    allow_none: bool = False,
) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MessageValidationError(f"{name} precisa ser numérico.")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise MessageValidationError(f"{name} está fora do intervalo permitido.")
    return number


def finite_integer(value: object, name: str, *, minimum: int, maximum: int) -> int:
    number = finite_number(value, name, minimum=minimum, maximum=maximum)
    if number is None or not number.is_integer():
        raise MessageValidationError(f"{name} precisa ser inteiro.")
    return int(number)


def short_text(value: object, name: str, *, maximum: int = 120) -> str:
    if not isinstance(value, str):
        raise MessageValidationError(f"{name} precisa ser texto.")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > maximum:
        raise MessageValidationError(f"{name} tem tamanho inválido.")
    return cleaned


def boolean_value(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise MessageValidationError(f"{name} precisa ser booleano.")
    return value


def vector3(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> list[float | None]:
    if not isinstance(value, list) or len(value) != 3:
        raise MessageValidationError(f"{name} precisa ter três eixos.")
    return [
        finite_number(
            item,
            f"{name}[{index}]",
            minimum=minimum,
            maximum=maximum,
            allow_none=True,
        )
        for index, item in enumerate(value)
    ]


def optional_number(
    message: dict[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if key not in message:
        return None
    return finite_number(message[key], key, minimum=minimum, maximum=maximum)


def nome_de_pessoa(value: object) -> str:
    """Apelido curto exibido no painel da turma.

    Fica de propósito limitado a um primeiro nome: a página é pública e o que
    trafega junto é movimento do corpo de quem grava.
    """
    texto = short_text(value, "nome", maximum=MAX_NOME)
    limpo = "".join(
        caractere
        for caractere in texto
        if caractere.isalnum() or caractere in " -_'"
    ).strip()
    if not limpo:
        raise MessageValidationError("Nome inválido.")
    return limpo[:MAX_NOME]


def activity_name(value: object) -> str:
    if value not in ACTIVITIES:
        raise MessageValidationError("Atividade inválida.")
    return str(value)


def sanitize_sample(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MessageValidationError("Amostra inválida.")
    sample = {
        "t": finite_number(value.get("t"), "t", minimum=0, maximum=4e15),
        "interval_ms": finite_number(
            value.get("interval_ms"),
            "interval_ms",
            minimum=0,
            maximum=1000,
            allow_none=True,
        ),
        "acceleration": vector3(
            value.get("acceleration"),
            "acceleration",
            minimum=-1000,
            maximum=1000,
        ),
        "acceleration_gravity": vector3(
            value.get("acceleration_gravity"),
            "acceleration_gravity",
            minimum=-1000,
            maximum=1000,
        ),
        "rotation_deg_s": vector3(
            value.get("rotation_deg_s"),
            "rotation_deg_s",
            minimum=-10000,
            maximum=10000,
        ),
        "orientation_deg": vector3(
            value.get("orientation_deg"),
            "orientation_deg",
            minimum=-720,
            maximum=720,
        ),
    }
    measured_values = (
        sample["acceleration"]
        + sample["acceleration_gravity"]
        + sample["rotation_deg_s"]
    )
    if not any(item is not None for item in measured_values):
        raise MessageValidationError("Amostra sem leitura de movimento.")
    return sample


def sanitize_mobile_message(message: object) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise MessageValidationError("Mensagem precisa ser um objeto.")
    message_type = message.get("type")
    if message_type == "keepalive":
        # Sinal de vida do aparelho. Não carrega dado nenhum de propósito: só
        # existe para provar que a página ainda está rodando.
        return {"type": "keepalive"}
    if message_type == "hello":
        saudacao = {
            "type": "hello",
            "role": "mobile",
            "secure": boolean_value(message.get("secure"), "secure"),
            "user_agent": short_text(
                message.get("user_agent", "desconhecido"),
                "user_agent",
                maximum=180,
            ),
        }
        if message.get("nome") is not None:
            saudacao["nome"] = nome_de_pessoa(message.get("nome"))
        return saudacao
    if message_type == "status":
        status = short_text(message.get("status"), "status", maximum=40)
        if status not in STATUS_VALUES:
            raise MessageValidationError("Estado de captura inválido.")
        sanitized: dict[str, Any] = {
            "type": "status",
            "status": status,
        }
        for key, minimum, maximum in (
            ("duration_ms", 0, 300000),
            ("sample_count", 0, 100000),
            ("observed_hz", 0, 1000),
            ("valid_ratio", 0, 1),
            ("linear_ratio", 0, 1),
        ):
            number = optional_number(message, key, minimum=minimum, maximum=maximum)
            if number is not None:
                sanitized[key] = number
        if "still" in message:
            sanitized["still"] = boolean_value(message["still"], "still")
        return sanitized
    if message_type == "recording":
        status = short_text(message.get("status"), "status", maximum=20)
        if status not in {"started", "stopped"}:
            raise MessageValidationError("Estado de gravação inválido.")
        return {
            "type": "recording",
            "status": status,
            "activity": activity_name(message.get("activity")),
            "duration_ms": finite_number(
                message.get("duration_ms"),
                "duration_ms",
                minimum=1000,
                maximum=300000,
            ),
        }
    if message_type == "summary":
        reason = short_text(message.get("reason"), "reason", maximum=40)
        if reason not in SUMMARY_REASONS:
            raise MessageValidationError("Motivo de encerramento inválido.")
        return {
            "type": "summary",
            "reason": reason,
            "activity": activity_name(message.get("activity")),
            "sample_count": finite_integer(
                message.get("sample_count"),
                "sample_count",
                minimum=0,
                maximum=100000,
            ),
            "duration_ms": finite_number(
                message.get("duration_ms"),
                "duration_ms",
                minimum=0,
                maximum=300000,
            ),
            "observed_hz": finite_number(
                message.get("observed_hz"),
                "observed_hz",
                minimum=0,
                maximum=1000,
            ),
            "valid_ratio": finite_number(
                message.get("valid_ratio", 0),
                "valid_ratio",
                minimum=0,
                maximum=1,
            ),
            "linear_ratio": finite_number(
                message.get("linear_ratio", 0),
                "linear_ratio",
                minimum=0,
                maximum=1,
            ),
        }
    if message_type == "samples":
        samples = message.get("samples")
        if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_BATCH_SAMPLES:
            raise MessageValidationError(
                f"Lote precisa ter entre 1 e {MAX_BATCH_SAMPLES} amostras."
            )
        return {
            "type": "samples",
            "sequence": finite_integer(
                message.get("sequence"),
                "sequence",
                minimum=0,
                maximum=2**31 - 1,
            ),
            "sent_at": finite_number(
                message.get("sent_at"),
                "sent_at",
                minimum=0,
                maximum=4e15,
            ),
            "recording": boolean_value(message.get("recording"), "recording"),
            "activity": activity_name(message.get("activity")),
            "samples": [sanitize_sample(sample) for sample in samples],
        }
    if message_type == "error":
        return {
            "type": "error",
            "message": short_text(message.get("message"), "message", maximum=240),
        }
    raise MessageValidationError("Tipo de mensagem não permitido.")


class EspacoIndisponivel(RuntimeError):
    pass


class ProjetorHarLive:
    """Guarda os modelos do espaço compartilhado e projeta gravações.

    O carregamento é preguiçoso: o relay continua funcionando mesmo sem os
    modelos, e a projeção só é oferecida quando `src/build_live_space.py`
    já rodou. O `transform()` é pesado, então roda fora do laço de eventos.
    """

    def __init__(self) -> None:
        self._espaco: Any = None
        self._rotulos: list[str] | None = None
        self._erro: str | None = None
        self._lock = asyncio.Lock()

    @property
    def disponivel(self) -> bool:
        return (LIVE_SPACE_DIR / "modelos.joblib").exists()

    def _carregar(self) -> Any:
        if self._espaco is None:
            from live_projection import EspacoCompartilhado

            self._espaco = EspacoCompartilhado(LIVE_SPACE_DIR)
            referencia = json.loads(
                (LIVE_SPACE_DIR / "referencia.json").read_text(encoding="utf-8")
            )
            self._rotulos = referencia["atividades"]
        return self._espaco

    def _projetar_sincrono(self, amostras: list[dict[str, Any]]) -> dict[str, Any]:
        from live_projection import formar_janelas, preparar_series

        espaco = self._carregar()
        series, relatorio = preparar_series(amostras)
        janelas = formar_janelas(series)
        projecao = espaco.projetar(janelas, rotulos_har=self._rotulos)

        composicao: dict[str, int] = {}
        for grupo in projecao.vizinhos:
            for vizinho in grupo:
                atividade = vizinho["atividade"]
                if atividade:
                    composicao[atividade] = composicao.get(atividade, 0) + 1
        ordenadas = sorted(composicao.items(), key=lambda par: par[1], reverse=True)
        total_vizinhos = sum(composicao.values()) or 1

        def arredondar(matriz: Any) -> list[list[float]]:
            return [[round(float(x), 4), round(float(y), 4)] for x, y in matriz]

        return {
            "coordenadas": arredondar(projecao.coordenadas),
            "coordenadas_pca": arredondar(projecao.coordenadas_pca),
            "coordenadas_tsne": arredondar(projecao.coordenadas_tsne),
            "coordenadas_3d": [
                [round(float(v), 4) for v in ponto] for ponto in projecao.coordenadas_3d
            ],
            "situacoes": projecao.situacoes,
            "percentis": [round(float(valor), 1) for valor in projecao.percentis_de_distancia],
            "vizinhanca": [
                {"atividade": nome, "proporcao": round(quantidade / total_vizinhos, 3)}
                for nome, quantidade in ordenadas[:4]
            ],
            "captura": relatorio,
            "janelas": len(projecao.coordenadas),
        }

    async def projetar(self, amostras: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.disponivel:
            raise EspacoIndisponivel(
                "O espaço HAR live ainda não foi construído neste computador."
            )
        async with self._lock:
            return await asyncio.to_thread(self._projetar_sincrono, amostras)

    def _ao_vivo_sincrono(self, janelas: Any) -> dict[str, list[list[float]]]:
        return self._carregar().projetar_ao_vivo(janelas)

    async def projetar_ao_vivo(self, janelas: Any) -> dict[str, list[list[float]]]:
        if not self.disponivel:
            raise EspacoIndisponivel("Espaço HAR live indisponível.")
        async with self._lock:
            return await asyncio.to_thread(self._ao_vivo_sincrono, janelas)

    async def aquecer(self) -> None:
        """Carrega e compila fora do caminho da aula."""
        if not self.disponivel:
            return
        async with self._lock:
            await asyncio.to_thread(self._carregar)


def sanitizar_comando(message: object) -> dict[str, Any]:
    """Comando do admin para os aparelhos da turma.

    Só o papel admin envia isto, e o vocabulário é fechado: nada que o
    professor mande chega aos celulares sem passar por aqui.
    """
    if not isinstance(message, dict):
        raise MessageValidationError("Comando precisa ser um objeto.")
    acao = short_text(message.get("acao"), "acao", maximum=20)
    if acao not in ACOES_DE_COMANDO and acao not in ACOES_DE_GESTAO:
        raise MessageValidationError("Ação de comando não permitida.")

    if acao in ACOES_DE_GESTAO:
        # Gestão da turma: age no relay, não vira mensagem para os aparelhos.
        gestao: dict[str, Any] = {
            "type": "gestao",
            "acao": acao,
            "participante": int(
                finite_number(
                    message.get("participante"),
                    "participante",
                    minimum=PRIMEIRO_PARTICIPANTE,
                    maximum=ULTIMO_PARTICIPANTE,
                )
            ),
        }
        if acao == "renomear":
            gestao["nome"] = nome_de_pessoa(message.get("nome"))
        return gestao

    comando: dict[str, Any] = {"type": "comando", "acao": acao}
    if acao in {"preparar", "iniciar"}:
        comando["atividade"] = activity_name(message.get("atividade"))
        comando["duracao_ms"] = finite_number(
            message.get("duracao_ms", 10000),
            "duracao_ms",
            minimum=3000,
            maximum=120000,
        )
    if acao == "iniciar":
        # Instante combinado para todos começarem juntos, em relógio do servidor.
        comando["contagem_ms"] = finite_number(
            message.get("contagem_ms", 5000),
            "contagem_ms",
            minimum=0,
            maximum=30000,
        )
    return comando


class SessionHub:
    def __init__(self) -> None:
        self._dashboards: dict[str, set[WebSocket]] = defaultdict(set)
        self._mobiles: dict[str, set[WebSocket]] = defaultdict(set)
        self._last_message: dict[str, dict[str, Any]] = {}
        self._gravacoes: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        self._participantes: dict[str, dict[WebSocket, int]] = defaultdict(dict)
        self._nomes: dict[str, dict[int, str]] = defaultdict(dict)
        self._ultimo_sinal: dict[WebSocket, float] = {}
        # O número é um id que só sobe: reciclar juntava pessoas diferentes sob
        # o mesmo identificador. A chave é o que prova que o número é seu
        # quando a página recarrega.
        self._ultimo_numero: dict[str, int] = {}
        self._chaves: dict[str, dict[int, str]] = defaultdict(dict)
        self._janelas_emitidas: dict[tuple[str, int], int] = defaultdict(int)
        self._admins: dict[str, set[WebSocket]] = defaultdict(set)
        self._projetadas: list[dict[str, Any]] = self._ler_do_disco()
        self._lock = asyncio.Lock()

    @staticmethod
    def normalizar_participante(value: str | None) -> int:
        """Número do participante, validado na faixa reservada ao ao vivo.

        Uma sala tem vários aparelhos ao mesmo tempo: o número é o que separa
        um aluno do outro dentro da mesma sessão, e o que o laboratório usa
        para filtrar e colorir.
        """
        try:
            numero = int(str(value).strip())
        except (TypeError, ValueError):
            return PRIMEIRO_PARTICIPANTE
        if not PRIMEIRO_PARTICIPANTE <= numero <= ULTIMO_PARTICIPANTE:
            return PRIMEIRO_PARTICIPANTE
        return numero

    @staticmethod
    def normalize_session(value: str | None) -> str:
        cleaned = "".join(character for character in (value or "P31").upper() if character.isalnum() or character in "-_")
        return cleaned[:24] or "P31"

    async def connect(
        self,
        role: str,
        session: str,
        websocket: WebSocket,
        participante: int | None = None,
    ) -> bool:
        async with self._lock:
            if role == "mobile" and len(self._mobiles.get(session, set())) >= MAX_EMISSORES_POR_SALA:
                lotada = True
            else:
                lotada = False
        if lotada:
            await websocket.close(code=1013, reason="Sala cheia.")
            return False

        await websocket.accept()
        async with self._lock:
            target = self._mobiles if role == "mobile" else self._dashboards
            target[session].add(websocket)
            if role == "admin":
                self._admins[session].add(websocket)
            if role == "mobile" and participante is not None:
                self._participantes[session][websocket] = participante
                self._ultimo_sinal[websocket] = time.monotonic()
            last_message = self._last_message.get(session)
        await self.broadcast_status(session)
        if role == "dashboard" and last_message is not None:
            await websocket.send_json(last_message)
        return True

    async def disconnect(self, role: str, session: str, websocket: WebSocket) -> None:
        async with self._lock:
            target = self._mobiles if role == "mobile" else self._dashboards
            target[session].discard(websocket)
            if not target[session]:
                target.pop(session, None)
            numero = self._participantes.get(session, {}).pop(websocket, None)
            if not self._participantes.get(session):
                self._participantes.pop(session, None)
            # O nome tem que sair junto com o aparelho. Guardado, ele seria
            # devolvido ao próximo que recebesse o mesmo número — foi o que fez
            # um "Participante 31" antigo reaparecer depois de corrigido.
            if numero is not None:
                self._nomes.get(session, {}).pop(numero, None)
                if not self._nomes.get(session):
                    self._nomes.pop(session, None)
            self._admins.get(session, set()).discard(websocket)
            self._ultimo_sinal.pop(websocket, None)
            # Sala vazia: nada dela precisa continuar na memória. Sem isto,
            # `_last_message`, `_janelas_emitidas` e buffers de gravações
            # interrompidas ficavam para sempre, crescendo a cada sessão que o
            # relay atende ao longo do dia.
            vazia = not self._mobiles.get(session) and not self._dashboards.get(session)
            if vazia:
                self._last_message.pop(session, None)
                self._admins.pop(session, None)
                for chave in [c for c in self._gravacoes if c[0] == session]:
                    self._gravacoes.pop(chave, None)
                for chave in [c for c in self._janelas_emitidas if c[0] == session]:
                    self._janelas_emitidas.pop(chave, None)
        await self.broadcast_status(session)

    def anotar_sinal(self, websocket: WebSocket) -> None:
        """Qualquer mensagem válida prova que a página está viva."""
        self._ultimo_sinal[websocket] = time.monotonic()

    async def varrer_silenciosos(self) -> None:
        """Tira da sala quem parou de dar sinal de vida.

        O ping do protocolo não resolve: o navegador responde pong sozinho,
        então uma aba congelada ou fechada atrás do túnel continuaria no
        roster para sempre. Aqui quem manda é o batimento da própria página.
        """
        while True:
            await asyncio.sleep(INTERVALO_DA_VARREDURA)
            try:
                await self.expirar_silenciosos()
            except Exception:
                continue  # uma varredura ruim não pode parar a aula

    async def expirar_silenciosos(self) -> list[WebSocket]:
        """Uma passada: fecha quem passou do limite e devolve quem saiu."""
        agora = time.monotonic()
        async with self._lock:
            vencidos = [
                websocket
                for websocket, visto in self._ultimo_sinal.items()
                if agora - visto > LIMITE_DE_SILENCIO
            ]
        for websocket in vencidos:
            # fechar dispara o disconnect() do laço, que limpa nome e número
            try:
                await websocket.close(code=1001, reason="Sem sinal de vida.")
            except Exception:
                pass
            async with self._lock:
                self._ultimo_sinal.pop(websocket, None)
        return vencidos

    async def relay_from_mobile(
        self, session: str, message: dict[str, Any], participante: int
    ) -> None:
        forwarded = dict(message)
        forwarded["session"] = session
        forwarded["participante"] = participante
        forwarded["server_received_at"] = int(time.time() * 1000)
        async with self._lock:
            self._last_message[session] = forwarded
            dashboards = set(self._dashboards.get(session, set()))
        await self._send_many(dashboards, forwarded)
        await self._acompanhar_gravacao(session, message, participante)

    async def reservar_participante(
        self, session: str, pedido: int, chave: str | None = None
    ) -> tuple[int, str]:
        """Um número por pessoa — e nunca o mesmo número para duas pessoas.

        Numa aula o QR é o mesmo para todos: sem reserva, a turma inteira
        entraria como 31 e as amostras de pessoas diferentes cairiam no mesmo
        acumulador, sem erro nenhum.

        O número também NÃO é reciclado. Antes bastava alguém sair para o
        número voltar à fila e ir para outra pessoa — e aí duas pessoas
        diferentes dividiam o mesmo identificador. As gravações das duas
        ficavam indistinguíveis, e apagar ou renomear "o participante 31"
        pegava as duas. Aqui o número é um id: sobe e não volta.

        Quem recarrega a página não pode perder o seu, então o aparelho guarda
        uma chave e a apresenta na volta. Sem a chave certa ninguém assume
        número alheio — a página é pública e o endereço é compartilhado.
        """
        async with self._lock:
            usados = set(self._participantes.get(session, {}).values())
            chaves = self._chaves[session]
            if (
                pedido not in usados
                and chave
                and secrets.compare_digest(chaves.get(pedido, ""), chave)
            ):
                return pedido, chave

            anterior = self._ultimo_numero.get(session, PRIMEIRO_PARTICIPANTE - 1)
            numero = max(anterior + 1, PRIMEIRO_PARTICIPANTE)
            if numero > ULTIMO_PARTICIPANTE:
                raise SalaLotada("Esta sala esgotou os números disponíveis.")
            self._ultimo_numero[session] = numero
            nova_chave = secrets.token_urlsafe(9)
            chaves[numero] = nova_chave
            return numero, nova_chave

    async def registrar_nome(self, session: str, participante: int, nome: str) -> None:
        async with self._lock:
            self._nomes[session][participante] = nome
        await self.broadcast_status(session)

    def nome_de(self, session: str, participante: int) -> str:
        return self._nomes.get(session, {}).get(participante, f"Participante {participante}")

    async def enviar_comando(self, session: str, comando: dict[str, Any]) -> int:
        """Leva o comando do admin a todos os aparelhos da sala."""
        async with self._lock:
            aparelhos = set(self._mobiles.get(session, set()))
            paineis = set(self._dashboards.get(session, set()))
        await self._send_many(aparelhos, comando)
        await self._send_many(paineis, dict(comando, eco=True))
        return len(aparelhos)

    async def _acompanhar_gravacao(
        self, session: str, message: dict[str, Any], participante: int
    ) -> None:
        """Junta as amostras da gravação e projeta quando ela termina.

        Numa sala há vários aparelhos gravando ao mesmo tempo, e os lotes
        chegam intercalados: o acumulador é por (sessão, participante), nunca
        só por sessão.
        """
        chave = (session, participante)
        tipo = message.get("type")
        if tipo == "recording" and message.get("status") == "started":
            async with self._lock:
                self._gravacoes[chave] = []
                self._janelas_emitidas[chave] = 0
            return
        if tipo == "samples" and message.get("recording"):
            async with self._lock:
                acumulado = self._gravacoes[chave]
                if len(acumulado) < MAX_RECORDING_SAMPLES:
                    acumulado.extend(message.get("samples", []))
            return
        if tipo == "summary":
            async with self._lock:
                amostras = self._gravacoes.pop(chave, [])
            if amostras:
                asyncio.create_task(
                    self._projetar_gravacao(session, amostras, message, participante)
                )

    async def _projetar_gravacao(
        self,
        session: str,
        amostras: list[dict[str, Any]],
        resumo: dict[str, Any],
        participante: int,
    ) -> None:
        await self._avisar_dashboards(
            session,
            {
                "type": "projection-status",
                "status": "calculando",
                "participante": participante,
            },
        )
        try:
            resultado = await projetor.projetar(amostras)
        except EspacoIndisponivel as erro:
            await self._avisar_dashboards(
                session,
                {
                    "type": "projection-status",
                    "status": "indisponivel",
                    "participante": participante,
                    "message": str(erro),
                },
            )
            return
        except Exception as erro:  # gravação curta ou sinal inutilizável
            await self._avisar_dashboards(
                session,
                {
                    "type": "projection-status",
                    "status": "falhou",
                    "participante": participante,
                    "message": str(erro)[:240],
                },
            )
            return
        resultado.update(
            {
                "type": "projection",
                "session": session,
                "participante": participante,
                "nome": self.nome_de(session, participante),
                "atividade": resumo.get("activity"),
                "server_received_at": int(time.time() * 1000),
            }
        )
        async with self._lock:
            self._last_message[session] = resultado
            self._projetadas.append(
                {
                    "participante": participante,
                    "nome": resultado.get("nome"),
                    "atividade": resultado.get("atividade"),
                    "coordenadas": resultado.get("coordenadas", []),
                    "coordenadas_pca": resultado.get("coordenadas_pca", []),
                    "coordenadas_tsne": resultado.get("coordenadas_tsne", []),
                    "coordenadas_3d": resultado.get("coordenadas_3d", []),
                    "situacoes": resultado.get("situacoes", []),
                    "quando": resultado.get("server_received_at"),
                }
            )
            del self._projetadas[:-MAX_GRAVACOES_GUARDADAS]
            self._gravar_no_disco()
        await self._avisar_dashboards(session, resultado)

    def gravacoes_projetadas(self) -> list[dict[str, Any]]:
        return list(self._projetadas)

    def apagar_gravacoes(self) -> int:
        """Fim de aula: nada de movimento corporal fica guardado."""
        quantas = len(self._projetadas)
        self._projetadas.clear()
        self._gravar_no_disco()
        GRAVACOES_ARQUIVO.unlink(missing_ok=True)
        return quantas

    @staticmethod
    def _ler_do_disco() -> list[dict[str, Any]]:
        """As gravações precisam sobreviver a um reinício do servidor."""
        if not GRAVACOES_ARQUIVO.exists():
            return []
        try:
            conteudo = json.loads(GRAVACOES_ARQUIVO.read_text(encoding="utf-8"))
            gravacoes = conteudo.get("gravacoes", [])
            return gravacoes if isinstance(gravacoes, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _gravar_no_disco(self) -> None:
        """Escrita atômica e legível apenas pelo dono.

        O arquivo guarda movimento corporal de quem gravou. Um write direto
        deixaria o arquivo truncado se o servidor caísse no meio; o temporário
        seguido de replace garante que ou está inteiro, ou está intacto.
        """
        temporario = GRAVACOES_ARQUIVO.with_suffix(".parcial")
        try:
            descritor = os.open(
                temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
                json.dump({"gravacoes": self._projetadas}, arquivo, ensure_ascii=False)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, GRAVACOES_ARQUIVO)
            os.chmod(GRAVACOES_ARQUIVO, 0o600)
        except OSError:
            temporario.unlink(missing_ok=True)  # a sessão atual continua servindo

    async def ciclo_ao_vivo(self) -> None:
        """Move o mapa enquanto a turma grava.

        Junta as janelas fechadas por todos os participantes desde o último
        ciclo e projeta tudo de uma vez nos três espaços.
        """
        while True:
            await asyncio.sleep(INTERVALO_AO_VIVO)
            try:
                await self._projetar_pendentes()
            except Exception:
                continue  # um ciclo ruim não pode parar a aula

    @staticmethod
    def _recortar_janelas(
        instantaneo: dict[tuple[str, int], list[dict[str, Any]]],
        emitidas: dict[tuple[str, int], int],
    ) -> list[tuple[str, int, Any]]:
        """Trabalho pesado de sinal — roda FORA do laço de eventos.

        Reamostrar e janelar trinta buffers custa dezenas de milissegundos por
        ciclo. Feito no laço, o servidor deixa de responder aos pings e o
        WebSocket de toda a turma cai no meio da aula.
        """
        from live_projection import GravacaoInsuficiente, formar_janelas, preparar_series

        pendentes: list[tuple[str, int, Any]] = []
        for (session, participante), amostras in instantaneo.items():
            try:
                series, _ = preparar_series(amostras)
                janelas = formar_janelas(series)
            except (GravacaoInsuficiente, ValueError):
                continue  # ainda não fechou 2,56 s
            ja_vistas = emitidas.get((session, participante), 0)
            for indice in range(ja_vistas, len(janelas)):
                pendentes.append((session, participante, janelas[indice]))
        return pendentes

    async def _janelas_pendentes(self) -> list[tuple[str, int, Any]]:
        async with self._lock:
            instantaneo = {
                chave: list(amostras)
                for chave, amostras in self._gravacoes.items()
                if amostras
            }
            emitidas = dict(self._janelas_emitidas)
        if not instantaneo:
            return []
        return await asyncio.to_thread(self._recortar_janelas, instantaneo, emitidas)

    async def _projetar_pendentes(self) -> None:
        import numpy as np

        pendentes = await self._janelas_pendentes()
        if not pendentes:
            return
        pendentes = pendentes[:MAX_JANELAS_POR_CICLO]

        lote = await asyncio.to_thread(
            np.stack, [janela for _, _, janela in pendentes], 0
        )
        try:
            coordenadas = await projetor.projetar_ao_vivo(lote)
        except EspacoIndisponivel:
            return

        por_sessao: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for posicao, (session, participante, _) in enumerate(pendentes):
            por_sessao[session].append(
                {
                    "participante": participante,
                    "nome": self.nome_de(session, participante),
                    "pca": coordenadas["pca"][posicao],
                    "umap": coordenadas["umap"][posicao],
                    "tsne": coordenadas["tsne"][posicao],
                }
            )
            async with self._lock:
                self._janelas_emitidas[(session, participante)] += 1

        for session, pontos in por_sessao.items():
            await self._avisar_dashboards(
                session,
                {
                    "type": "projection-live",
                    "session": session,
                    "pontos": pontos,
                    "quando": int(time.time() * 1000),
                },
            )

    async def gerenciar(self, session: str, comando: dict[str, Any]) -> dict[str, Any]:
        """Gestão da turma pelo painel: tirar da sala, corrigir nome, apagar.

        Quem conduz a aula precisa arrumar a lista na hora — um aparelho preso,
        um nome digitado errado, uma gravação de teste no meio da turma. Sem
        isto a única saída era apagar tudo de todo mundo.
        """
        acao = comando["acao"]
        numero = comando["participante"]
        if acao == "remover":
            return await self._remover_participante(session, numero)
        if acao == "renomear":
            return await self._renomear_participante(session, numero, comando["nome"])
        return await self._esquecer_participante(numero)

    async def _remover_participante(self, session: str, numero: int) -> dict[str, Any]:
        async with self._lock:
            alvos = [
                websocket
                for websocket, atribuido in self._participantes.get(session, {}).items()
                if atribuido == numero
            ]
        for websocket in alvos:
            # fechar dispara o disconnect() do laço, que devolve nome e número
            try:
                await websocket.close(code=1000, reason="Removido pelo painel.")
            except Exception:
                pass
        return {"acao": "remover", "participante": numero, "aparelhos": len(alvos)}

    async def _renomear_participante(
        self, session: str, numero: int, nome: str
    ) -> dict[str, Any]:
        """Corrigir o nome vale também para o que a pessoa já gravou.

        Só na sala não bastaria: as gravações guardam o nome de quando foram
        feitas, então um nome errado continuaria no mapa e no filtro para
        sempre.
        """
        async with self._lock:
            presente = numero in set(self._participantes.get(session, {}).values())
            if presente:
                self._nomes[session][numero] = nome
            corrigidas = 0
            for gravacao in self._projetadas:
                if gravacao.get("participante") == numero:
                    gravacao["nome"] = nome
                    corrigidas += 1
            if corrigidas:
                self._gravar_no_disco()
        await self.broadcast_status(session)
        if corrigidas:
            await self.avisar_todos_os_paineis({"type": "gravacoes-atualizadas"})
        return {
            "acao": "renomear",
            "participante": numero,
            "nome": nome,
            "gravacoes": corrigidas,
        }

    async def _esquecer_participante(self, numero: int) -> dict[str, Any]:
        async with self._lock:
            antes = len(self._projetadas)
            self._projetadas = [
                gravacao
                for gravacao in self._projetadas
                if gravacao.get("participante") != numero
            ]
            apagadas = antes - len(self._projetadas)
            if apagadas:
                self._gravar_no_disco()
        if apagadas:
            await self.avisar_todos_os_paineis({"type": "gravacoes-atualizadas"})
        return {"acao": "esquecer", "participante": numero, "gravacoes": apagadas}

    async def avisar_todos_os_paineis(self, mensagem: dict[str, Any]) -> None:
        """Apagar vale para a instalação inteira, não para uma sessão só.

        O laboratório guarda as gravações na memória da página. Sem este
        aviso ele continuaria desenhando gente que já não existe no relay
        até alguém recarregar — e aí ele não seria tempo real de verdade,
        só um acumulador que nunca esquece.
        """
        async with self._lock:
            paineis = {ws for grupo in self._dashboards.values() for ws in grupo}
        await self._send_many(paineis, mensagem)

    async def _avisar_dashboards(self, session: str, mensagem: dict[str, Any]) -> None:
        async with self._lock:
            dashboards = set(self._dashboards.get(session, set()))
        await self._send_many(dashboards, mensagem)

    async def broadcast_status(self, session: str) -> None:
        async with self._lock:
            presentes = sorted(set(self._participantes.get(session, {}).values()))
            nomes = self._nomes.get(session, {})
            status = {
                "type": "relay-status",
                "session": session,
                "mobile_connections": len(self._mobiles.get(session, set())),
                "dashboard_connections": len(self._dashboards.get(session, set())),
                "participantes": presentes,
                "turma": [
                    {"participante": numero, "nome": nomes.get(numero, f"Participante {numero}")}
                    for numero in presentes
                ],
            }
            sockets = set(self._dashboards.get(session, set())) | set(
                self._mobiles.get(session, set())
            )
        await self._send_many(sockets, status)

    async def _send_many(self, sockets: set[WebSocket], message: dict[str, Any]) -> None:
        async def send_one(websocket: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=1.0)
                return None
            except Exception:
                return websocket

        stale = [
            websocket
            for websocket in await asyncio.gather(
                *(send_one(websocket) for websocket in tuple(sockets))
            )
            if websocket is not None
        ]
        if stale:
            async with self._lock:
                for websocket in stale:
                    for registry in (self._dashboards, self._mobiles):
                        for session_sockets in registry.values():
                            session_sockets.discard(websocket)


hub = SessionHub()
projetor = ProjetorHarLive()
app = FastAPI(title="HAR Participante 31 — relay", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=LIVE_DIR), name="live-assets")
if (ROOT / "web").is_dir():
    # Mesma origem do relay: o laboratório consegue buscar as gravações sem CORS.
    app.mount(
        "/laboratorio",
        StaticFiles(directory=ROOT / "web", html=True),
        name="laboratorio",
    )


@app.on_event("startup")
async def preparar_servidor() -> None:
    # Aquecer antes da aula: a primeira projeção compila código e levaria
    # segundos justamente quando o primeiro aluno gravasse.
    asyncio.create_task(projetor.aquecer())
    asyncio.create_task(hub.ciclo_ao_vivo())
    asyncio.create_task(hub.varrer_silenciosos())


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/laboratorio"):
        # O laboratório é conteúdo local e estático, mas o motor de template e o
        # ECharts compilam funções em tempo de execução. A permissão fica presa
        # a esta rota; a captura, que recebe dados de fora, mantém a regra dura.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self' ws: wss:; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
    response.headers["Permissions-Policy"] = (
        "accelerometer=(self), gyroscope=(self), magnetometer=()"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/dashboard")


@app.get("/mobile")
async def mobile_page() -> FileResponse:
    return FileResponse(LIVE_DIR / "mobile.html")


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(LIVE_DIR / "dashboard.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(LIVE_DIR / "admin.html")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "har-live-relay",
        "protocol": 2,
        "har_live": projetor.disponivel,
    }


@app.get("/api/har-live/referencia")
async def referencia_har_live(request: Request) -> JSONResponse:
    """Mapa de fundo: as 10.299 janelas do HAR no espaço compartilhado."""
    if not token_http_valido(request):
        return recusa_sem_token()
    caminho = LIVE_SPACE_DIR / "referencia.json"
    if not caminho.exists():
        return JSONResponse(
            {"erro": "Espaço HAR live não construído."}, status_code=404
        )
    return JSONResponse(json.loads(caminho.read_text(encoding="utf-8")))


@app.get("/api/qr")
async def qr_da_sala(request: Request) -> Response:
    """QR da aula, desenhado no servidor.

    Codifica o link de captura COM o token dos alunos e SEM número: a reserva
    de participante é automática, então o mesmo código serve a turma inteira.
    Quem pede é quem conduz a aula, por isso exige o token de admin — o de
    aluno não deve conseguir descobrir nada por aqui.
    """
    if not token_http_valido(request, ADMIN_TOKEN):
        return recusa_sem_token()

    import qrcode
    import qrcode.image.svg

    session = hub.normalize_session(request.query_params.get("session"))
    base = str(request.base_url).rstrip("/")
    destino = f"{base}/mobile?session={session}&token={ACCESS_TOKEN}"

    if request.query_params.get("formato") == "json":
        # o painel usa isto para mostrar o link por extenso, para quem não
        # consegue escanear — e serve de conferência do que o QR carrega
        return JSONResponse({"destino": destino})

    codigo = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    codigo.add_data(destino)
    codigo.make(fit=True)
    buffer = io.BytesIO()
    codigo.make_image().save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/har-live/gravacoes")
async def gravacoes_har_live(request: Request) -> JSONResponse:
    """Gravações já projetadas, para o laboratório desenhar.

    É o dado mais sensível do serviço: movimento do corpo de quem gravou.
    """
    if not token_http_valido(request):
        return recusa_sem_token()
    return JSONResponse({"gravacoes": hub.gravacoes_projetadas()})


@app.delete("/api/har-live/gravacoes")
async def apagar_gravacoes_har_live(request: Request) -> JSONResponse:
    """Apagar é ação de quem conduz a aula: exige o token de admin."""
    if not token_http_valido(request, ADMIN_TOKEN):
        return recusa_sem_token()
    apagadas = hub.apagar_gravacoes()
    await hub.avisar_todos_os_paineis(
        {"type": "gravacoes-apagadas", "apagadas": apagadas}
    )
    return JSONResponse({"apagadas": apagadas})


@app.get("/api/har-live/metricas")
async def metricas_har_live(request: Request) -> JSONResponse:
    if not token_http_valido(request):
        return recusa_sem_token()
    caminho = LIVE_SPACE_DIR / "metricas.json"
    if not caminho.exists():
        return JSONResponse(
            {"erro": "Espaço HAR live não construído."}, status_code=404
        )
    return JSONResponse(json.loads(caminho.read_text(encoding="utf-8")))


def token_is_valid(websocket: WebSocket, esperado: str | None = None) -> bool:
    supplied = websocket.query_params.get("token") or ""
    return bool(supplied) and secrets.compare_digest(supplied, esperado or ACCESS_TOKEN)


def token_http_valido(request: Request, esperado: str | None = None) -> bool:
    """Mesma credencial dos WebSockets, por query ou cabeçalho.

    As rotas do HAR live devolvem a projeção de gravações do próprio corpo do
    usuário; elas exigem o token de pareamento como o restante do relay.
    """
    fornecido = request.query_params.get("token") or request.headers.get("x-har-token") or ""
    return bool(fornecido) and secrets.compare_digest(fornecido, esperado or ACCESS_TOKEN)


def recusa_sem_token() -> JSONResponse:
    return JSONResponse({"erro": "Token de pareamento ausente ou inválido."}, status_code=403)


class ControleDeTaxa:
    """Teto de mensagens por conexão, medido numa janela deslizante.

    Fica por conexão de propósito: numa sala a turma inteira costuma sair pelo
    mesmo IP, então limitar por endereço puniria todo mundo junto.
    """

    def __init__(self, teto: int = MAX_MENSAGENS_POR_SEGUNDO, janela: float = JANELA_DE_TAXA) -> None:
        self._teto = teto
        self._janela = janela
        self._inicio = time.monotonic()
        self._contagem = 0

    def excedeu(self) -> bool:
        agora = time.monotonic()
        if agora - self._inicio >= self._janela:
            self._inicio = agora
            self._contagem = 0
        self._contagem += 1
        return self._contagem > self._teto * self._janela


async def websocket_loop(websocket: WebSocket, role: str) -> None:
    esperado = ADMIN_TOKEN if role == "admin" else ACCESS_TOKEN
    if not token_is_valid(websocket, esperado):
        await websocket.close(code=1008, reason="Token de pareamento inválido.")
        return
    session = hub.normalize_session(websocket.query_params.get("session"))
    pedido = hub.normalizar_participante(websocket.query_params.get("participante"))
    chave_do_aparelho = ""
    if role == "mobile":
        try:
            participante, chave_do_aparelho = await hub.reservar_participante(
                session, pedido, websocket.query_params.get("chave")
            )
        except SalaLotada as erro:
            await websocket.close(code=1013, reason=str(erro))
            return
    else:
        participante = pedido
    if not await hub.connect(role, session, websocket, participante):
        return
    if role == "mobile":
        # o aparelho precisa saber com que número ficou, para exibir e para o
        # aluno conferir com quem conduz a aula
        await websocket.send_json({
            "type": "participante-atribuido",
            "participante": participante,
            "pedido": pedido,
            "trocado": participante != pedido,
            # o aparelho guarda a chave para reaver o mesmo número se a página
            # recarregar; ela não vale para mais nada
            "chave": chave_do_aparelho,
        })
    invalid_messages = 0
    taxa = ControleDeTaxa()
    try:
        while True:
            if role == "mobile":
                try:
                    message = sanitize_mobile_message(await websocket.receive_json())
                except (MessageValidationError, TypeError, ValueError) as error:
                    invalid_messages += 1
                    await websocket.send_json(
                        {"type": "error", "message": str(error)[:240]}
                    )
                    if invalid_messages >= 3:
                        await websocket.close(
                            code=1008,
                            reason="Muitas mensagens inválidas.",
                        )
                        return
                    continue
                if taxa.excedeu():
                    await websocket.close(code=1008, reason="Mensagens em excesso.")
                    return
                invalid_messages = 0
                hub.anotar_sinal(websocket)
                if message["type"] == "keepalive":
                    continue
                if message["type"] == "hello" and message.get("nome"):
                    await hub.registrar_nome(session, participante, message["nome"])
                await hub.relay_from_mobile(session, message, participante)
            elif role == "admin":
                # O único papel que fala com os aparelhos. Vocabulário fechado.
                try:
                    comando = sanitizar_comando(await websocket.receive_json())
                except (MessageValidationError, TypeError, ValueError) as error:
                    invalid_messages += 1
                    await websocket.send_json(
                        {"type": "error", "message": str(error)[:240]}
                    )
                    if invalid_messages >= 5:
                        await websocket.close(code=1008, reason="Comandos inválidos.")
                        return
                    continue
                if taxa.excedeu():
                    await websocket.close(code=1008, reason="Comandos em excesso.")
                    return
                invalid_messages = 0
                if comando["type"] == "gestao":
                    resultado = await hub.gerenciar(session, comando)
                    await websocket.send_json({"type": "gestao-ok", **resultado})
                    continue
                comando["enviado_em"] = int(time.time() * 1000)
                alcancados = await hub.enviar_comando(session, comando)
                await websocket.send_json(
                    {"type": "comando-ok", "acao": comando["acao"], "aparelhos": alcancados}
                )
            else:
                await websocket.receive_text()
                await websocket.send_json(
                    {"type": "error", "message": "Dashboard é somente leitura."}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(role, session, websocket)


@app.websocket("/ws/mobile")
async def mobile_socket(websocket: WebSocket) -> None:
    await websocket_loop(websocket, "mobile")


@app.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket) -> None:
    await websocket_loop(websocket, "admin")


@app.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket) -> None:
    await websocket_loop(websocket, "dashboard")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Servidor do modo Participante 31.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ssl-certfile", type=Path)
    parser.add_argument("--ssl-keyfile", type=Path)
    parser.add_argument(
        "--token",
        help="Token temporário de pareamento; se omitido, gera um valor aleatório.",
    )
    parser.add_argument(
        "--token-admin",
        help="Token de quem comanda a turma; separado do token dos participantes.",
    )
    return parser.parse_args()


def main() -> None:
    global ACCESS_TOKEN, ADMIN_TOKEN
    args = parse_args()
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        raise SystemExit("Informe --ssl-certfile e --ssl-keyfile juntos.")
    if args.token:
        if len(args.token) < 12:
            raise SystemExit("O token precisa ter pelo menos 12 caracteres.")
        ACCESS_TOKEN = args.token
    if args.token_admin:
        if len(args.token_admin) < 12:
            raise SystemExit("O token de admin precisa ter pelo menos 12 caracteres.")
        ADMIN_TOKEN = args.token_admin
    if secrets.compare_digest(ADMIN_TOKEN, ACCESS_TOKEN):
        raise SystemExit("O token de admin precisa ser diferente do token dos participantes.")
    print("\nParticipante 31 — URLs locais")
    print(
        f"Dashboard: http://127.0.0.1:{args.port}/dashboard"
        f"?session=P31&token={ACCESS_TOKEN}"
    )
    print(
        f"Captura:   http://127.0.0.1:{args.port}/mobile"
        f"?session=P31&token={ACCESS_TOKEN}"
    )
    print(
        f"Admin:     http://127.0.0.1:{args.port}/admin"
        f"?session=P31&token={ADMIN_TOKEN}"
    )
    print("Use o mesmo token na URL HTTPS fornecida pelo túnel.")
    print("O token de admin comanda a turma: não o distribua junto com o dos alunos.\n")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=str(args.ssl_certfile) if args.ssl_certfile else None,
        ssl_keyfile=str(args.ssl_keyfile) if args.ssl_keyfile else None,
        log_level="warning",
        access_log=False,
        ws_max_size=MAX_WEBSOCKET_BYTES,
        ws_ping_interval=15.0,
        ws_ping_timeout=10.0,
    )


if __name__ == "__main__":
    main()
