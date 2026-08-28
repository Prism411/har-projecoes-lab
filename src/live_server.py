from __future__ import annotations

import argparse
import asyncio
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
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "live"
LIVE_SPACE_DIR = ROOT / "results" / "live-space"
GRAVACOES_ARQUIVO = ROOT / "gravacoes-iphone.json"
MAX_RECORDING_SAMPLES = 20000
MAX_GRAVACOES_GUARDADAS = 40
ACCESS_TOKEN = os.environ.get("HAR_LIVE_TOKEN") or secrets.token_urlsafe(18)
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
SUMMARY_REASONS = {"completed", "manual", "connection-lost", "page-hidden"}


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
    if message_type == "hello":
        return {
            "type": "hello",
            "role": "mobile",
            "secure": boolean_value(message.get("secure"), "secure"),
            "user_agent": short_text(
                message.get("user_agent", "desconhecido"),
                "user_agent",
                maximum=180,
            ),
        }
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
    """guarda os modelos do espaco compartilhado e projeta gravacoes.

    carregamento preguicoso: o relay continua de pe mesmo sem os modelos, e a
    projecao so fica disponivel depois que `src/build_live_space.py` rodou.
    `transform()` e pesado, entao roda fora do loop de eventos.
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


class SessionHub:
    def __init__(self) -> None:
        self._dashboards: dict[str, set[WebSocket]] = defaultdict(set)
        self._mobiles: dict[str, set[WebSocket]] = defaultdict(set)
        self._last_message: dict[str, dict[str, Any]] = {}
        self._gravacoes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._projetadas: list[dict[str, Any]] = self._ler_do_disco()
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_session(value: str | None) -> str:
        cleaned = "".join(character for character in (value or "P31").upper() if character.isalnum() or character in "-_")
        return cleaned[:24] or "P31"

    async def connect(self, role: str, session: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            target = self._mobiles if role == "mobile" else self._dashboards
            target[session].add(websocket)
            last_message = self._last_message.get(session)
        await self.broadcast_status(session)
        if role == "dashboard" and last_message is not None:
            await websocket.send_json(last_message)

    async def disconnect(self, role: str, session: str, websocket: WebSocket) -> None:
        async with self._lock:
            target = self._mobiles if role == "mobile" else self._dashboards
            target[session].discard(websocket)
            if not target[session]:
                target.pop(session, None)
        await self.broadcast_status(session)

    async def relay_from_mobile(self, session: str, message: dict[str, Any]) -> None:
        forwarded = dict(message)
        forwarded["session"] = session
        forwarded["server_received_at"] = int(time.time() * 1000)
        async with self._lock:
            self._last_message[session] = forwarded
            dashboards = set(self._dashboards.get(session, set()))
        await self._send_many(dashboards, forwarded)
        await self._acompanhar_gravacao(session, message)

    async def _acompanhar_gravacao(self, session: str, message: dict[str, Any]) -> None:
        """junta as amostras da gravacao e projeta quando ela termina."""
        tipo = message.get("type")
        if tipo == "recording" and message.get("status") == "started":
            async with self._lock:
                self._gravacoes[session] = []
            return
        if tipo == "samples" and message.get("recording"):
            async with self._lock:
                acumulado = self._gravacoes[session]
                if len(acumulado) < MAX_RECORDING_SAMPLES:
                    acumulado.extend(message.get("samples", []))
            return
        if tipo == "summary":
            async with self._lock:
                amostras = self._gravacoes.pop(session, [])
            if amostras:
                asyncio.create_task(
                    self._projetar_gravacao(session, amostras, message)
                )

    async def _projetar_gravacao(
        self,
        session: str,
        amostras: list[dict[str, Any]],
        resumo: dict[str, Any],
    ) -> None:
        await self._avisar_dashboards(
            session, {"type": "projection-status", "status": "calculando"}
        )
        try:
            resultado = await projetor.projetar(amostras)
        except EspacoIndisponivel as erro:
            await self._avisar_dashboards(
                session,
                {"type": "projection-status", "status": "indisponivel", "message": str(erro)},
            )
            return
        except Exception as erro:  # gravacao curta ou sinal inutilizavel
            await self._avisar_dashboards(
                session,
                {
                    "type": "projection-status",
                    "status": "falhou",
                    "message": str(erro)[:240],
                },
            )
            return
        resultado.update(
            {
                "type": "projection",
                "session": session,
                "atividade": resumo.get("activity"),
                "server_received_at": int(time.time() * 1000),
            }
        )
        async with self._lock:
            self._last_message[session] = resultado
            self._projetadas.append(
                {
                    "atividade": resultado.get("atividade"),
                    "coordenadas": resultado.get("coordenadas", []),
                    "coordenadas_pca": resultado.get("coordenadas_pca", []),
                    "coordenadas_tsne": resultado.get("coordenadas_tsne", []),
                    "situacoes": resultado.get("situacoes", []),
                    "quando": resultado.get("server_received_at"),
                }
            )
            del self._projetadas[:-MAX_GRAVACOES_GUARDADAS]
            self._gravar_no_disco()
        await self._avisar_dashboards(session, resultado)

    def gravacoes_projetadas(self) -> list[dict[str, Any]]:
        return list(self._projetadas)

    @staticmethod
    def _ler_do_disco() -> list[dict[str, Any]]:
        """gravacao precisa sobreviver a um reinicio do servidor."""
        if not GRAVACOES_ARQUIVO.exists():
            return []
        try:
            conteudo = json.loads(GRAVACOES_ARQUIVO.read_text(encoding="utf-8"))
            gravacoes = conteudo.get("gravacoes", [])
            return gravacoes if isinstance(gravacoes, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _gravar_no_disco(self) -> None:
        """escrita atomica e legivel so pelo dono.

        o arquivo guarda movimento corporal de quem gravou. um write direto
        deixaria o arquivo truncado se o servidor caisse no meio; o temporario
        seguido de replace garante que ou fica inteiro, ou fica intacto.
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
            temporario.unlink(missing_ok=True)  # a sessao atual continua servindo

    async def _avisar_dashboards(self, session: str, mensagem: dict[str, Any]) -> None:
        async with self._lock:
            dashboards = set(self._dashboards.get(session, set()))
        await self._send_many(dashboards, mensagem)

    async def broadcast_status(self, session: str) -> None:
        async with self._lock:
            status = {
                "type": "relay-status",
                "session": session,
                "mobile_connections": len(self._mobiles.get(session, set())),
                "dashboard_connections": len(self._dashboards.get(session, set())),
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
    # mesma origem do relay: laboratorio busca as gravacoes sem CORS
    app.mount(
        "/laboratorio",
        StaticFiles(directory=ROOT / "web", html=True),
        name="laboratorio",
    )


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/laboratorio"):
        # laboratorio e conteudo local e estatico, mas o motor de template e o
        # echarts compilam funcao em tempo de execucao. a permissao fica presa
        # nessa rota; a captura, que recebe dado de fora, mantem a regra dura
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
    """mapa de fundo: as 10.299 janelas do HAR no espaco compartilhado."""
    if not token_http_valido(request):
        return recusa_sem_token()
    caminho = LIVE_SPACE_DIR / "referencia.json"
    if not caminho.exists():
        return JSONResponse(
            {"erro": "Espaço HAR live não construído."}, status_code=404
        )
    return JSONResponse(json.loads(caminho.read_text(encoding="utf-8")))


@app.get("/api/har-live/gravacoes")
async def gravacoes_har_live(request: Request) -> JSONResponse:
    """gravacoes ja projetadas, pro laboratorio desenhar.

    e o dado mais sensivel do servico: movimento do corpo de quem gravou.
    """
    if not token_http_valido(request):
        return recusa_sem_token()
    return JSONResponse({"gravacoes": hub.gravacoes_projetadas()})


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


def token_is_valid(websocket: WebSocket) -> bool:
    supplied = websocket.query_params.get("token") or ""
    return bool(supplied) and secrets.compare_digest(supplied, ACCESS_TOKEN)


def token_http_valido(request: Request) -> bool:
    """mesma credencial dos websockets, por query ou cabecalho.

    as rotas do HAR live devolvem a projecao de gravacoes do proprio corpo do
    usuario; exigem o token de pareamento igual ao resto do relay.
    """
    fornecido = request.query_params.get("token") or request.headers.get("x-har-token") or ""
    return bool(fornecido) and secrets.compare_digest(fornecido, ACCESS_TOKEN)


def recusa_sem_token() -> JSONResponse:
    return JSONResponse({"erro": "Token de pareamento ausente ou inválido."}, status_code=403)


async def websocket_loop(websocket: WebSocket, role: str) -> None:
    if not token_is_valid(websocket):
        await websocket.close(code=1008, reason="Token de pareamento inválido.")
        return
    session = hub.normalize_session(websocket.query_params.get("session"))
    await hub.connect(role, session, websocket)
    invalid_messages = 0
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
                invalid_messages = 0
                await hub.relay_from_mobile(session, message)
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
    return parser.parse_args()


def main() -> None:
    global ACCESS_TOKEN
    args = parse_args()
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        raise SystemExit("Informe --ssl-certfile e --ssl-keyfile juntos.")
    if args.token:
        if len(args.token) < 12:
            raise SystemExit("O token precisa ter pelo menos 12 caracteres.")
        ACCESS_TOKEN = args.token
    print("\nParticipante 31 — URLs locais")
    print(
        f"Dashboard: http://127.0.0.1:{args.port}/dashboard"
        f"?session=P31&token={ACCESS_TOKEN}"
    )
    print(
        f"Captura:   http://127.0.0.1:{args.port}/mobile"
        f"?session=P31&token={ACCESS_TOKEN}"
    )
    print("Use o mesmo token na URL HTTPS fornecida pelo túnel.\n")
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
