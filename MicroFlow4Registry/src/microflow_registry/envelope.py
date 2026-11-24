"""Canonical JSON, content digests and the deterministic output envelope.

Two rules make every report auditable: canonical serialization (sorted keys,
ASCII only, compact separators, no NaN) so the same input yields the same
bytes, and SHA-256 digests over that canonical form so a report is addressed
by what it says rather than by when it was produced.
"""
import hashlib
import json


def canonical(value) -> str:
    """Deterministic JSON text; raises ValueError for NaN/Infinity."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    """Content digest of a JSON-compatible value."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def bytes_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def report_body(report: dict) -> dict:
    """The digestable part: everything except volatile meta, the digest and the portable key."""
    return {key: value for key, value in report.items()
            if key not in ("meta", "digest", "contentDigest")}


def report_digest(report: dict) -> str:
    return digest(report_body(report))


def dumps(value) -> str:
    """Single-line canonical text used for stdout (same input, same bytes)."""
    return canonical(value)
