"""Secured Narrator application shell; workflow routes are injected."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from hashlib import sha256

from heritage_archive.platform.web import WebRequest, WebResponse
from .security import ASSET_TYPES, ProcessSecurity, WebInputError, json_error, secure_response


class NarratorWebApplication:
    def __init__(self, security: ProcessSecurity, *, dispatch: Callable[[WebRequest], WebResponse] | None = None,
                 assets: Mapping[str, bytes] | None = None,
                 render_root: Callable[[str], bytes] | None = None):
        self._security = security
        self._dispatch = dispatch
        self._render_root = render_root
        self._assets = dict(assets or {})
        if any(path not in ASSET_TYPES or type(body) is not bytes for path, body in self._assets.items()):
            raise ValueError("invalid fixed assets")

    def error_response(self, status: int) -> WebResponse:
        """Prebuilt generic errors for failures outside the Narrator request handler."""
        codes = {400: "malformed_request", 500: "internal_error"}
        return secure_response(json_error(status, codes[status]))

    def __call__(self, request: WebRequest) -> WebResponse:
        asset = False
        try:
            headers = self._security.validate(request)
            read = request.method in {"GET", "HEAD"}
            if read and request.path == "/":
                body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="narrator-csrf" content="' + self._security.csrf_token + '">'
                        '<title>Narration studio</title><script src="/assets/studio.js" defer></script>'
                        '</head><body data-narrator-bootstrap><p>Opening the local studio. '
                        'If it does not open, enable cookies and reload this page.</p></body></html>').encode()
                if self._render_root is not None and self._security.has_current_session(headers):
                    body = self._render_root(self._security.csrf_token)
                response = WebResponse(200,
                    body,
                    ((b"content-type", b"text/html; charset=utf-8"),
                     (b"set-cookie", ("narrator_session=" + self._security.session_token + "; Path=/; HttpOnly; SameSite=Strict").encode())))
            elif read and request.path in ASSET_TYPES:
                if request.path not in self._assets:
                    response = json_error(404, "not_found")
                else:
                    body = self._assets[request.path]
                    etag = ('"' + sha256(body).hexdigest() + '"').encode()
                    response = WebResponse(200, body, ((b"content-type", ASSET_TYPES[request.path]), (b"etag", etag)))
                    if headers.get(b"if-none-match") == etag:
                        response = replace(response, status=304, body=b"")
                    asset = True
            elif self._dispatch is not None:
                response = self._dispatch(replace(request, method="GET") if request.method == "HEAD" else request)
            else:
                response = json_error(404, "not_found")
            return secure_response(response, head=request.method == "HEAD", asset=asset)
        except WebInputError as error:
            response = json_error(error.status, error.code)
        except Exception:
            response = json_error(500, "internal_error")
        return secure_response(response, head=request.method == "HEAD")
