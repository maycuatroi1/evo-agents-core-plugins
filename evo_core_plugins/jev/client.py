"""The client of the System One API of TypeSafe (``POST <base_url>/v1/systemone``), the only code of the plugin that
leaves the hub's process.

- The base URL is https and holds no credentials. Every address its host resolves to must be public, and the call goes
  to the address checked, with the host in the Host header and as the TLS server name (so the certificate is the
  host's): a name that resolves again to a private address after the check cannot move the call (DNS rebinding). A
  redirect is not followed.
- The key travels only in the Authorization header. A failure is told in words of the plugin's own: the status code,
  never the body or the headers the vendor sent, which could echo the request.
- No retry: a call that failed is paid for by whoever asks again.
- The whole call takes less than the 30 seconds a tool has.

``RESOLVER`` and ``TRANSPORT`` are the two places a test puts a fake in.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

PATH = "/v1/systemone"
TIMEOUT = httpx.Timeout(25.0, connect=5.0)
MAX_REQUEST_BYTES = 120_000  # about 30k tokens: well within the vendor's 64k of context
MAX_REPLY_BYTES = 1_000_000
CGNAT = ipaddress.ip_network("100.64.0.0/10")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class JevError(Exception):
    """A call that failed, in words that hold nothing the vendor sent. ``sent`` is whether a request left the hub."""

    def __init__(self, message: str, *, sent: bool = False) -> None:
        super().__init__(message)
        self.sent = sent


async def _resolve(host: str, port: int) -> list[str]:
    found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({item[4][0] for item in found})


RESOLVER = _resolve
TRANSPORT: httpx.AsyncBaseTransport | None = None


def public(address: str) -> bool:
    """Whether ``address`` is one a call may go to: global, not multicast, not carrier-grade NAT, and an IPv4 address
    mapped into IPv6 judged as the IPv4 address."""
    try:
        ip = ipaddress.ip_address(address.partition("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and ip not in CGNAT


@dataclass(frozen=True)
class Target:
    """Where a call goes: the checked address, the host it was resolved from, and the path."""

    host: str
    port: int
    address: str
    path: str

    @property
    def url(self) -> str:
        address = f"[{self.address}]" if ":" in self.address else self.address
        return f"https://{address}:{self.port}{self.path}"


def parse_base_url(base_url: str) -> tuple[str, int, str]:
    """(host, port, path prefix) of an https base URL with no credentials, query or fragment; JevError otherwise."""
    try:
        parts = urlsplit(base_url.strip())
        port = parts.port or 443
    except ValueError:
        raise JevError("base_url is not a URL") from None
    if parts.scheme != "https" or not parts.hostname:
        raise JevError("base_url must be an https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise JevError("base_url holds no credentials, query or fragment")
    return parts.hostname, port, parts.path.rstrip("/")


async def target(base_url: str) -> Target:
    """The checked target of the base URL: JevError when its host resolves to nothing, or to any address that is not
    public (every address counts, not only the one the call uses)."""
    host, port, prefix = parse_base_url(base_url)
    try:
        ip = ipaddress.ip_address(host)
        addresses = [str(ip)]
    except ValueError:
        try:
            addresses = list(await RESOLVER(host, port))
        except OSError:
            raise JevError("the host of base_url does not resolve") from None
    if not addresses:
        raise JevError("the host of base_url does not resolve")
    if not all(public(address) for address in addresses):
        raise JevError("base_url resolves to an address that is not public")
    return Target(host, port, addresses[0], prefix + PATH)


@dataclass(frozen=True)
class Reply:
    """What the vendor answered: the model that answered, its answers by question, and the input tokens it counted."""

    model: str
    answers: dict
    input_tokens: int
    output_tokens: int


def _count(usage: object, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


async def _read(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_REPLY_BYTES:
            raise JevError("Jev's answer is too large", sent=True)
    return bytes(body)


async def ask(base_url: str, api_key: str, body: dict) -> Reply:
    """Send ``body`` ({model, state, questions}) and parse the answer. JevError for a refused base URL, a timeout, a
    connection that failed, a status past 299 and a body that is not the shape of the API; the model is compared by
    the caller, which still has the tokens a wrong answer cost."""
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise JevError(f"the request is {len(payload)} bytes; a call takes at most {MAX_REQUEST_BYTES}")
    where = await target(base_url)
    headers = {
        "Host": where.host if where.port == 443 else f"{where.host}:{where.port}",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=TRANSPORT) as client:
            request = client.build_request(
                "POST", where.url, content=payload, headers=headers, extensions={"sni_hostname": where.host}
            )
            response = await client.send(request, stream=True)
            try:
                status = response.status_code
                raw = await _read(response) if status < 300 else b""
            finally:
                await response.aclose()
    except httpx.TimeoutException:
        raise JevError("Jev did not answer in time", sent=True) from None
    except httpx.HTTPError:
        raise JevError("Jev could not be reached", sent=True) from None
    if status >= 300:
        raise JevError(f"Jev answered HTTP {status}", sent=True)
    try:
        data = json.loads(raw)
    except ValueError:
        raise JevError("Jev's answer is not JSON", sent=True) from None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("answers"), dict)
        or not isinstance(data.get("model"), str)
    ):
        raise JevError("Jev's answer is not the shape the API documents", sent=True)
    usage = data.get("usage")
    return Reply(data["model"], data["answers"], _count(usage, "input_tokens"), _count(usage, "output_tokens"))


def shown_model(model: str) -> str:
    """The model an answer named, for a refusal's words: itself when it is a plain id, else a placeholder."""
    return model if SAFE_NAME.match(model) else "an unnamed model"
