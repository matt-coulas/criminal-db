"""Minimal local HTTP JSON API for agents (stdlib only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import config
from .api import get_case, open_router, search
from .statutes import StatutesDatabase


class CriminalDbHandler(BaseHTTPRequestHandler):
    """JSON endpoints: ``/health``, ``/search``, ``/get``."""

    router = None  # set on server startup

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _auth_ok(self) -> bool:
        token = config.API_TOKEN
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {token}":
            return True
        return self.headers.get("X-API-Token") == token

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._json_response(200, {"status": "ok"})
            return

        if not self._auth_ok():
            self._json_response(401, {"error": "unauthorized"})
            return

        if path == "/search":
            query = (qs.get("q") or [""])[0]
            if not query:
                self._json_response(400, {"error": "missing q"})
                return
            mode = (qs.get("type") or ["fts"])[0].lower()
            scope = (qs.get("scope") or ["cases"])[0].lower()
            limit = int((qs.get("limit") or ["10"])[0])
            if scope == "statutes":
                db = StatutesDatabase()
                try:
                    if mode == "fts":
                        results = db.search_fts(query, limit=limit)
                    elif mode == "hybrid":
                        from .embedding import Embedder

                        vec = Embedder().encode_one(query)
                        results = db.search_hybrid(query, vec, limit=limit)
                    else:
                        self._json_response(
                            400, {"error": "statutes support fts or hybrid only"}
                        )
                        return
                    payload = [
                        {
                            "section": r.section_number,
                            "heading": r.heading,
                            "text": r.text,
                            "score": r.score,
                        }
                        for r in results
                    ]
                finally:
                    db.close()
                self._json_response(
                    200, {"query": query, "scope": scope, "results": payload}
                )
                return
            if scope == "all":
                from .search_unified import search_all_fts, search_all_hybrid

                router = self.router or open_router()
                statutes = StatutesDatabase()
                try:
                    if mode == "hybrid":
                        from .embedding import Embedder

                        vec = Embedder().encode_one(query)
                        hits = search_all_hybrid(
                            query, vec, router=router, statutes=statutes, limit=limit
                        )
                    else:
                        if mode not in ("fts",):
                            self._json_response(
                                400, {"error": "scope=all supports fts or hybrid"}
                            )
                            return
                        hits = search_all_fts(
                            query, router=router, statutes=statutes, limit=limit
                        )
                    self._json_response(
                        200,
                        {
                            "query": query,
                            "scope": "all",
                            "results": [h.to_dict() for h in hits],
                        },
                    )
                finally:
                    statutes.close()
                return
            results = search(
                query,
                mode=mode,
                limit=limit,
                router=self.router or open_router(),
            )
            self._json_response(
                200,
                {
                    "query": query,
                    "scope": "cases",
                    "results": [
                        {
                            "canlii_ref": r.canlii_ref,
                            "score": r.score,
                            "text": r.text,
                            "paragraph_num": r.paragraph_num,
                        }
                        for r in results
                    ],
                },
            )
            return

        if path == "/get":
            citation = (qs.get("citation") or [""])[0]
            if not citation:
                self._json_response(400, {"error": "missing citation"})
                return
            case = get_case(citation, router=self.router or open_router())
            if case is None:
                self._json_response(404, {"error": "not found", "citation": citation})
                return
            self._json_response(200, case)
            return

        self._json_response(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._json_response(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/search":
            self._json_response(404, {"error": "not found"})
            return
        body = self._read_json_body()
        query = str(body.get("q") or body.get("query") or "")
        if not query:
            self._json_response(400, {"error": "missing q"})
            return
        mode = str(body.get("type") or "fts").lower()
        limit = int(body.get("limit") or 10)
        results = search(
            query, mode=mode, limit=limit, router=self.router or open_router()
        )
        self._json_response(
            200,
            {
                "query": query,
                "results": [
                    {"canlii_ref": r.canlii_ref, "score": r.score, "text": r.text}
                    for r in results
                ],
            },
        )


def serve(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Run the local JSON API until interrupted."""
    h = host or config.API_HOST
    p = port or config.API_PORT
    router = open_router()
    CriminalDbHandler.router = router
    server = ThreadingHTTPServer((h, p), CriminalDbHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        router.close()
        server.server_close()
