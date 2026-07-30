#!/usr/bin/env python3
"""Serve the newest benchmark dashboard, regenerating it on each request."""
from __future__ import annotations

import argparse
import html
import pathlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dashboard import ANALYSIS_OUTPUTS, analysis_needs_refresh, dashboard_data, refresh_analysis, render_dashboard


def newest_result_dir(project: pathlib.Path) -> pathlib.Path | None:
    # A run directory is servable when its generated analysis outputs exist.
    # We do NOT require raw/ + config.snapshot.json: those are gitignored
    # runtime evidence that may be cleaned up once analysis has been produced.
    # Requiring them hid legitimate runs whose pre-rendered analysis was all
    # that remained, causing the dashboard to serve the empty landing page.
    results = project / "results"
    candidates = []
    for path in (results.iterdir() if results.is_dir() else []):
        if not path.is_dir():
            continue
        analysis_dir = path / "analysis"
        if analysis_dir.is_dir() and all(
            (analysis_dir / name).is_file() for name in ANALYSIS_OUTPUTS
        ):
            candidates.append(path)
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
            try:
                result_dir = newest_result_dir(project)
                if result_dir is None:
                    page = landing_page()
                else:
                    refresh_error = refresh_analysis(result_dir) if analysis_needs_refresh(result_dir) else None
                    data = dashboard_data(result_dir)
                    if refresh_error:
                        data["analysis_error"] = refresh_error
                    page = render_dashboard(data)
            except Exception as error:  # Avoid turning an application error into a proxy 502.
                page = f"<!doctype html><title>Dashboard error</title><h1>Dashboard error</h1><pre>{html.escape(str(error))}</pre>"
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
