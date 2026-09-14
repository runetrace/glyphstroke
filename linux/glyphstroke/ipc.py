"""Канал к рисовальщику следа.

Демон объявляет о начале и конце росчерка, а рисует его тот, кто может:
в X11 — собственное окно поверх экрана, в GNOME на Wayland — расширение
оболочки. Обе стороны подключаются сюда как клиенты, поэтому демону всё
равно, кто именно слушает и слушает ли кто-нибудь вообще.

Протокол построчный. От демона::

    begin #4da3ff 4 0.9 начался росчерк: цвет, толщина, прозрачность
    end                 росчерк закончен, можно гасить след
    stroke  …           что распознано (видно в «glyphstroke watch»)
    points  …           сам росчерк, 64 точки
    action  …           какое действие выполнено
    dokeys  ctrl+c      просьба нажать сочетание вместо демона
    dopick              какое окно под курсором (мишень редактора)
    picked  класс  имя  ответ на мишень, всем слушателям
    overlay-key-hold    Super зажат ради росчерка по тачпаду: обзор не открывать
    overlay-key-free    Super отпущен

В обратную сторону клиент представляется и перечисляет, что умеет, а также
управляет демоном::

    iam shell keys      расширение оболочки, умеет нажимать клавиши
    pause / resume / toggle   приостановить или вернуть перехват
    state?              спросить текущее состояние
    pick                редактор спрашивает, какое окно под курсором
    picked  класс  имя  ответ оболочки, закодированный как в адресной строке

Это нужно из-за раскладки: демон шлёт нажатия кодами клавиш, и композитор
читает их через текущую раскладку — при русской «KEY_C» превращается в «с»,
и приложение не узнаёт в этом Ctrl+C. Расширение оболочки шлёт не код, а
символ, поэтому раскладка перестаёт что-либо значить.
"""

from __future__ import annotations

import logging
import os
import select
import socket
import threading
from pathlib import Path

from .i18n import _

log = logging.getLogger("glyphstroke.ipc")

ACCEPT_TIMEOUT_S = 0.5


def socket_path() -> Path:
    """Сокет в каталоге сеанса пользователя — он же чистится при выходе."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/glyphstroke-{os.getuid()}"
    return Path(base) / "glyphstroke" / "overlay.sock"


class OverlayServer:
    def __init__(self, path: str | Path | None = None, greeting: str | None = None,
                 on_command=None):
        self.path = Path(path) if path else socket_path()
        #: строка, которую получает каждый подключившийся, — по ней видно,
        #: какая версия демона на самом деле работает и что с перехватом.
        #: Может быть функцией: состояние меняется, а приветствие должно быть
        #: свежим на момент подключения, а не на момент запуска
        self.greeting = greeting
        #: обработчик команд от клиентов: получает список слов строки
        self.on_command = on_command
        self._server: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._capabilities: dict[socket.socket, set[str]] = {}
        self._buffers: dict[socket.socket, bytes] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.path))
        os.chmod(self.path, 0o600)  # чужому пользователю тут делать нечего
        server.listen(4)
        server.settimeout(ACCEPT_TIMEOUT_S)
        self._server = server
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True,
                                        name="glyphstroke-ipc")
        self._thread.start()
        log.info(_("канал следа: %s"), self.path)

    def _accept_loop(self) -> None:
        while self._running:
            with self._lock:
                watched = [self._server, *self._clients]
            try:
                readable, _w, _x = select.select(watched, [], [], ACCEPT_TIMEOUT_S)
            except (OSError, ValueError):
                continue
            for sock in readable:
                if sock is self._server:
                    self._accept()
                else:
                    self._receive(sock)

    def _accept(self) -> None:
        try:
            conn, _addr = self._server.accept()
        except OSError:
            return
        conn.setblocking(False)
        greeting = self.greeting() if callable(self.greeting) else self.greeting
        if greeting:
            try:
                conn.sendall((greeting + "\n").encode("utf-8"))
            except OSError:
                conn.close()
                return
        with self._lock:
            self._clients.append(conn)
            self._capabilities[conn] = set()
            self._buffers[conn] = b""
            total = len(self._clients)
        log.info(_("к каналу подключился клиент (всего %d)"), total)

    def _receive(self, conn: socket.socket) -> None:
        """Клиент рассказывает о себе строкой ``iam <имя> <что умеет>``."""
        try:
            chunk = conn.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            with self._lock:
                self._drop(conn)
            return
        commands: list[list[str]] = []
        with self._lock:
            buffer = self._buffers.get(conn, b"") + chunk
            while b"\n" in buffer:
                raw, _sep, buffer = buffer.partition(b"\n")
                parts = raw.decode("utf-8", "replace").split()
                if not parts:
                    continue
                if parts[0] == "iam":
                    self._capabilities[conn] = set(parts[1:])
                    log.info(_("клиент умеет: %s"), ", ".join(parts[1:]) or _("ничего"))
                elif self.on_command is not None:
                    commands.append(parts)
            self._buffers[conn] = buffer[-4096:]
        # обработчик вызываем без замка: он может слать в тот же канал
        for parts in commands:
            try:
                self.on_command(parts)
            except Exception:
                log.exception(_("команда %s не выполнена"), parts)

    def _drop(self, conn: socket.socket) -> None:
        """Вызывается под замком."""
        if conn in self._clients:
            self._clients.remove(conn)
        self._capabilities.pop(conn, None)
        self._buffers.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass

    def has(self, capability: str) -> bool:
        """Есть ли подключённый клиент, умеющий это."""
        with self._lock:
            return any(capability in caps for caps in self._capabilities.values())

    def broadcast(self, line: str) -> int:
        """Разослать строку всем подключённым. Возвращает число получателей."""
        data = (line + "\n").encode("utf-8")
        delivered = 0
        with self._lock:
            for conn in list(self._clients):
                try:
                    conn.sendall(data)
                    delivered += 1
                except OSError:
                    # клиент отвалился или не читает — забываем о нём
                    self._drop(conn)
        return delivered

    @property
    def listeners(self) -> int:
        with self._lock:
            return len(self._clients)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            for conn in list(self._clients):
                self._drop(conn)
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass
