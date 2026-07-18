"""Malware scanning (docs/08 §8.11): the EICAR dev scanner, the ClamAV INSTREAM protocol,
and the factory's real-vs-fake selection."""

from __future__ import annotations

import socket
import struct
import threading

from cani_shared.providers.scanner import (
    EICAR_SIGNATURE,
    ClamAVScanner,
    EicarSignatureScanner,
    ScanResult,
)


def test_eicar_scanner_flags_eicar():
    result = EicarSignatureScanner().scan(b"harmless preamble " + EICAR_SIGNATURE + b" trailer")
    assert result.is_clean is False
    assert result.signature == "Eicar-Test-Signature"


def test_eicar_scanner_passes_clean_file():
    result = EicarSignatureScanner().scan(b"%PDF-1.7 a perfectly ordinary document")
    assert result == ScanResult(is_clean=True)


def _fake_clamd(reply: bytes) -> tuple[socket.socket, int]:
    """A one-shot loopback server that speaks just enough INSTREAM to answer one scan."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        conn, _ = server.accept()
        with conn:
            # Drain the INSTREAM command + chunks until the zero-length terminator.
            conn.recv(len(b"zINSTREAM\0"))
            while True:
                header = conn.recv(4)
                if len(header) < 4:
                    break
                (length,) = struct.unpack("!I", header)
                if length == 0:
                    break
                remaining = length
                while remaining:
                    remaining -= len(conn.recv(remaining))
            conn.sendall(reply)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server, port


def test_clamav_scanner_parses_clean_response():
    _, port = _fake_clamd(b"stream: OK\0")
    result = ClamAVScanner(host="127.0.0.1", port=port).scan(b"a" * (128 * 1024 + 7))
    assert result.is_clean is True


def test_clamav_scanner_parses_found_response():
    _, port = _fake_clamd(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    result = ClamAVScanner(host="127.0.0.1", port=port).scan(b"whatever")
    assert result.is_clean is False
    assert result.signature == "Win.Test.EICAR_HDB-1"


def test_factory_selects_real_vs_fake(monkeypatch):
    from cani_shared.providers.factory import build_malware_scanner

    class _S:
        clamav_host = ""
        clamav_port = 3310

        @property
        def clamav_configured(self):
            return bool(self.clamav_host)

    fake = _S()
    assert isinstance(build_malware_scanner(fake), EicarSignatureScanner)

    real = _S()
    real.clamav_host = "clamav"
    assert isinstance(build_malware_scanner(real), ClamAVScanner)
