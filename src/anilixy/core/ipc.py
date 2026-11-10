import select
import socket
import sys
import threading
import time

WINDOWS = sys.platform == "win32"

POLL_SECONDS = 0.05

PIPE_CLOSED_ERRORS = (109, 232, 233)


def pipe_path(name: str) -> str:
    return rf"\\.\pipe\{name}"


class NamedPipe:
    def __init__(self, address: str):
        import _winapi

        self._winapi = _winapi
        self._lock = threading.Lock()
        self._timeout = None
        self._handle = _winapi.CreateFile(
            address,
            _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
            0,
            _winapi.NULL,
            _winapi.OPEN_EXISTING,
            0,
            _winapi.NULL,
        )

    def settimeout(self, timeout) -> None:
        self._timeout = timeout

    def _pending(self) -> int:
        if self._handle is None:
            raise OSError("pipe is closed")
        try:
            return self._winapi.PeekNamedPipe(self._handle, 0)[0]
        except OSError as error:
            if error.winerror in PIPE_CLOSED_ERRORS:
                return -1
            raise

    def _wait(self, timeout, ready) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not ready():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(POLL_SECONDS)
        return True

    def wait_readable(self, timeout) -> bool:
        def ready():
            with self._lock:
                return self._pending() != 0

        return self._wait(timeout, ready)

    def recv(self, size: int) -> bytes:
        received = []

        def ready():
            with self._lock:
                pending = self._pending()
                if pending > 0:
                    received.append(
                        self._winapi.ReadFile(self._handle, min(size, pending))[0]
                    )
                return pending != 0

        if not self._wait(self._timeout, ready):
            raise TimeoutError("timed out reading from pipe")
        return received[0] if received else b""

    def sendall(self, data: bytes) -> None:
        view = memoryview(data)
        with self._lock:
            if self._handle is None:
                raise OSError("pipe is closed")
            while view:
                written, _ = self._winapi.WriteFile(self._handle, bytes(view))
                view = view[written:]

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._winapi.CloseHandle(self._handle)
                self._handle = None


def connect(address: str, timeout=None):
    if WINDOWS:
        return NamedPipe(address)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(address)
        sock.settimeout(None)
    except BaseException:
        sock.close()
        raise
    return sock


def wait_readable(conn, timeout) -> bool:
    if WINDOWS:
        return conn.wait_readable(timeout)
    ready, _, _ = select.select([conn], [], [], timeout)
    return bool(ready)


def read_lines(conn):
    buffer = b""
    while chunk := conn.recv(65536):
        *lines, buffer = (buffer + chunk).split(b"\n")
        for line in lines:
            yield line.decode("utf-8", "replace")
