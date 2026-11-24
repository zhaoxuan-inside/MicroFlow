"""Diagnostic catalog: every code this package can emit.

The catalog is a single source of truth. The guard test scans the source for
raised codes and requires an exact match in both directions, so an
unregistered code (or a dead entry) fails the build instead of drifting.
"""

PROTOCOL = "microflow-registry-v1"

# code -> human description. Sorted projection is produced by describe_diagnostics.
DIAGNOSTICS = {
    "CLI_UNAVAILABLE": "Cannot launch the MicroFlow CLI",
    "CLI_TIMEOUT": "The MicroFlow CLI exceeded its time budget",
    "CLI_FAILED": "The MicroFlow CLI rejected the request",
    "CLI_PROTOCOL_MISMATCH": "CLI output is not a microflow-cli-v1 envelope",
    "CLI_CONTRACT_MISMATCH": "A CLI envelope lacks a documented result key",
    "UNSUPPORTED_COMMAND": "The installed CLI lacks a command this projection requires",
    "INVALID_ADDRESSING": "Namespace, group or asset id is not a valid addressing key",
    "PROJECT_CHECK_FAILED": "The project did not pass the framework's static gate",
    "RELEASE_MISMATCH": "CLI commands disagree about the project release id",
    "REPORT_INVALID": "The report file is not a valid JSON object",
    "REPORT_PROTOCOL_MISMATCH": "The report does not speak microflow-registry-v1",
    "REPORT_DIGEST_MISMATCH": "The report digest does not match its own content",
    "STREAM_INVALID": "The event batch is not a valid microflow-registry-stream-v1 payload",
    "STREAM_DIGEST_MISMATCH": "The batch contentDigest does not match its frames",
    "BATCH_TOO_LARGE": "The event batch exceeds the frame budget",
    "REGISTRY_DIGEST_CONFLICT": "Same asset id with a different digest already exists locally",
    "ENDPOINT_NOT_CONFIGURED": "No dispatch endpoint is configured",
    "TOKEN_NOT_CONFIGURED": "No dispatch token is configured",
    "PUSH_FAILED": "The dispatch endpoint rejected or could not receive the report",
    "RATE_LIMITED": "The dispatch endpoint is overloaded (429); retry later",
    "ENVELOPE_INVALID": "The dispatch response is not a host-contract envelope",
    "STORE_CORRUPT": "The local snapshot store cannot be read",
    "EPHEMERAL_REQUIRED": "This command compiles or executes and requires --ephemeral",
    "EPHEMERAL_REJECTED": "This command is declarative and rejects --ephemeral",
    "UNEXPECTED_FAILURE": "An unexpected error escaped the command boundary",
}


def describe_diagnostics():
    """Sorted, stable projection used by tests and `status --json` consumers."""
    return {"protocol": PROTOCOL, "count": len(DIAGNOSTICS),
            "diagnostics": [{"code": code, "description": DIAGNOSTICS[code]}
                            for code in sorted(DIAGNOSTICS)]}
