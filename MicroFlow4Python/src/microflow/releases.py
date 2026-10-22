"""Immutable candidate construction; durable publication is a separate protocol."""
from dataclasses import dataclass
import hashlib
from typing import Mapping

from .errors import ContractError
from .values import digest, freeze


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
