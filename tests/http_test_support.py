"""Exercise HTTP handlers when the host denies loopback client connections.

Prefer an actual loopback socket. Only an OS permission denial selects the
in-process transport, which still uses HTTPConnection request serialization,
the server's unchanged RequestHandlerClass, and HTTPResponse parsing. It does
not claim to verify the operating system's network transport.
"""

from collections import Counter
import errno
import http.client
import io


_counts = Counter()


class _AcceptedRequest:
    def __init__(self, data):
        self.incoming = io.BytesIO(data)
        self.outgoing = bytearray()

    def makefile(self, mode, buffering=-1):
        if mode != "rb":
            raise ValueError("Only the handler's binary request stream is supported")
        return self.incoming

    def sendall(self, data):
        self.outgoing.extend(data)


class _InProcessSocket:
    def __init__(self, server):
        self.server = server
        self.request = bytearray()
        self.response = None

    def sendall(self, data):
        if self.response is not None:
            raise RuntimeError("Use a fresh test connection for each HTTP request")
        self.request.extend(data)

    def makefile(self, mode, buffering=None):
        if mode != "rb":
            raise ValueError("Only binary HTTP response reading is supported")
        if self.response is None:
            accepted = _AcceptedRequest(bytes(self.request))
            self.server.RequestHandlerClass(accepted, ("127.0.0.1", 0), self.server)
            self.response = bytes(accepted.outgoing)
        return io.BytesIO(self.response)

    def close(self):
        # HTTPResponse owns its independent response stream after creation.
        pass


def connection_for(server, *, timeout=5):
    """Return a normal HTTP client, with an explicit permission-only fallback."""
    if server.server_address[0] != "127.0.0.1":
        raise ValueError("HTTP test support accepts only the local test server")
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)
    try:
        connection.connect()
    except PermissionError as error:
        if error.errno not in (errno.EACCES, errno.EPERM) and getattr(error, "winerror", None) != 10013:
            raise
        connection.close()
        connection.sock = _InProcessSocket(server)
        connection.stratus_test_transport = "in_process_http"
    else:
        connection.stratus_test_transport = "loopback_socket"
    _counts[connection.stratus_test_transport] += 1
    return connection


def transport_counts():
    return dict(_counts)
