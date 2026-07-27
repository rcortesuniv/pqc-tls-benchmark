#!/usr/bin/env python3
"""Serve the newest benchmark dashboard, regenerating it on each request."""
from __future__ import annotations

import argparse
import pathlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dashboard import dashboard_data, refresh_analysis, render_dashboard


def newest_result_dir(project: pathlib.Path) -> pathlib.Path | None:
    results = project / "results"
    candidates = [
        path for path in results.glob("pqc-tls-*")
        if path.is_dir() and (path / "raw").is_dir() and (path / "config.snapshot.json").is_file()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def landing_page() -> str:
    return """<!doctype html><html lang="en"><meta charset="utf-8"><title>PQC TLS dashboard</title>
<body><h1>PQC TLS benchmark dashboard</h1><p>No result directory is available yet.</p>
<p>Run a benchmark, then refresh this page.</p></body></html>"""


def make_handler(project: pathlib.Path) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path not in ("/", "/dashboard.html"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            result_dir = newest_result_dir(project)
            if result_dir is None:
                page = landing_page()
            else:
                refresh_analysis(result_dir)
                page = render_dashboard(dashboard_data(result_dir))
            encoded = page.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            print(f"dashboard: {format % args}")

    return DashboardHandler


def main() -> int:
    project = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(project))
    print(f"Dashboard server listening on http://{args.bind}:{args.port}/dashboard.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
