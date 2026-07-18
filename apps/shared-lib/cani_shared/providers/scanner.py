"""Malware scanning for uploads, before extraction (docs/08 §8.11, docs/14 §14.8).

Same real-vs-fake tiering as the other providers: production points at a ClamAV daemon
(`ClamAVScanner`, spoken to over clamd's INSTREAM TCP protocol); dev/CI use
`EicarSignatureScanner`, which has no external dependency and detects the industry-standard
EICAR anti-malware test file. The EICAR string is the accepted way to exercise an AV
integration end to end without handling a real virus — a genuine ClamAV would flag the
same bytes as `Eicar-Test-Signature`. The *gate* (scan runs before extraction, a positive
result blocks the document) is identical regardless of backend.
"""

from __future__ import annotations

import base64
import socket
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass

# The EICAR standard anti-malware test string (not a real virus), stored base64-encoded
# and decoded at import. Kept out of source as plaintext deliberately: a host AV (e.g.
# Windows Defender on a dev machine) would otherwise quarantine this very file for
# containing the literal EICAR bytes.
EICAR_SIGNATURE = base64.b64decode(
    "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
)


@dataclass
class ScanResult:
    is_clean: bool
    signature: str | None = None  # AV signature name when not clean; never the file bytes


class MalwareScanner(ABC):
    @abstractmethod
    def scan(self, data: bytes) -> ScanResult: ...


class EicarSignatureScanner(MalwareScanner):
    """Dependency-free dev/CI scanner. Flags the EICAR test file; treats everything else
    as clean. This is NOT real malware detection — it exists to prove the scan gate works
    and to keep tests/compose from needing a clamd. Production must use ClamAVScanner."""

    def scan(self, data: bytes) -> ScanResult:
        if EICAR_SIGNATURE in data:
            return ScanResult(is_clean=False, signature="Eicar-Test-Signature")
        return ScanResult(is_clean=True)


class ClamAVScanner(MalwareScanner):
    """Production scanner: streams the file to a clamd daemon via the INSTREAM command.

    INSTREAM framing: send ``zINSTREAM\\0``, then for each chunk a 4-byte big-endian
    length prefix followed by the chunk, then a zero-length chunk (``\\x00\\x00\\x00\\x00``)
    to signal end of stream. clamd replies ``stream: OK`` (clean) or
    ``stream: <name> FOUND`` (infected)."""

    _CHUNK = 64 * 1024

    def __init__(self, *, host: str, port: int = 3310, timeout_seconds: float = 30.0):
        self._host = host
        self._port = port
        self._timeout = timeout_seconds

    def scan(self, data: bytes) -> ScanResult:
        with socket.create_connection((self._host, self._port), timeout=self._timeout) as sock:
            sock.settimeout(self._timeout)
            sock.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), self._CHUNK):
                chunk = data[offset : offset + self._CHUNK]
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))  # end-of-stream marker

            response = b""
            while b"\0" not in response:
                part = sock.recv(4096)
                if not part:
                    break
                response += part

        text = response.rstrip(b"\0").decode("utf-8", errors="replace").strip()
        if text.endswith("OK"):
            return ScanResult(is_clean=True)
        # "stream: <signature> FOUND" -> pull out the signature name.
        signature = text
        if text.endswith("FOUND"):
            body = text.split(":", 1)[-1].strip()
            signature = body[: -len("FOUND")].strip() or "unknown"
        return ScanResult(is_clean=False, signature=signature)
