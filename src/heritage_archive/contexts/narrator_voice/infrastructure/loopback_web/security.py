"""Process credentials, strict input and redacted HTTP responses."""

from dataclasses import dataclass, field, replace
import json
from math import isfinite
import re
import secrets

from heritage_archive.platform.web import MAX_BODY_BYTES, WebRequest, WebResponse


_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_SINGLE_HEADERS = frozenset({b"host", b"origin", b"content-type", b"x-narrator-csrf",
                             b"sec-fetch-site", b"cookie", b"content-length", b"transfer-encoding"})
ASSET_TYPES = {"/assets/studio.css": b"text/css; charset=utf-8",
               "/assets/studio.js": b"text/javascript; charset=utf-8"}
_SECURITY_HEADERS = (
    (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'"),
    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"), (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)


@dataclass(frozen=True, slots=True)
class ProcessSecurity:
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)

    def __post_init__(self):
        if not all(type(token) is str and _TOKEN.fullmatch(token) for token in (self.session_token, self.csrf_token)) or self.session_token == self.csrf_token:
            raise ValueError("invalid process security configuration")

    def validate(self, request: WebRequest) -> dict[bytes, bytes]:
        headers = checked_headers(request)
        session = _session_cookie(headers.get(b"cookie"))
        if b"host" not in headers:
            raise WebInputError(400, "malformed_request")
        if headers[b"host"] != b"127.0.0.1:8765":
            raise WebInputError(403, "invalid_host")
        if request.method not in {"GET", "HEAD", "POST"}:
            raise WebInputError(405, "method_not_allowed")
        public_read = request.method in {"GET", "HEAD"} and (request.path == "/" or request.path in ASSET_TYPES)
        if not public_read and not _matches(session, self.session_token):
            raise WebInputError(401, "session_required")
        if request.method == "POST":
            if headers.get(b"origin") != b"http://127.0.0.1:8765":
                raise WebInputError(403, "invalid_origin")
            if headers.get(b"sec-fetch-site") != b"same-origin":
                raise WebInputError(403, "invalid_fetch_metadata")
            if not _matches(headers.get(b"x-narrator-csrf", b"").decode("latin-1"), self.csrf_token):
                raise WebInputError(403, "invalid_csrf")
            if headers.get(b"content-type") != b"application/json":
                raise WebInputError(415, "unsupported_media_type")
        if request.body_too_large or len(request.body) > MAX_BODY_BYTES:
            raise WebInputError(413, "body_too_large")
        return headers


def _matches(candidate: str, expected: str) -> bool:
    return bool(_TOKEN.fullmatch(candidate)) and secrets.compare_digest(candidate, expected)


def checked_headers(request: WebRequest) -> dict[bytes, bytes]:
    headers: dict[bytes, bytes] = {}
    for name, value in request.headers:
        name = name.lower()
        if not _HEADER_NAME.fullmatch(name) or any(byte < 32 or byte == 127 for byte in value):
            raise WebInputError(400, "malformed_request")
        if name in _SINGLE_HEADERS and name in headers:
            raise WebInputError(400, "malformed_request")
        headers[name] = value
    if b"content-length" in headers and (
        not headers[b"content-length"].isdigit() or b"transfer-encoding" in headers
    ):
        raise WebInputError(400, "malformed_request")
    return headers


def _session_cookie(raw: bytes | None) -> str:
    if raw is None:
        return ""
    session = ""
    found = False
    for part in raw.split(b";"):
        name, separator, value = part.strip().partition(b"=")
        if not separator or not _HEADER_NAME.fullmatch(name) or any(byte < 33 or byte > 126 for byte in value):
            raise WebInputError(400, "malformed_request")
        if name == b"narrator_session":
            if found:
                raise WebInputError(400, "malformed_request")
            found = True
            session = value.decode("ascii")
    return session


def secure_response(response: WebResponse, *, head: bool = False, asset: bool = False) -> WebResponse:
    fixed = (*_SECURITY_HEADERS, (b"cache-control", b"no-cache" if asset else b"no-store"))
    names = {name for name, _ in fixed}
    headers = tuple((name, value) for name, value in response.headers if name.lower() not in names)
    if response.status not in (204, 304) and not any(name.lower() == b"content-length" for name, _ in headers):
        headers += ((b"content-length", str(len(response.body)).encode()),)
    return replace(response, body=b"" if head else response.body, headers=(*headers, *fixed))


class WebInputError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__()
        self.status = status
        self.code = code


def json_success(result: dict[str, object]) -> WebResponse:
    return WebResponse(200, json.dumps({"ok": True, "result": result}, separators=(",", ":"), allow_nan=False).encode("utf-8"),
                       ((b"content-type", b"application/json"),))


def json_error(status: int, code: str) -> WebResponse:
    return WebResponse(status, json.dumps({"ok": False, "error": {"code": code, "message": "The request could not be completed."}}, separators=(",", ":")).encode(),
                       ((b"content-type", b"application/json"),) + (((b"allow", b"GET, HEAD, POST"),) if status == 405 else ()))


def parse_json_object(request: WebRequest, keys: frozenset[str]) -> dict[str, object]:
    if request.body_too_large or len(request.body) > MAX_BODY_BYTES:
        raise WebInputError(413, "body_too_large")
    try:
        value = json.loads(request.body.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise WebInputError(400, "invalid_json") from None
    if not isinstance(value, dict) or value.keys() != keys:
        raise WebInputError(400, "invalid_json")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise ValueError("invalid JSON constant")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("invalid JSON number")
    return parsed
