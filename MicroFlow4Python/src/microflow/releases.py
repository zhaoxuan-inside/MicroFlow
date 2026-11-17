"""Immutable candidate construction and the durable publication slice (T12).

Publication is content-addressed: the release manifest is stored under its own
digest (which is the release_id) and every source file under its SHA-256. There
is no separate index and no mutable pointer — a release id either resolves to a
byte-identical snapshot or it does not resolve. Loading re-imports the stored
sources from their recorded paths (a T12 slice, not a full deployment protocol:
cross-machine materialization and medium migration remain future work) and
recompiles; the round trip is accepted only when the recomputed release_id
matches the published one.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from .errors import ContractError
from .values import canonical, digest, freeze, thaw, load_json

RELEASE_PROTOCOL = "microflow-release-v1"


@dataclass(frozen=True)
class CandidateSnapshot:
    release_id: str
    manifest: Mapping
    sources: Mapping

    def verify(self):
        if digest(self.manifest) != self.release_id:
            raise ContractError("MANIFEST_DIGEST_MISMATCH", "Manifest does not match release identity")
        expected = self.manifest["sources"]
        if set(expected) != set(self.sources):
            raise ContractError("MISSING_ARTIFACT", "Candidate source set does not match manifest")
        for path, checksum in expected.items():
            if hashlib.sha256(self.sources[path]).hexdigest() != checksum:
                raise ContractError("ARTIFACT_DIGEST_MISMATCH", "Source digest mismatch", path)
        return self


def build_candidate(release):
    return CandidateSnapshot(release.release_id, freeze(release.manifest), freeze(release.sources)).verify()


def _manifest_blob(manifest) -> bytes:
    """Store the manifest in the framework's canonical framed form.

    The artifact store keys content by sha256(bytes); the release_id already IS
    sha256(canonical(manifest)), so the canonical blob is the one serialization
    whose content address matches the release identity — no pointer table.
    """
    return canonical(thaw(manifest))


def _unframed(blob: bytes):
    """Inverse of values.canonical for stored snapshots; strictly validated."""
    try:
        framed = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ContractError("INVALID_RELEASE", "Stored snapshot is not valid JSON") from error
    if not isinstance(framed, list) or len(framed) != 2 or framed[0] != "microflow-canonical-v1":
        raise ContractError("INVALID_RELEASE", "Stored snapshot is not a canonical snapshot")
    def decode(node):
        if (not isinstance(node, list) or not node or type(node[0]) is not str
                or (node[0] in ("bool", "int", "float", "str") and len(node) != 2)
                or node[0] in ("null",) and len(node) != 1):
            raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
        tag = node[0]
        if tag == "null":
            return None
        if tag == "bool":
            if type(node[1]) is not bool:
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return node[1]
        if tag == "int":
            if type(node[1]) is not str:
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return int(node[1])
        if tag == "float":
            if type(node[1]) is not str:
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return float.fromhex(node[1])
        if tag == "str":
            if type(node[1]) is not str:
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return node[1]
        if tag == "map":
            if not isinstance(node[1], list) or any(not isinstance(pair, list) or len(pair) != 2
                                                    or type(pair[0]) is not str for pair in node[1]):
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return {pair[0]: decode(pair[1]) for pair in node[1]}
        if tag == "list":
            if not isinstance(node[1], list):
                raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
            return [decode(item) for item in node[1]]
        raise ContractError("INVALID_RELEASE", "Stored snapshot framing is malformed")
    return decode(framed[1])


def publish(release, artifacts) -> str:
    """Store the candidate snapshot content-addressed. Idempotent by digest.

    The manifest goes under the release_id (its canonical bytes hash to it),
    every source under its SHA-256; put_immutable rejects any digest/bytes
    mismatch, so a corrupted publish fails loudly instead of storing a wrong
    snapshot.
    """
    candidate = build_candidate(release).verify()
    artifacts.put_immutable(candidate.release_id, _manifest_blob(candidate.manifest))
    for path, content in sorted(candidate.sources.items()):
        artifacts.put_immutable(hashlib.sha256(content).hexdigest(), content)
    return candidate.release_id


def load_release(release_id, artifacts):
    """Rebuild a compiled release from its published snapshot.

    Sources are re-imported from their recorded paths on this host; drift or
    absence is an explicit failure, never a silent substitution. Identity is
    verified twice: the stored manifest against the requested id, and the
    recompiled release against the same id.
    """
    if (type(release_id) is not str or not release_id or len(release_id) != 64
            or any(c not in "0123456789abcdef" for c in release_id)):
        raise ContractError("INVALID_RELEASE", "Release id must be a lowercase sha-256 hex digest")
    manifest = _unframed(artifacts.get(release_id))
    if not isinstance(manifest, Mapping) or manifest.get("protocol") != RELEASE_PROTOCOL:
        raise ContractError("INVALID_RELEASE", "Stored snapshot is not a release manifest")
    if digest(manifest) != release_id:
        raise ContractError("MANIFEST_DIGEST_MISMATCH", "Stored manifest does not match the release id")
    sources = manifest.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise ContractError("INVALID_RELEASE", "Release manifest carries no sources")
    for path, checksum in sorted(sources.items()):
        current = Path(path)
        try:
            content = current.read_bytes()
        except OSError as error:
            raise ContractError("MISSING_ARTIFACT",
                                "Published source is absent on this host; restore or republish",
                                path) from error
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ContractError("SOURCE_CHANGED", "Published source drifted since publication", path)
    from .registry import discover
    from .compiler import compile_release
    registry = discover([Path(path) for path in sorted(sources)])
    release = compile_release(registry, list(manifest["flows"].values()),
                              defaults=dict(manifest.get("defaults") or {}))
    if release.release_id != release_id:
        raise ContractError("MANIFEST_DIGEST_MISMATCH",
                            "Recompiled identity differs from the published release id; "
                            "the source layout moved on this host, republish from the current layout",
                            release_id)
    return release
