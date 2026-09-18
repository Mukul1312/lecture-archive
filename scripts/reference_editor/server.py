"""Local, single-user web editor for turning a subtitle file into a verified reference.

    python -m scripts.reference_editor --srt data/reference/X.srt --audio <archive.org URL or local file>

It binds 127.0.0.1 only. Every save replaces the review JSON atomically, keeps the
previous version as ``.bak`` and a timestamped snapshot at most every ten minutes,
because the listening work it records cannot be regenerated.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

from . import review as review_model


STATIC_DIR = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}
DEFAULT_PORT = 8770
MAX_BODY_BYTES = 5 * 1024 * 1024
SNAPSHOT_INTERVAL_S = 600
EDITOR_HEADER = "X-Reference-Editor"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "media-src 'self' https://archive.org https://*.archive.org; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class ReviewStore:
    """The review file on disk plus the subtitle baseline it must stay faithful to."""

    def __init__(self, srt_path: Path, review_path: Path, audio: str) -> None:
        self.baseline = review_model.new_review(srt_path.read_bytes(), source_name=srt_path.name, audio=audio)
        self.review_path = review_path
        self.snapshot_dir = review_path.with_name(review_path.stem + "-snapshots")
        self._lock = threading.Lock()
        self._last_snapshot: float | None = None
        if review_path.exists():
            try:
                loaded = json.loads(review_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise review_model.ReviewError(
                    f"{review_path.name} is not valid JSON ({error}); restore it from its .bak or snapshots"
                ) from error
            self.current = review_model.validate_review(loaded, baseline=self.baseline)
        else:
            self.current = review_model.validate_review(self.baseline, baseline=self.baseline)
            self._write(self.current)

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self.current))

    def save(self, submitted: object) -> dict:
        clean = review_model.validate_review(submitted, baseline=self.baseline)
        with self._lock:
            self._write(clean)
            self.current = clean
        return clean

    def _write(self, data: dict) -> None:
        self.review_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
        fd, temporary = tempfile.mkstemp(dir=self.review_path.parent, prefix=self.review_path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.review_path.exists():
                shutil.copy2(self.review_path, self.review_path.with_name(self.review_path.name + ".bak"))
            os.replace(temporary, self.review_path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
        now = time.monotonic()
        if self._last_snapshot is None or now - self._last_snapshot >= SNAPSHOT_INTERVAL_S:
            self.snapshot_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            shutil.copy2(self.review_path, self.snapshot_dir / f"{self.review_path.stem}-{stamp}.json")
            self._last_snapshot = now


class EditorHandler(BaseHTTPRequestHandler):
    server_version = "ReferenceEditor/1"
    store: ReviewStore
    audio_path: Path | None = None
    audio_url: str | None = None

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if not self._host_is_local():
            return self._text(HTTPStatus.MISDIRECTED_REQUEST, "unexpected Host header")
        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            return self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), content_type)
        if path == "/api/review":
            data = self.store.snapshot()
            data["audio_src"] = "/audio" if self.audio_path else self.audio_url
            data["counts"] = review_model.counts(data)
            return self._json(HTTPStatus.OK, data)
        stem = Path(self.store.baseline["source_srt"]).stem
        if path == "/api/export.srt":
            body = review_model.export_srt(self.store.snapshot()).encode("utf-8")
            return self._send(HTTPStatus.OK, body, "text/plain; charset=utf-8", attachment=f"{stem}-verified.srt")
        if path == "/api/changes.md":
            body = review_model.change_log(self.store.snapshot()).encode("utf-8")
            return self._send(HTTPStatus.OK, body, "text/markdown; charset=utf-8", attachment=f"{stem}-changes.md")
        if path == "/audio" and self.audio_path:
            return self._audio()
        return self._text(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        if not self._host_is_local():
            return self._text(HTTPStatus.MISDIRECTED_REQUEST, "unexpected Host header")
        if urlsplit(self.path).path != "/api/review":
            return self._text(HTTPStatus.NOT_FOUND, "not found")
        # A cross-site page cannot send a custom header without a CORS preflight this server never grants.
        if self.headers.get(EDITOR_HEADER) != "1":
            return self._json(HTTPStatus.FORBIDDEN, {"error": "missing editor header"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "expected application/json"})
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
        if not 0 < length <= MAX_BODY_BYTES:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body is empty or too large"})
        try:
            submitted = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "body is not UTF-8 JSON"})
        try:
            saved = self.store.save(submitted)
        except review_model.ReviewError as error:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except OSError as error:
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"could not write the review file: {error}"})
        saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self._json(HTTPStatus.OK, {"saved_at": saved_at, "counts": review_model.counts(saved)})

    def _host_is_local(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _audio(self) -> None:
        assert self.audio_path is not None
        size = self.audio_path.stat().st_size
        start, end, status = 0, size - 1, HTTPStatus.OK
        requested = self.headers.get("Range")
        if requested:
            match = _RANGE.fullmatch(requested.strip())
            if not match or not (match[1] or match[2]):
                return self._unsatisfiable(size)
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
            else:
                start, end = max(0, size - int(match[2])), size - 1
            if start >= size or start > end:
                return self._unsatisfiable(size)
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(self.audio_path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        remaining = end - start + 1
        with self.audio_path.open("rb") as handle:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(65_536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return  # players abandon range requests whenever the listener seeks
                remaining -= len(chunk)

    def _unsatisfiable(self, size: int) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, status: HTTPStatus, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _text(self, status: HTTPStatus, message: str) -> None:
        self._send(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, attachment: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(body)


def build_server(srt_path: Path, review_path: Path, audio: str, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    audio_path: Path | None = None
    audio_url: str | None = None
    if re.match(r"https?://", audio):
        host = (urlsplit(audio).hostname or "").lower()
        if urlsplit(audio).scheme != "https" or not (host == "archive.org" or host.endswith(".archive.org")):
            raise review_model.ReviewError("remote audio must be an https archive.org URL; otherwise pass a local file")
        audio_url = audio
    else:
        audio_path = Path(audio).resolve()
        if not audio_path.is_file():
            raise review_model.ReviewError(f"audio file not found: {audio}")
    store = ReviewStore(srt_path, review_path, audio)
    handler = type("BoundEditorHandler", (EditorHandler,), {
        "store": store, "audio_path": audio_path, "audio_url": audio_url,
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.reference_editor",
        description="Listen to audio and correct its subtitles, cue by cue, into a verified reference.",
    )
    parser.add_argument("--srt", required=True, type=Path, help="source subtitle file (never modified)")
    parser.add_argument("--audio", required=True, help="https archive.org URL or a local audio file")
    parser.add_argument("--review", type=Path, help="review JSON (default: <subtitle name>-review.json beside it)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    review_path = args.review or args.srt.with_name(args.srt.stem + "-review.json")
    try:
        server = build_server(args.srt, review_path, args.audio, args.port)
    except (review_model.ReviewError, OSError) as error:
        print(f"reference editor: {error}", file=sys.stderr)
        return 2
    print(f"Reference editor for {args.srt.name}: http://127.0.0.1:{server.server_address[1]}/")
    print(f"Every edit is saved to {review_path}. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
