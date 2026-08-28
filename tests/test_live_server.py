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

from live_server import (  # noqa: E402
    ACCESS_TOKEN,
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

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


class LiveServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_pages_and_health_are_served(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["service"], "har-live-relay")
        self.assertIn("Participante 31", self.client.get("/mobile").text)
        self.assertIn("Participante 31", self.client.get("/dashboard").text)

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
        )

        self.assertEqual(len(dashboard.messages), 1)
        relayed = dashboard.messages[0]
        self.assertEqual(relayed["session"], "TESTE")
        self.assertEqual(relayed["samples"][0]["acceleration"], [0.1, 0.2, 0.3])
        self.assertIn("server_received_at", relayed)


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
