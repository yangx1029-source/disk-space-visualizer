"""Hardened local HTTP server and versioned API for the DiskVis dashboard."""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import __version__
from .api import API_PREFIX, API_VERSION, DashboardAPIError, normalize_api_path
from .manager import DashboardManager, DashboardScanOptions
from .observability import close_dashboard_logger, create_dashboard_logger


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.version == 4 and address.is_loopback


@dataclass(frozen=True)
class DashboardConfig:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8765
    snapshot_dir: Path = Path.home() / ".diskvis" / "snapshots"
    log_dir: Path = Path.home() / ".diskvis" / "logs"
    top: int = 20
    min_size: int = 0
    include_duplicates: bool = False
    max_depth: int | None = 8
    max_nodes: int | None = 1500
    save_snapshot: bool = True
    request_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not _is_loopback_host(self.host):
            raise ValueError("dashboard host must be an IPv4 loopback address or localhost")
        if self.port < 0 or self.port > 65_535:
            raise ValueError("port must be between 0 and 65535")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")


class _DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


class DashboardServer:
    """Serve a single-user dashboard without exposing filesystem mutations."""

    def __init__(self, config: DashboardConfig) -> None:
        self.config = config
        self.instance_id = secrets.token_hex(6)
        self._started_monotonic = time.monotonic()
        self._logger, self.log_path, self.logging_error = create_dashboard_logger(
            config.log_dir,
            self.instance_id,
        )
        self._thread: threading.Thread | None = None
        self._serving = threading.Event()
        self._closing = threading.Event()
        self._finalized = threading.Event()
        self._lifecycle_lock = threading.Lock()
        try:
            self.manager = DashboardManager(
                DashboardScanOptions(
                    root=config.root,
                    snapshot_dir=config.snapshot_dir,
                    top=config.top,
                    min_size=config.min_size,
                    include_duplicates=config.include_duplicates,
                    max_depth=config.max_depth,
                    max_nodes=config.max_nodes,
                    save_snapshot=config.save_snapshot,
                ),
                logger=self._logger,
            )
            self._httpd = _DashboardHTTPServer(
                (config.host, config.port),
                self._handler_class(),
            )
        except BaseException:
            close_dashboard_logger(self._logger)
            raise
        self._allowed_hosts = {
            config.host.casefold(),
            "127.0.0.1",
            "localhost",
        }

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.address
        display_host = "127.0.0.1" if host.casefold() == "localhost" else host
        return f"http://{display_host}:{port}/"

    def start_scan(self) -> int:
        return self.manager.start_scan()

    def serve_forever(self, open_browser: bool = True) -> None:
        if self._finalized.is_set():
            raise RuntimeError("dashboard server is closed")
        if not self.manager.is_running and self.manager.status()["state"] == "idle":
            self.manager.start_scan()
        if open_browser:
            timer = threading.Timer(0.35, webbrowser.open, args=(self.url,))
            timer.daemon = True
            timer.start()
        self._serve_loop()

    def start_background(self, start_scan: bool = True) -> None:
        if self._finalized.is_set():
            raise RuntimeError("dashboard server is closed")
        if self._thread and self._thread.is_alive():
            return
        if start_scan and self.manager.status()["state"] == "idle":
            self.manager.start_scan()
        self._thread = threading.Thread(
            target=self._serve_loop,
            name=f"diskvis-dashboard-http-{self.instance_id}",
            daemon=True,
        )
        self._thread.start()
        self._serving.wait(timeout=2)

    def _serve_loop(self) -> None:
        self._serving.set()
        self._logger.info(
            "dashboard server started",
            extra={"event": "server_started", "state": "running"},
        )
        try:
            self._httpd.serve_forever(poll_interval=0.1)
        finally:
            self._finalize()

    def close(self) -> None:
        """Stop serving and scanning. Repeated calls are intentionally harmless."""
        if self._finalized.is_set():
            return
        self._closing.set()
        if self._serving.is_set():
            self._httpd.shutdown()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._finalize()

    def _finalize(self) -> None:
        with self._lifecycle_lock:
            if self._finalized.is_set():
                return
            self.manager.close()
            self._httpd.server_close()
            self._logger.info(
                "dashboard server stopped",
                extra={"event": "server_stopped", "state": "stopped"},
            )
            close_dashboard_logger(self._logger)
            self._finalized.set()

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        dashboard = self

        class DashboardHandler(BaseHTTPRequestHandler):
            server_version = f"DiskVisDashboard/{__version__}"
            sys_version = ""
            protocol_version = "HTTP/1.1"
            request_id = ""
            response_status = 0

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(dashboard.config.request_timeout_seconds)

            def log_message(self, format: str, *args: object) -> None:
                return

            def version_string(self) -> str:
                return self.server_version

            def do_GET(self) -> None:
                dashboard._dispatch(self, "GET")

            def do_POST(self) -> None:
                dashboard._dispatch(self, "POST")

            def do_HEAD(self) -> None:
                dashboard._dispatch(self, "HEAD")

            def do_PUT(self) -> None:
                dashboard._dispatch(self, "PUT")

            def do_PATCH(self) -> None:
                dashboard._dispatch(self, "PATCH")

            def do_DELETE(self) -> None:
                dashboard._dispatch(self, "DELETE")

            def do_OPTIONS(self) -> None:
                dashboard._dispatch(self, "OPTIONS")

            def do_TRACE(self) -> None:
                dashboard._dispatch(self, "TRACE")

            def do_CONNECT(self) -> None:
                dashboard._dispatch(self, "CONNECT")

        return DashboardHandler

    def _dispatch(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        handler.request_id = secrets.token_hex(8)  # type: ignore[attr-defined]
        handler.response_status = int(HTTPStatus.INTERNAL_SERVER_ERROR)  # type: ignore[attr-defined]
        started = time.perf_counter()
        try:
            self._validate_request(handler)
            if method == "GET":
                self._handle_get(handler)
            elif method == "POST":
                self._handle_post(handler)
            elif method == "HEAD":
                self._handle_head(handler)
            else:
                raise DashboardAPIError(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "METHOD_NOT_ALLOWED",
                    f"method {method} is not supported",
                )
        except DashboardAPIError as exc:
            self._send_error(handler, exc.status, exc.code, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            self._logger.info(
                "client disconnected",
                extra={
                    "event": "client_disconnected",
                    "request_id": handler.request_id,  # type: ignore[attr-defined]
                    "method": method,
                    "path": urlsplit(handler.path).path,
                },
            )
        except Exception as exc:
            self._logger.exception(
                "unhandled request failure",
                extra={
                    "event": "request_failed",
                    "request_id": handler.request_id,  # type: ignore[attr-defined]
                    "method": method,
                    "path": urlsplit(handler.path).path,
                    "error_type": type(exc).__name__,
                },
            )
            self._send_error(
                handler,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "an unexpected server error occurred",
            )
        finally:
            self._logger.info(
                "http request",
                extra={
                    "event": "http_request",
                    "request_id": handler.request_id,  # type: ignore[attr-defined]
                    "method": method,
                    "path": urlsplit(handler.path).path,
                    "status": handler.response_status,  # type: ignore[attr-defined]
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

    def _validate_request(self, handler: BaseHTTPRequestHandler) -> None:
        if len(handler.path) > 4096:
            raise DashboardAPIError(
                HTTPStatus.REQUEST_URI_TOO_LONG,
                "URI_TOO_LONG",
                "request URI is too long",
            )
        host_header = handler.headers.get("Host", "")
        host = self._parse_host(host_header, "Host")
        if host not in self._allowed_hosts:
            raise DashboardAPIError(
                HTTPStatus.MISDIRECTED_REQUEST,
                "UNTRUSTED_HOST",
                "request Host is not trusted",
            )
        origin = handler.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                origin_host = (parsed.hostname or "").casefold()
                origin_port = parsed.port or (80 if parsed.scheme == "http" else 443)
            except ValueError as exc:
                raise DashboardAPIError(
                    HTTPStatus.BAD_REQUEST,
                    "INVALID_HEADER",
                    "Origin header is invalid",
                ) from exc
            if (
                parsed.scheme != "http"
                or origin_host not in self._allowed_hosts
                or origin_port != self.address[1]
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise DashboardAPIError(
                    HTTPStatus.FORBIDDEN,
                    "UNTRUSTED_ORIGIN",
                    "request Origin is not trusted",
                )

    def _parse_host(self, value: str, header_name: str) -> str:
        try:
            parsed = urlsplit(f"//{value}")
            host = (parsed.hostname or "").casefold()
            port = parsed.port
        except ValueError as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_HEADER",
                f"{header_name} header is invalid",
            ) from exc
        if (
            not host
            or (port is not None and port != self.address[1])
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_HEADER",
                f"{header_name} header is invalid",
            )
        return host

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(handler.path)
        if parsed.path == "/":
            html, nonce = self._render_index()
            self._send_html(handler, html, nonce)
            return
        if parsed.path == "/health":
            self._send_json(
                handler,
                {
                    "status": "ok",
                    "version": __version__,
                    "api_version": API_VERSION,
                    "instance_id": self.instance_id,
                },
            )
            return
        if parsed.path == "/ready":
            status = self.manager.status()
            self._send_json(
                handler,
                {
                    "ready": not self._closing.is_set(),
                    "state": status["state"],
                    "has_result": status["has_result"],
                },
            )
            return
        route = normalize_api_path(parsed.path)
        if route is None:
            raise DashboardAPIError(
                HTTPStatus.NOT_FOUND,
                "NOT_FOUND",
                "resource not found",
            )
        try:
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        except ValueError as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_ARGUMENT",
                "query contains too many fields",
            ) from exc
        try:
            if route == "/status":
                value = self.manager.status()
            elif route == "/result":
                value = self.manager.result_data()
            elif route == "/tree":
                offset = self._query_int(query, "offset", 0, minimum=0, maximum=100_000)
                limit = self._query_int(query, "limit", 100, minimum=1, maximum=500)
                value = self.manager.tree_data(
                    query.get("path", [""])[0],
                    offset=offset,
                    limit=limit,
                )
            elif route == "/search":
                text = query.get("q", [""])[0]
                min_size = self._query_int(query, "min_size", 0, minimum=0)
                offset = self._query_int(query, "offset", 0, minimum=0, maximum=100_000)
                limit = self._query_int(query, "limit", 100, minimum=1, maximum=500)
                value = self.manager.search(text, min_size, limit, offset)
            elif route == "/history":
                value = self.manager.history_data()
            elif route == "/diagnostics":
                value = self.diagnostics()
            elif route == "/export/json":
                self._send_download(
                    handler,
                    self.manager.export_json_bytes(),
                    "application/json; charset=utf-8",
                    "diskvis-analysis.json",
                )
                return
            elif route == "/export/csv":
                self._send_download(
                    handler,
                    self.manager.export_csv_bytes(),
                    "text/csv; charset=utf-8",
                    "diskvis-files.csv",
                )
                return
            elif route == "/export/html":
                self._send_download(
                    handler,
                    self.manager.export_html_bytes(),
                    "text/html; charset=utf-8",
                    "diskvis-report.html",
                )
                return
            else:
                raise DashboardAPIError(
                    HTTPStatus.NOT_FOUND,
                    "NOT_FOUND",
                    "resource not found",
                )
        except KeyError as exc:
            raise DashboardAPIError(
                HTTPStatus.NOT_FOUND,
                "DIRECTORY_NOT_FOUND",
                str(exc),
            ) from exc
        except RuntimeError as exc:
            raise DashboardAPIError(
                HTTPStatus.CONFLICT,
                "RESULT_NOT_READY",
                str(exc),
            ) from exc
        except ValueError as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_ARGUMENT",
                str(exc),
            ) from exc
        self._send_json(handler, value)

    def _handle_head(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        if path not in {"/health", "/ready"}:
            raise DashboardAPIError(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "METHOD_NOT_ALLOWED",
                "HEAD is supported only for health endpoints",
            )
        self._begin_response(handler, HTTPStatus.OK, "application/json; charset=utf-8")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(handler.path)
        route = normalize_api_path(parsed.path)
        if route not in {"/scan", "/cancel"}:
            raise DashboardAPIError(
                HTTPStatus.NOT_FOUND,
                "NOT_FOUND",
                "resource not found",
            )
        self._read_json_body(handler)
        try:
            if route == "/scan":
                task_id = self.manager.start_scan()
                self._send_json(
                    handler,
                    {"task_id": task_id, "state": "running"},
                    status=HTTPStatus.ACCEPTED,
                )
            else:
                cancelled = self.manager.cancel()
                if not cancelled:
                    raise DashboardAPIError(
                        HTTPStatus.CONFLICT,
                        "NO_ACTIVE_SCAN",
                        "there is no active scan to cancel",
                    )
                self._send_json(
                    handler,
                    {"cancel_requested": True},
                    status=HTTPStatus.ACCEPTED,
                )
        except RuntimeError as exc:
            raise DashboardAPIError(
                HTTPStatus.CONFLICT,
                "SCAN_ALREADY_RUNNING",
                str(exc),
            ) from exc

    @staticmethod
    def _query_int(
        query: dict[str, list[str]],
        name: str,
        default: int,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        try:
            value = int(query.get(name, [str(default)])[0])
        except ValueError as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_ARGUMENT",
                f"{name} must be an integer",
            ) from exc
        if value < minimum or (maximum is not None and value > maximum):
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_ARGUMENT",
                f"{name} is outside the allowed range",
            )
        return value

    @staticmethod
    def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        if handler.headers.get("Transfer-Encoding"):
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "UNSUPPORTED_TRANSFER_ENCODING",
                "Transfer-Encoding is not supported",
            )
        content_type = handler.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.casefold() != "application/json":
            raise DashboardAPIError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "UNSUPPORTED_MEDIA_TYPE",
                "Content-Type must be application/json",
            )
        try:
            length = int(handler.headers.get("Content-Length", "0") or 0)
        except ValueError as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_CONTENT_LENGTH",
                "Content-Length must be a non-negative integer",
            ) from exc
        if length < 0:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_CONTENT_LENGTH",
                "Content-Length must be a non-negative integer",
            )
        if length > 1_000_000:
            raise DashboardAPIError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "BODY_TOO_LARGE",
                "request body is too large",
            )
        body = handler.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_JSON",
                "request body must be valid UTF-8 JSON",
            ) from exc
        if not isinstance(value, dict):
            raise DashboardAPIError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_JSON_OBJECT",
                "request body must be a JSON object",
            )
        return value

    def _render_index(self) -> tuple[str, str]:
        template_dir = Path(__file__).parent / "templates"
        environment = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(("html", "xml", "j2")),
        )
        nonce = secrets.token_urlsafe(18)
        template = environment.get_template("index.html.j2")
        return (
            template.render(
                nonce=nonce,
                app_version=__version__,
                api_prefix=API_PREFIX,
                root_path=str(self.manager.root),
            ),
            nonce,
        )

    def diagnostics(self) -> dict[str, Any]:
        status = self.manager.status()
        return {
            "application": {
                "name": "Disk Space Visualizer",
                "version": __version__,
                "api_version": API_VERSION,
                "instance_id": self.instance_id,
            },
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "process_id": os.getpid(),
                "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
            },
            "server": {
                "address": self.url,
                "logging_enabled": self.log_path is not None,
                "log_path": str(self.log_path) if self.log_path else None,
                "logging_error": self.logging_error,
                "python_executable": str(Path(sys.executable)),
            },
            "analysis": {
                "state": status["state"],
                "task_id": status["task_id"],
                "has_result": status["has_result"],
                "result_stale": status["result_stale"],
                "files_scanned": status["files_scanned"],
                "dirs_scanned": status["dirs_scanned"],
                "errors": status["errors"],
            },
        }

    def _base_headers(self, handler: BaseHTTPRequestHandler, content_type: str) -> None:
        handler.send_header("Content-Type", content_type)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Cross-Origin-Opener-Policy", "same-origin")
        handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
        handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        handler.send_header("X-DiskVis-Version", __version__)
        handler.send_header("X-DiskVis-API-Version", API_VERSION)
        handler.send_header("X-Request-ID", handler.request_id)  # type: ignore[attr-defined]

    def _begin_response(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        content_type: str,
    ) -> None:
        handler.response_status = int(status)  # type: ignore[attr-defined]
        handler.send_response(status)
        self._base_headers(handler, content_type)

    def _send_html(self, handler: BaseHTTPRequestHandler, html: str, nonce: str) -> None:
        data = html.encode("utf-8")
        self._begin_response(handler, HTTPStatus.OK, "text/html; charset=utf-8")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            f"script-src 'nonce-{nonce}'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(data)

    def _send_json(
        self,
        handler: BaseHTTPRequestHandler,
        value: Any,
        status: int = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._begin_response(handler, status, "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(data)

    def _send_download(
        self,
        handler: BaseHTTPRequestHandler,
        data: bytes,
        content_type: str,
        filename: str,
    ) -> None:
        self._begin_response(handler, HTTPStatus.OK, content_type)
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def _send_error(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        code: str,
        message: str,
    ) -> None:
        handler.close_connection = True
        self._send_json(
            handler,
            {
                "error": message,
                "code": code,
                "request_id": handler.request_id,  # type: ignore[attr-defined]
            },
            status=status,
        )


def run_dashboard(config: DashboardConfig, open_browser: bool = True) -> None:
    """Run a blocking dashboard server until interrupted."""
    server = DashboardServer(config)
    try:
        server.serve_forever(open_browser=open_browser)
    finally:
        server.close()
