"""Web command deck for DriftLab.

Stdlib-only HTTP server — no FastAPI, no template engine, no CDN. Serves the
single-page command deck plus a JSON API over the compliance store, and can
trigger cycles from the browser.

Local-only by construction: the socket binds loopback, and every ``/api/``
route additionally refuses non-loopback clients. Compliance evidence never
leaves the host.

Run:
    driftlab serve                       # http://127.0.0.1:8321
    python -m driftlab.web --port 9000
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import ipaddress
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import __version__
from . import runner, state

__all__ = ["main", "serve", "DeckHandler", "STATIC_DIR"]

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BYTES = 64_000
DEFAULT_PORT = 8321


def _is_loopback_bind_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _client_is_loopback(handler: BaseHTTPRequestHandler) -> bool:
    host = handler.client_address[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "127.0.0.1", "::1")


_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _split_host_header(value: str) -> tuple[str, str]:
    """``Host`` into ``(hostname, port)``, handling the ``[::1]:8321`` form."""
    if value.startswith("["):
        hostname, _, rest = value.partition("]")
        return hostname[1:], rest.lstrip(":")
    hostname, _, port = value.partition(":")
    return hostname, port


def _host_header_ok(handler: BaseHTTPRequestHandler) -> bool:
    """Pin the ``Host`` header to this listener.

    The peer-address check alone does not make the deck local-only: under a DNS
    rebinding attack the browser is the peer, so a page on any domain that
    re-resolves to 127.0.0.1 becomes same-origin with the deck and can read
    every ledger. Pinning Host is what actually closes that hole.
    """
    hostname, port = _split_host_header(handler.headers.get("Host", ""))
    if hostname.lower() not in _LOOPBACK_NAMES:
        return False
    expected = handler.server.server_address[1]
    if not port:
        return expected == 80
    try:
        return int(port) == expected
    except ValueError:
        return False


class DeckHandler(BaseHTTPRequestHandler):
    server_version = f"DriftLabDeck/{__version__}"

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        self._dispatch(self._get)

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        self._dispatch(self._post)

    def _dispatch(self, handler) -> None:
        """Common gate: pin the origin, then never die without a response.

        An unhandled exception here would close the socket mid-request and the
        deck would show a bare network error, hiding the real cause (a
        malformed registry, say). Answer 500 with the reason instead.
        """
        if not _host_header_ok(self):
            self._send_json({"error": "unrecognised Host header"}, status=421)
            return
        try:
            handler()
        except Exception as exc:
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"}, status=500
            )

    def _get(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") and not _client_is_loopback(self):
            self._send_json({"error": "deck APIs are restricted to loopback"}, status=403)
            return
        query = parse_qs(urlparse(self.path).query)

        if path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/favicon.svg":
            self._send_file(STATIC_DIR / "favicon.svg", "image/svg+xml")
        elif path == "/api/health":
            self._send_json({
                "ok": True,
                "version": __version__,
                "busy": runner.busy(),
                "narrative_busy": runner.narrative_busy(),
                "active_job_id": runner.active_job_id(),
            })
        elif path == "/api/llm":
            self._send_json(runner.llm_status())
        elif path == "/api/state":
            self._send_json(state.build_snapshot())
        elif path == "/api/agent":
            detail = state.agent_detail(str(query.get("id", [""])[0]))
            if detail is None:
                self._send_json({"error": "unknown agent"}, status=404)
            else:
                self._send_json(detail)
        elif path == "/api/events":
            self._send_json({
                "events": runner.live_events(limit=_int(query, "limit", 120)),
                "busy": runner.busy(),
            })
        elif path == "/api/jobs":
            self._send_json({"jobs": runner.list_jobs(), "busy": runner.busy()})
        elif path.startswith("/api/jobs/"):
            job = runner.get_job(path.rsplit("/", 1)[-1])
            self._send_json(job or {"error": "unknown job"}, status=200 if job else 404)
        elif path == "/api/narrative":
            self._send_json(runner.narrative_for(str(query.get("agent", [""])[0])))
        elif path == "/api/evidence":
            self._send_evidence(str(query.get("rel", [""])[0]))
        elif path == "/api/about":
            self._send_json(_about())
        else:
            self.send_error(404, "Not found")

    # -- POST --------------------------------------------------------------

    def _post(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/api/run", "/api/narrative"):
            self.send_error(404, "Not found")
            return
        if not _client_is_loopback(self):
            self._send_json(
                {"error": "run requests are restricted to the local deck"}, status=403
            )
            return

        body = self._read_json_body()
        if body is None:
            return  # _read_json_body already sent the error

        if path == "/api/run":
            job_id, error = runner.start_cycle_job(body)
        else:
            job_id, error = runner.start_narrative_job(str(body.get("agent") or ""))

        if error:
            status = 409 if ("running" in error or "already" in error) else 400
            self._send_json({"error": error}, status=status)
        else:
            self._send_json({"job_id": job_id}, status=202)

    def _read_json_body(self) -> dict[str, Any] | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            self._send_json({"error": "Content-Type must be application/json"}, status=415)
            return None
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._send_json({"error": "Content-Length is required"}, status=411)
            return None
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json({"error": "invalid Content-Length"}, status=400)
            return None
        if length < 0:
            self._send_json({"error": "invalid Content-Length"}, status=400)
            return None
        if length > MAX_REQUEST_BYTES:
            self._send_json({"error": "request body is too large"}, status=413)
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "invalid JSON body"}, status=400)
            return None
        if not isinstance(body, dict):
            self._send_json({"error": "JSON body must be an object"}, status=400)
            return None
        return body

    # -- responses ---------------------------------------------------------

    def _send_evidence(self, rel: str) -> None:
        found = state.read_artifact(rel)
        if found is None:
            self._send_json({"error": "unknown evidence artifact"}, status=404)
            return
        body, content_type = found
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # Air-gapped by policy: the deck must render with zero external fetches.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def _int(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(query.get(key, [str(default)])[0])
    except (ValueError, IndexError):
        return default


def _about() -> dict[str, Any]:
    from ..baseline import CONTROL_FAMILY

    settings = state.get_settings()
    return {
        "version": __version__,
        "registry": str(state.registry_path()),
        "data_dir": str(settings.data_dir),
        "artifacts_dir": str(settings.artifacts_dir),
        "db_path": str(settings.db_path),
        "llm_provider": settings.llm_provider,
        "controls": [
            {"id": c.id, "title": c.title, "description": c.description,
             "nist_800_53": list(c.nist_800_53), "is_ca7": c.is_ca7}
            for c in CONTROL_FAMILY
        ],
    }


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    query: str = "",
) -> None:
    """Start the command deck (blocks until Ctrl-C)."""
    if not _is_loopback_bind_host(host):
        raise SystemExit(
            "--host must be a loopback address or localhost; the command deck is "
            "intentionally local-only (compliance evidence never leaves the host)"
        )
    try:
        server = ThreadingHTTPServer((host, port), DeckHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"Port {port} is already in use — a deck instance is most likely")
            print(f"already running at http://{host}:{port}")
            print(f"(or pick another port: driftlab serve --port {port + 1})")
            raise SystemExit(1) from None
        raise

    url = f"http://{host}:{port}"
    if query:
        url = f"{url}/?{query.lstrip('?')}"
    print(f"DriftLab command deck → {url}  (Ctrl+C to stop)")
    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DriftLab web command deck")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open a browser tab on start.")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
