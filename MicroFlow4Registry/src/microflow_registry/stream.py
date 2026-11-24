"""Event frames: the streaming half of the registry face.

A snapshot answers "what is published"; a frame answers "what just happened".
They are deliberately different envelopes: a report is whole and re-computable,
an event has an ordinal, an aggregate and an identity that survives replay.

Frames are *projections*, not framework facts. When the producer already owns an
identity (a framework ``EventIntent``), we keep it verbatim and label the kind
``event_intent``; otherwise the identity is content-derived and labelled
``runtime_record``. Nothing here re-derives execution semantics.
"""
import re

from .envelope import digest
from .errors import RegistryError

STREAM_PROTOCOL = "microflow-registry-stream-v1"
MAX_FRAMES = 500
KIND_RECORD = "runtime_record"
KIND_INTENT = "event_intent"
_AGGREGATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def check_aggregate(value: str) -> str:
    if not isinstance(value, str) or not _AGGREGATE.match(value):
        raise RegistryError("STREAM_INVALID",
                            "aggregateKey must match [A-Za-z0-9][A-Za-z0-9._:@-]{0,127}",
                            path="frames", hint=f"got {value!r}")
    return value


def frame_id(aggregate_key: str, sequence: int, kind: str, payload) -> str:
    """Content-derived identity: same aggregate + ordinal + payload ⇒ same id."""
    return digest({"aggregateKey": aggregate_key, "sequence": sequence,
                   "kind": kind, "payload": payload})


def build_frame(payload, *, aggregate_key: str, sequence: int, kind: str = KIND_RECORD,
                occurred_at: str | None = None, event_id: str | None = None) -> dict:
    check_aggregate(aggregate_key)
    if type(sequence) is not int or sequence < 1:
        raise RegistryError("STREAM_INVALID", "sequence must be a positive integer",
                            path="frames", hint=f"got {sequence!r}")
    if kind not in (KIND_RECORD, KIND_INTENT):
        raise RegistryError("STREAM_INVALID", f"unknown frame kind {kind!r}", path="frames")
    identifier = event_id or frame_id(aggregate_key, sequence, kind, payload)
    frame = {"eventId": identifier, "aggregateKey": aggregate_key, "sequence": sequence,
             "kind": kind, "payload": payload}
    if occurred_at:
        frame["occurredAt"] = occurred_at
    return frame


def build_batch(namespace: str, group: str, frames, *, source: dict | None = None) -> dict:
    """Deterministic batch; frames are ordered by (aggregateKey, sequence)."""
    ordered = sorted(frames, key=lambda frame: (frame["aggregateKey"], frame["sequence"]))
    if len(ordered) > MAX_FRAMES:
        raise RegistryError("BATCH_TOO_LARGE",
                            f"batch has {len(ordered)} frames, budget is {MAX_FRAMES}",
                            hint="flush more often; the sink does this automatically")
    body = {"protocol": STREAM_PROTOCOL, "namespace": namespace, "group": group,
            "count": len(ordered), "frames": ordered}
    if source:
        body["source"] = source
    body["contentDigest"] = digest(body)
    return body


def validate_batch(value) -> dict:
    """Load-side gate: shape, budget, aggregate keys and the self-digest."""
    if not isinstance(value, dict):
        raise RegistryError("STREAM_INVALID", "batch must be a JSON object")
    if value.get("protocol") != STREAM_PROTOCOL:
        raise RegistryError("STREAM_INVALID",
                            f"expected protocol {STREAM_PROTOCOL!r}, got {value.get('protocol')!r}",
                            hint="produce batches with this package or match the documented shape")
    frames = value.get("frames")
    if not isinstance(frames, list) or not frames:
        raise RegistryError("STREAM_INVALID", "frames must be a nonempty array")
    if len(frames) > MAX_FRAMES:
        raise RegistryError("BATCH_TOO_LARGE", f"batch has {len(frames)} frames, budget is {MAX_FRAMES}")
    for index, frame in enumerate(frames):
        path = f"frames[{index}]"
        if not isinstance(frame, dict):
            raise RegistryError("STREAM_INVALID", "frame must be an object", path=path)
        check_aggregate(frame.get("aggregateKey"))
        sequence = frame.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise RegistryError("STREAM_INVALID", "sequence must be a positive integer", path=path)
        if not isinstance(frame.get("eventId"), str) or not frame["eventId"]:
            raise RegistryError("STREAM_INVALID", "eventId must be a nonempty string", path=path)
        kind = frame.get("kind")
        if kind not in (KIND_RECORD, KIND_INTENT):
            raise RegistryError("STREAM_INVALID", f"unknown frame kind {kind!r}", path=path)
        if kind == KIND_RECORD:
            expected = frame_id(frame["aggregateKey"], sequence, kind, frame.get("payload"))
            if frame["eventId"] != expected:
                raise RegistryError("STREAM_DIGEST_MISMATCH",
                                    "runtime_record eventId is not derived from its content",
                                    path=path, hint="recompute with frame_id(); do not patch ids")
    without_digest = {key: item for key, item in value.items() if key != "contentDigest"}
    if value.get("contentDigest") != digest(without_digest):
        raise RegistryError("STREAM_DIGEST_MISMATCH",
                            "contentDigest does not match the frames",
                            hint="re-run the producer instead of editing the batch")
    return value
