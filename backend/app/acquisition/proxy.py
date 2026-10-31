import asyncio
import logging
import socket
from urllib.parse import urlsplit

from app.acquisition.ssrf import UrlRejected, parse_url, resolve_public

log = logging.getLogger(__name__)

MAX_HEADER_BYTES = 64 * 1024
CHUNK_BYTES = 64 * 1024
CONNECT_TIMEOUT_S = 15
_HOP_HEADERS = (b"connection:", b"proxy-connection:", b"proxy-authorization:", b"keep-alive:")


async def allowed_addresses(host: str, port: int) -> list[str]:
    """The checks a fetched URL gets, applied to each connection the browser makes."""
    parse_url(f"http://{host}:{port}/")
    return await resolve_public(host, port)


class GuardedProxy:
    """A local forward proxy that the browser tier sends all its traffic through.

    Playwright's route handler only sees the first URL of a redirect chain, so a public page
    could redirect the browser to an internal address. Checking here covers every hop, and
    connecting to the checked address means DNS can't change after the check.
    """

    def __init__(self, limit_bytes: int) -> None:
        self._remaining = limit_bytes
        self._tasks: set[asyncio.Task] = set()
        self._server: asyncio.Server | None = None
        self.url = ""
        self.blocked = False
        self.over_limit = False

    async def __aenter__(self) -> "GuardedProxy":
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *_: object) -> None:
        self._server.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            await self._handle(reader, writer)
        except (OSError, ValueError, IndexError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        if len(head) > MAX_HEADER_BYTES:
            return
        request_line, *headers = head[:-4].split(b"\r\n")
        method, target, version = request_line.split(b" ", 2)
        tunnel = method == b"CONNECT"
        url = urlsplit(f"//{target.decode()}" if tunnel else target.decode())
        host, port = url.hostname, url.port or (443 if tunnel else 80)

        upstream = await self._connect(host, port)
        if upstream is None:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        up_reader, up_writer = upstream
        try:
            if tunnel:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                up_writer.write(_origin_request(method, url, version, headers))
                await up_writer.drain()
            await asyncio.gather(
                self._pipe(reader, up_writer), self._pipe(up_reader, writer, counted=True)
            )
        finally:
            up_writer.close()

    async def _connect(self, host: str | None, port: int):
        try:
            addresses = await allowed_addresses(host or "", port)
        except UrlRejected:
            self.blocked = True
            log.info("Browser tier blocked a connection")
            return None
        except (socket.gaierror, UnicodeError):
            return None
        for address in addresses[:2]:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(address, port, limit=CHUNK_BYTES), CONNECT_TIMEOUT_S
                )
            except (OSError, TimeoutError):
                continue
        return None

    async def _pipe(
        self, source: asyncio.StreamReader, sink: asyncio.StreamWriter, counted: bool = False
    ) -> None:
        try:
            while chunk := await source.read(CHUNK_BYTES):
                if counted:
                    self._remaining -= len(chunk)
                    if self._remaining < 0:
                        self.over_limit = True
                        return
                sink.write(chunk)
                await sink.drain()
        finally:
            # Ending one direction ends the exchange, so a stalled peer can't hold the other open.
            sink.close()


def _origin_request(method: bytes, url, version: bytes, headers: list[bytes]) -> bytes:
    path = (url.path or "/") + (f"?{url.query}" if url.query else "")
    kept = [h for h in headers if not h.lower().startswith(_HOP_HEADERS)]
    # One request per connection. The browser can't reuse this tunnel to reach another host.
    lines = [b" ".join((method, path.encode(), version)), *kept, b"Connection: close"]
    return b"\r\n".join(lines) + b"\r\n\r\n"
