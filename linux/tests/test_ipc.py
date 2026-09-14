"""Канал между демоном и рисовальщиком следа."""

from __future__ import annotations

import os
import socket
import stat
import time

import pytest

from glyphstroke.ipc import OverlayServer, socket_path


@pytest.fixture
def server(tmp_path):
    srv = OverlayServer(tmp_path / "overlay.sock")
    srv.start()
    yield srv
    srv.stop()


def connect(srv, expected: int = 1) -> socket.socket:
    """Подключиться и дождаться, пока сервер учтёт именно столько слушателей."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(srv.path))
    deadline = time.monotonic() + 2
    while srv.listeners < expected and time.monotonic() < deadline:
        time.sleep(0.02)
    assert srv.listeners == expected
    return client


def test_socket_lives_in_the_session_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert socket_path() == tmp_path / "glyphstroke" / "overlay.sock"


def test_socket_is_private_to_the_user(server):
    mode = stat.S_IMODE(os.stat(server.path).st_mode)
    assert mode == 0o600, "чужой пользователь не должен читать наши росчерки"


def test_line_reaches_the_listener(server):
    client = connect(server)
    assert server.broadcast("begin #4da3ff 4") == 1
    assert client.recv(64).decode().strip() == "begin #4da3ff 4"
    client.close()


def test_several_listeners_get_the_same_line(server):
    first, second = connect(server, 1), connect(server, 2)
    assert server.broadcast("end") == 2
    assert first.recv(16).decode().strip() == "end"
    assert second.recv(16).decode().strip() == "end"
    first.close()
    second.close()


def test_disconnected_listener_is_forgotten(server):
    client = connect(server)
    client.close()
    time.sleep(0.1)
    for _ in range(3):          # первая отправка может уйти в буфер ядра
        server.broadcast("end")
    assert server.listeners == 0


def test_broadcast_without_listeners_is_harmless(server):
    assert server.broadcast("end") == 0


def test_stop_removes_the_socket(tmp_path):
    srv = OverlayServer(tmp_path / "overlay.sock")
    srv.start()
    assert srv.path.exists()
    srv.stop()
    assert not srv.path.exists()


# --- клиент рассказывает, что умеет ---
def test_client_capabilities_are_remembered(server):
    client = connect(server)
    assert not server.has("keys")
    client.sendall(b"iam shell keys\n")
    deadline = time.monotonic() + 2
    while not server.has("keys") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.has("keys")
    client.close()


def test_capabilities_disappear_with_the_client(server):
    client = connect(server)
    client.sendall(b"iam shell keys\n")
    deadline = time.monotonic() + 2
    while not server.has("keys") and time.monotonic() < deadline:
        time.sleep(0.02)
    client.close()
    deadline = time.monotonic() + 2
    while server.has("keys") and time.monotonic() < deadline:
        server.broadcast("end")
        time.sleep(0.05)
    assert not server.has("keys"), "ушедшему клиенту клавиши слать некуда"


def test_watcher_without_capabilities_does_not_claim_keys(server):
    client = connect(server)          # «glyphstroke watch» ничего о себе не шлёт
    server.broadcast("end")
    assert not server.has("keys")
    client.close()
