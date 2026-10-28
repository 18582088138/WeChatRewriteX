"""Outbound URL policy for untrusted article/media input, including redirects.

Proxy-side DNS resolution still requires an egress firewall for hostile remote input.
Configured model endpoints are administrator-controlled and use a separate trust boundary.
"""
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    pass


def validate_url(url: str, resolve: bool = True) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURL("URL 格式无效") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeURL("仅支持不含凭据的 HTTP/HTTPS URL")
    host = parsed.hostname.rstrip(".").lower()
    if host in ("localhost", "metadata.google.internal") or host.endswith((".localhost", ".local")):
        raise UnsafeURL("不允许抓取本机或内网地址")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not resolve:
            return url
        try:
            addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(
                         host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise UnsafeURL("目标域名解析失败") from exc
    if not addresses or any(not ip.is_global or ip.is_multicast or getattr(ip, "ipv4_mapped", None) and not ip.ipv4_mapped.is_global for ip in addresses):
        raise UnsafeURL("不允许抓取私网、回环、链路本地或保留地址")
    return url


def validate_request(request):
    validate_url(str(request.url))
