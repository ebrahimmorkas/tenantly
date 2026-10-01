"""Server-side request forgery (SSRF) protection for webhook URLs.

Tenants choose where we send HTTP requests, so we refuse URLs that point at our
own infrastructure: loopback, private, link-local (cloud metadata at
169.254.169.254) and other reserved ranges. Hostnames are resolved and every
returned address is checked. The check runs both when an endpoint is saved and
right before each delivery, because DNS answers can change in between.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from django.conf import settings


class UnsafeURL(ValueError):
    pass


def _resolve(host: str) -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None)]
    except socket.gaierror as exc:
        raise UnsafeURL(f"Cannot resolve host '{host}'.") from exc


def check_url(url: str) -> None:
    parts = urlsplit(url)
    allowed = {"https"} | ({"http"} if settings.TENANTLY_WEBHOOK_ALLOW_HTTP else set())
    if parts.scheme not in allowed:
        raise UnsafeURL(f"URL scheme must be one of: {', '.join(sorted(allowed))}.")
    if not parts.hostname:
        raise UnsafeURL("URL must include a host.")
    if settings.TENANTLY_WEBHOOK_ALLOW_PRIVATE_NETWORKS:
        return

    for address in _resolve(parts.hostname):
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL("URL resolves to a private or reserved network address.")
