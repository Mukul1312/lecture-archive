"""The sole framework translation and fixed loopback server boundary."""

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
import h11
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

from . import MAX_BODY_BYTES, WebApplication, WebRequest, WebResponse


def build_asgi(application: WebApplication):
    fallback = _capture_error_response(application, 500)

    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                # Uvicorn marks a response started before serializing headers. Once
                # handed downstream, a failed send cannot safely be retried.
                started = True
            await send(message)

        try:
            body = bytearray()
            overflow = False
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    overflow = True
                    body.clear()
                    break
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            request = WebRequest(scope["method"], scope["path"], tuple(scope["headers"]), bytes(body), overflow)
            result = await run_in_threadpool(application, request)
            response = Response(result.body, status_code=result.status)
            supplied_names = {key.lower() for key, _ in result.headers}
            response.raw_headers = [(key, value) for key, value in response.raw_headers if key not in supplied_names]
            response.raw_headers.extend(result.headers)
            if request.method == "HEAD":
                response.body = b""
            await response(scope, receive, tracked_send)
        except Exception:
            if not started:
                # Bypass the failing framework/worker conversion path entirely.
                try:
                    await tracked_send({"type": "http.response.start", "status": fallback.status,
                                        "headers": list(fallback.headers)})
                    await tracked_send({"type": "http.response.body",
                                        "body": b"" if scope.get("method") == "HEAD" else fallback.body})
                except Exception:
                    pass  # A broken connection cannot receive another response.

    return asgi


def serve_loopback(application: WebApplication) -> None:
    protocol = _http_protocol(_capture_error_response(application, 400))
    uvicorn.run(build_asgi(application), host="127.0.0.1", port=8765, workers=1,
                proxy_headers=False, reload=False, access_log=False, http=protocol)


def _capture_error_response(application: WebApplication, status: int) -> WebResponse:
    """Validate immutable context-owned fallbacks before accepting requests."""
    response = application.error_response(status)
    if (type(response) is not WebResponse or response.status != status
            or type(response.body) is not bytes or type(response.headers) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2
                   or any(type(value) is not bytes for value in pair) for pair in response.headers)):
        raise ValueError("invalid web error response")
    try:
        h11.Response(status_code=status, headers=response.headers)
        if dict(response.headers).get(b"content-length") != str(len(response.body)).encode():
            raise ValueError
    except (ValueError, h11.LocalProtocolError):
        raise ValueError("invalid web error response") from None
    return response


def _http_protocol(fallback: WebResponse) -> type[H11Protocol]:
    """Pinned Uvicorn 0.52.4/h11 parser failures occur before ASGI dispatch."""
    class SecuredH11Protocol(H11Protocol):
        def send_400_response(self, msg: str) -> None:
            headers = [(name, value) for name, value in fallback.headers if name.lower() != b"connection"]
            headers.append((b"connection", b"close"))
            try:
                self.transport.write(self.conn.send(h11.Response(status_code=400, headers=headers, reason=b"Bad Request")))
                self.transport.write(self.conn.send(h11.Data(data=fallback.body)))
                self.transport.write(self.conn.send(h11.EndOfMessage()))
            finally:
                self.transport.close()

    return SecuredH11Protocol
