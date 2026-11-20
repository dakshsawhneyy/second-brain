import socket

from secondbrain import netfix


def test_ipv4_addresses_are_kept_and_ipv6_dropped(monkeypatch):
    v6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
    monkeypatch.setattr(netfix, "_original", lambda *a: [v6, v4])
    assert netfix._ipv4_first("example.com", 443) == [v4]


def test_ipv6_only_hosts_still_resolve(monkeypatch):
    v6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
    monkeypatch.setattr(netfix, "_original", lambda *a: [v6])
    assert netfix._ipv4_first("v6only.example", 443) == [v6]


def test_prefer_ipv4_is_idempotent(monkeypatch):
    monkeypatch.setattr(netfix, "_installed", False)
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)  # restored after the test
    netfix.prefer_ipv4()
    first = socket.getaddrinfo
    netfix.prefer_ipv4()
    assert socket.getaddrinfo is first is netfix._ipv4_first
