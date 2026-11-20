"""Prefer IPv4 for every outgoing connection of this process.

On his network Telegram's IPv6 route fails about half the time (measured 7 of 15 with curl) while IPv4 works every time,
yet DNS lists the IPv6 address first. The bot opens new connections constantly, so those failures showed up as
ConnectError / TimedOut and lost replies. Keeping only IPv4 addresses (falling back to the full list if a host has none)
removes the problem without touching any other program.
"""

from __future__ import annotations

import socket

_installed = False
_original = socket.getaddrinfo


def _ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
    results = _original(host, port, family, type, proto, flags)
    v4 = [r for r in results if r[0] == socket.AF_INET]
    return v4 or results


def prefer_ipv4() -> None:
    """Idempotent. Call once at the start of the bot process."""
    global _installed
    if not _installed:
        socket.getaddrinfo = _ipv4_first
        _installed = True
