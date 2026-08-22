"""Bounded HTTPS image retrieval with destination pinning.

The connection uses the already validated public address while TLS verifies the
original host name. Redirects repeat the complete validation process, preventing
DNS rebinding between validation and connection.
"""

import http.client
import io
import ipaddress
import socket
import ssl
import warnings
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 20
ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp"}


class ImageFetchError(ValueError):
    pass


@dataclass(frozen=True)
class FetchedImage:
    data: bytes
    media_type: str
    final_url: str


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, *, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._validated_address = address

    def connect(self):
        raw = socket.create_connection(
            (self._validated_address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _validated_address(hostname: str) -> str:
    try:
        answers = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ImageFetchError("The image hostname could not be resolved.") from error
    # sockaddr is (host, port) for AF_INET and (host, port, flowinfo, scope_id)
    # for AF_INET6, so the element type is `str | int` as far as the checker is
    # concerned even though index 0 is always the address string. Narrow it
    # here: `ipaddress.ip_address` accepts an int and reads it as a packed
    # address, which is not a distinction an SSRF guard should leave open.
    addresses = sorted({str(answer[4][0]) for answer in answers})
    if not addresses:
        raise ImageFetchError("The image hostname has no address.")
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global:
            raise ImageFetchError("The image hostname resolves to a non-public address.")
    return addresses[0]


def _request(url: str, allowed_hosts: set[str]) -> tuple[bytes, str, str | None]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ImageFetchError("Image URLs must be credential-free HTTPS URLs.")
    if parsed.port not in (None, 443):
        raise ImageFetchError("Image URLs must use the standard HTTPS port.")
    if host not in allowed_hosts:
        raise ImageFetchError("The image hostname is not allowed for this source.")
    address = _validated_address(host)
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    connection = _PinnedHTTPSConnection(host, address, timeout=TIMEOUT_SECONDS)
    try:
        connection.request(
            "GET",
            target,
            headers={"Host": host, "User-Agent": "mb-shop-import/1"},
        )
        response = connection.getresponse()
        location = response.getheader("Location")
        if response.status in {301, 302, 303, 307, 308}:
            response.read(1)
            if not location:
                raise ImageFetchError("The image server returned an empty redirect.")
            return b"", "", urljoin(url, location)
        if response.status < 200 or response.status >= 300:
            response.read(1)
            raise ImageFetchError(f"The image server returned HTTP {response.status}.")
        media_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
        if media_type not in ALLOWED_MEDIA:
            raise ImageFetchError("The response is not a supported raster image.")
        length = response.getheader("Content-Length")
        if length and int(length) > MAX_IMAGE_BYTES:
            raise ImageFetchError("The image exceeds 15 MB.")
        body = response.read(MAX_IMAGE_BYTES + 1)
        if len(body) > MAX_IMAGE_BYTES:
            raise ImageFetchError("The image exceeds 15 MB.")
        return body, media_type, None
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as error:
        if isinstance(error, ImageFetchError):
            raise
        raise ImageFetchError("The image could not be downloaded safely.") from error
    finally:
        connection.close()


def _sanitize(data: bytes, media_type: str) -> tuple[bytes, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if getattr(probe, "n_frames", 1) != 1:
                    raise ImageFetchError("Animated or multi-frame images are not accepted.")
                width, height = probe.size
                probe.verify()
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ImageFetchError("The image exceeds the safe decode size.")
            with Image.open(io.BytesIO(data)) as opened:
                image = ImageOps.exif_transpose(opened)
                output = io.BytesIO()
                if media_type == "image/png" and "A" in image.getbands():
                    image.convert("RGBA").save(output, "PNG", optimize=True)
                    normalized_type = "image/png"
                else:
                    image.convert("RGB").save(output, "JPEG", quality=90, optimize=True)
                    normalized_type = "image/jpeg"
                normalized = output.getvalue()
                if len(normalized) > MAX_IMAGE_BYTES:
                    raise ImageFetchError("The normalized image exceeds 15 MB.")
                return normalized, normalized_type
    except ImageFetchError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as error:
        raise ImageFetchError("The response is not a safe decodable image.") from error


def fetch_image(url: str, allowed_hosts: set[str]) -> FetchedImage:
    current = url
    for _redirect in range(MAX_REDIRECTS + 1):
        body, media_type, redirect = _request(current, allowed_hosts)
        if redirect:
            current = redirect
            continue
        normalized, normalized_type = _sanitize(body, media_type)
        return FetchedImage(normalized, normalized_type, current)
    raise ImageFetchError("The image exceeded the redirect limit.")
