"""The restricted-host transport preserves HTTP bytes and surfaces real errors."""

from collections import Counter
import errno
from http.server import BaseHTTPRequestHandler
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from http_test_support import connection_for, transport_counts


class EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = b"\x00\xff\r\nHTTP/1.1\x00"
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        raw = json.dumps({"path": self.path, "body": data.decode("utf-8"),
                          "origin": self.headers.get("Origin"),
                          "host": self.headers["Host"]}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class HttpTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = SimpleNamespace(server_address=("127.0.0.1", 8774), server_port=8774,
                                      RequestHandlerClass=EchoHandler)
        # Synthetic helper tests do not contribute to observed app-test transports.
        counts = patch("http_test_support._counts", Counter())
        counts.start()
        self.addCleanup(counts.stop)

    def denied_connection(self):
        with patch("http.client.HTTPConnection.connect",
                   side_effect=PermissionError(errno.EACCES, "Injected loopback denial")):
            connection = connection_for(self.server)
        self.addCleanup(connection.close)
        self.assertEqual(connection.stratus_test_transport, "in_process_http")
        return connection

    def test_permission_fallback_preserves_serialized_post_body_and_headers(self):
        connection = self.denied_connection()
        payload = json.dumps({"value": "temperature \u00b0C"}, ensure_ascii=False).encode()
        connection.request("POST", "/echo?view=overview", payload,
                           {"Content-Type": "application/json", "Origin": "https://foreign.example"})
        response = connection.getresponse()
        self.assertEqual(response.status, 201)
        self.assertEqual(json.loads(response.read()), {
            "path": "/echo?view=overview", "body": payload.decode(),
            "origin": "https://foreign.example", "host": "127.0.0.1:8774"})
        self.assertEqual(transport_counts(), {"in_process_http": 1})

    def test_binary_response_bytes_survive_the_actual_http_parser(self):
        connection = self.denied_connection()
        connection.request("GET", "/binary")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b"\x00\xff\r\nHTTP/1.1\x00")

    def test_connection_refusal_is_not_converted_to_a_successful_request(self):
        with patch("http.client.HTTPConnection.connect", side_effect=ConnectionRefusedError("Injected refusal")):
            with self.assertRaises(ConnectionRefusedError):
                connection_for(self.server)
        self.assertEqual(transport_counts(), {})

    def test_successful_connection_retains_the_native_transport(self):
        with patch("http.client.HTTPConnection.connect") as connect:
            connection = connection_for(self.server, timeout=3)
        self.addCleanup(connection.close)
        connect.assert_called_once_with()
        self.assertEqual(connection.stratus_test_transport, "loopback_socket")
        self.assertEqual(transport_counts(), {"loopback_socket": 1})

    def test_handler_exception_remains_a_test_failure(self):
        class BrokenHandler:
            def __init__(self, *args):
                raise RuntimeError("Injected handler defect")
        self.server.RequestHandlerClass = BrokenHandler
        connection = self.denied_connection()
        connection.request("GET", "/")
        with self.assertRaisesRegex(RuntimeError, "handler defect"):
            connection.getresponse()

    def test_external_server_cannot_use_the_in_process_transport(self):
        self.server.server_address = ("example.com", 443)
        with patch("http.client.HTTPConnection.connect") as connect:
            with self.assertRaises(ValueError):
                connection_for(self.server)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
