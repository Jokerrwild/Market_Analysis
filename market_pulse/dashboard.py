from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import add_tracked_crypto, remove_tracked_crypto
from .dashboard_data import build_dashboard_payload
from .ledger import add_transaction, delete_transaction, set_initial_capital, set_investment_goal


STATIC_DIR = Path(__file__).with_name("static")


class DashboardHandler(BaseHTTPRequestHandler):
    config_path = "config.json"
    ledger_path = "ledger.json"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            try:
                query = parse_qs(parsed.query)
                live_refresh = query.get("refresh", ["0"])[0] in {"1", "true", "yes"}
                self.send_json(
                    build_dashboard_payload(
                        self.config_path,
                        self.ledger_path,
                        live_refresh=live_refresh,
                    )
                )
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/shutdown":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_json({"ok": False, "error": "Shutdown is only allowed locally."}, HTTPStatus.FORBIDDEN)
                    return
                self.send_json({"ok": True, "message": "Market Pulse dashboard is stopping."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if parsed.path == "/api/capital":
                ledger = set_initial_capital(float(payload.get("initial_capital", 0)), self.ledger_path)
                self.send_json({"ok": True, "initial_capital": ledger.initial_capital})
                return
            if parsed.path == "/api/goal":
                ledger = set_investment_goal(
                    initial_capital=float(payload.get("initial_capital", 0)),
                    target_roi_pct=float(payload.get("target_roi_pct", 0)),
                    target_days=int(payload.get("target_days", 0)),
                    path=self.ledger_path,
                )
                self.send_json(
                    {
                        "ok": True,
                        "initial_capital": ledger.initial_capital,
                        "target_roi_pct": ledger.target_roi_pct,
                        "target_days": ledger.target_days,
                    }
                )
                return
            if parsed.path == "/api/transactions":
                transaction = add_transaction(payload, self.ledger_path)
                self.send_json({"ok": True, "transaction": transaction.__dict__}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/tracked":
                config = add_tracked_crypto(
                    asset=str(payload.get("asset", "")),
                    product_id=str(payload.get("product_id", "")),
                    path=self.config_path,
                )
                self.send_json({"ok": True, "tracked": config.get("crypto_assets", [])})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            prefix = "/api/transactions/"
            if parsed.path.startswith(prefix):
                transaction_id = unquote(parsed.path[len(prefix) :])
                if delete_transaction(transaction_id, self.ledger_path):
                    self.send_json({"ok": True})
                else:
                    self.send_json({"ok": False, "error": "Transaction not found"}, HTTPStatus.NOT_FOUND)
                return
            tracked_prefix = "/api/tracked/"
            if parsed.path.startswith(tracked_prefix):
                asset = unquote(parsed.path[len(tracked_prefix) :])
                config = remove_tracked_crypto(asset, self.config_path)
                self.send_json({"ok": True, "tracked": config.get("crypto_assets", [])})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            path = "/index.html"
        relative = path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        static_root = STATIC_DIR.resolve()
        if not str(target).startswith(str(static_root)) or not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def serve_dashboard(
    host: str = "127.0.0.1",
    port: int = 8765,
    config_path: str = "config.json",
    ledger_path: str = "ledger.json",
) -> None:
    handler = type(
        "ConfiguredDashboardHandler",
        (DashboardHandler,),
        {
            "config_path": config_path,
            "ledger_path": ledger_path,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Market Pulse dashboard running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Market Pulse dashboard stopped.")
    finally:
        server.server_close()
