"""NO_NETWORK proof: the autouse fixture in conftest.py blocks every outbound connection."""

from __future__ import annotations

import socket

import pytest
from contract_support import NetworkBlockedError


def test_create_connection_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)


def test_raw_socket_connect_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(NetworkBlockedError):
            sock.connect_ex(("127.0.0.1", 9))


def test_name_resolution_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("neurosphere.invalid", 443)
