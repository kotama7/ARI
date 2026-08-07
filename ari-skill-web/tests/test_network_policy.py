"""SSRF, DNS pinning, redirect, size, and media policy tests."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import network_policy
from network_policy import NetworkPolicyError, fetch_pinned, validate_url


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.2",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_non_public_destinations_are_rejected(address):
    with pytest.raises(NetworkPolicyError, match="non-public"):
        validate_url("https://target.example/", lambda _host, _port: (address,))


def test_mixed_public_and_private_dns_answer_is_rejected():
    with pytest.raises(NetworkPolicyError, match="non-public"):
        validate_url(
            "https://target.example/",
            lambda _host, _port: ("93.184.216.34", "127.0.0.1"),
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.org/",
        "https://example.org:444/",
    ],
)
def test_scheme_userinfo_and_port_policy(url):
    with pytest.raises(NetworkPolicyError):
        validate_url(url, lambda _host, _port: ("93.184.216.34",))


def test_dns_result_is_validated_once_then_pinned(monkeypatch):
    resolver_calls = 0
    observed_ips = []

    def resolver(_host, _port):
        nonlocal resolver_calls
        resolver_calls += 1
        return ("93.184.216.34",) if resolver_calls == 1 else ("127.0.0.1",)

    def request_once(_parsed, pinned_ip, **_kwargs):
        observed_ips.append(pinned_ip)
        return 200, {"content-type": "text/plain"}, b"ok"

    monkeypatch.setattr(network_policy, "_request_once", request_once)
    result = fetch_pinned("https://target.example/data", resolver=resolver)

    assert resolver_calls == 1
    assert observed_ips == ["93.184.216.34"]
    assert result.pinned_ip == "93.184.216.34"


def test_redirect_target_is_revalidated(monkeypatch):
    calls = 0

    def request_once(_parsed, _pinned_ip, **_kwargs):
        nonlocal calls
        calls += 1
        return 302, {"location": "http://127.0.0.1/metadata"}, b""

    monkeypatch.setattr(network_policy, "_request_once", request_once)
    with pytest.raises(NetworkPolicyError, match="non-public"):
        fetch_pinned(
            "http://public.example/start",
            resolver=lambda _host, _port: ("93.184.216.34",),
        )
    assert calls == 1


def test_https_downgrade_redirect_is_rejected(monkeypatch):
    monkeypatch.setattr(
        network_policy,
        "_request_once",
        lambda *_args, **_kwargs: (
            302,
            {"location": "http://public.example/plain"},
            b"",
        ),
    )
    with pytest.raises(NetworkPolicyError, match="downgrade"):
        fetch_pinned(
            "https://public.example/start",
            resolver=lambda _host, _port: ("93.184.216.34",),
        )


def test_content_length_over_limit_is_rejected_before_read(monkeypatch):
    class Response:
        status = 200

        @staticmethod
        def getheaders():
            return [("Content-Type", "text/plain"), ("Content-Length", "11")]

        @staticmethod
        def read(_amount):
            raise AssertionError("oversized body must not be read")

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        @staticmethod
        def getresponse():
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(network_policy.http.client, "HTTPConnection", Connection)
    with pytest.raises(NetworkPolicyError, match="byte limit"):
        network_policy._request_once(
            urlsplit("http://public.example/data"),
            "93.184.216.34",
            timeout=1,
            max_bytes=10,
        )


def test_disallowed_or_missing_content_type_is_rejected(monkeypatch):
    monkeypatch.setattr(
        network_policy,
        "_request_once",
        lambda *_args, **_kwargs: (
            200,
            {"content-type": "application/octet-stream"},
            b"binary",
        ),
    )
    with pytest.raises(NetworkPolicyError, match="content type"):
        fetch_pinned(
            "https://public.example/data",
            resolver=lambda _host, _port: ("93.184.216.34",),
        )
