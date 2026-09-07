"""The sole framework translation and fixed loopback server boundary."""

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
import uvicorn

from . import MAX_BODY_BYTES, WebApplication, WebRequest, WebResponse


def build_asgi(application: WebApplication):
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
        await response(scope, receive, send)

    return asgi


def serve_loopback(application: WebApplication) -> None:
    uvicorn.run(build_asgi(application), host="127.0.0.1", port=8765, workers=1,
                proxy_headers=False, reload=False, access_log=False)
