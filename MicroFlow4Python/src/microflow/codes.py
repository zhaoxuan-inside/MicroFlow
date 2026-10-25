"""Versioned diagnostic code catalog for the Python implementation.

Every code raised in this package must be registered here; emitting an
unregistered code is an implementation defect (mirrors the frontend §41
discipline). `stability` marks whether a code's semantics are asserted by the
cross-implementation CLI conformance suite ("shared", seeded from codes named
in the design documents) or are local to this implementation ("implementation");
the shared set is revised together with docs/design/cli-command-system-design.md.

The catalog is guard-tested bidirectionally against the source tree:
tests/test_cli_system.py fails if a raised code is missing or an entry is dead.
"""
from types import MappingProxyType

PROTOCOL = "microflow-diagnostics-v1"

_SHARED = frozenset({
    "ARTIFACT_DIGEST_MISMATCH", "ATTEMPT_TIMEOUT", "BUDGET_NOT_EXPIRED", "CANCELLED",
    "CLOCK_REGRESSION", "COMMIT_FAILED", "COMMIT_IN_DOUBT", "CONFIG_LIMIT", "CYCLE_DETECTED",
    "DEADLINE_EXCEEDED", "DUPLICATE_FLOW", "DUPLICATE_KEY", "DUPLICATE_MODULE", "DUPLICATE_NODE",
    "DUPLICATE_OPERATOR", "DUPLICATE_SCHEMA", "FALLBACK_FAILED", "FORBIDDEN_OVERRIDE",
    "IDEMPOTENCY_RESULT_EXPIRED", "IDEMPOTENCY_RESULT_INCOMPATIBLE", "INVALID_BINDING",
    "INVALID_CLOCK", "INVALID_JSON", "INVALID_OPERATION_KEY", "INVALID_OPERATION_SCOPE",
    "INVALID_OPERATOR_ID", "INVALID_POLICY", "INVALID_RETURN", "INVALID_SIGNATURE", "INVALID_VALUE",
    "MANIFEST_DIGEST_MISMATCH", "MAPPING_CONFLICT", "MISSING_ARTIFACT", "MISSING_DEPENDENCY_RESULT",
    "MISSING_REGISTER", "MODULE_IMPORT_FAILED", "MODULE_REGISTRATION_FAILED", "OPERATION_STATE_CONFLICT",
    "OPERATOR_REJECTED", "OUTPUT_CONTRACT_VIOLATION", "OWNER_FENCED", "REGISTRY_SEALED",
    "REQUEST_CONFLICT", "REVISION_CONFLICT", "SCHEMA_INCOMPATIBLE", "SOURCE_CHANGED", "STALE_ATTEMPT",
    "UNKNOWN_FLOW", "UNKNOWN_NODE", "UNKNOWN_OPERATOR", "UNKNOWN_POLICY_FIELD", "UNKNOWN_SCHEMA",
    "UNKNOWN_SCHEMA_RULE", "UNSUPPORTED_EXECUTION_STATE", "UNSUPPORTED_JOIN", "UNSUPPORTED_POLICY",
    "VALUE_LIMIT",
})

_SUMMARIES = {
    # 编译与图
    "CYCLE_DETECTED": "Directed cycle in the flow graph or subflow reference graph",
    "DUPLICATE_FLOW": "Duplicate flow id in the project configuration",
    "DUPLICATE_NODE": "Duplicate graph node identifier",
    "DUPLICATE_OPERATOR": "Operator ref is already registered",
    "DUPLICATE_SCHEMA": "Schema name is already registered",
    "UNKNOWN_NODE": "Edge or source references an undeclared node",
    "UNKNOWN_NODE_FIELD": "Unknown field in a node declaration",
    "UNKNOWN_FLOW": "Flow id is not part of this release",
    "UNKNOWN_FLOW_FIELD": "Unknown field in a flow definition",
    "UNKNOWN_OPERATOR": "Operator ref is not registered in this release",
    "UNKNOWN_SCHEMA": "Schema name is not registered",
    "INVALID_PROJECT": "Project configuration is invalid",
    "INVALID_FLOW": "Invalid flow definition structure",
    "INVALID_FLOW_OPTIONS": "Flow options must be nonempty scene and version strings",
    "INVALID_NODE": "Invalid node declaration",
    "INVALID_NODE_FIELD": "Field is not applicable to this node type",
    "INVALID_NODE_TYPE": "Unsupported node type",
    "INVALID_ROUTE": "Route branches or default target are invalid",
    "UNSUPPORTED_JOIN": "Join strategy is not implemented",
    "INVALID_DEPENDENCY": "depends_on must be a list of node ids",
    "INVALID_SOURCE": "Mapping source path is invalid or out of bounds",
    "INVALID_MAPPING": "Mapping rule structure is invalid",
    "MAPPING_CONFLICT": "Overlapping mapping target paths",
    "MISSING_DEPENDENCY_RESULT": "Required source value is missing",
    "CONDITION_TYPE_MISMATCH": "Condition operand types cannot be compared",
    "MISSING_CONDITION_VALUE": "Condition references a missing value",
    "INVALID_CONDITION": "Condition expression is invalid",
    "SPARSE_ARRAY": "Automatic sparse array extension is rejected",
    "PATH_TYPE_MISMATCH": "Path segment applied to the wrong container type",
    "INVALID_PATH": "Path syntax is invalid",
    "IMPACT_STRUCTURE": "Compiled release violates the impact index invariants",
    # 契约与值
    "INVALID_VALUE": "Unsupported or non-finite value",
    "VALUE_LIMIT": "Value exceeds depth or item budget",
    "INVALID_JSON": "Invalid JSON syntax or excessive nesting",
    "DUPLICATE_KEY": "Duplicate JSON object key",
    "CONFIG_LIMIT": "Configuration exceeds the byte budget",
    "INVALID_INPUT": "Input must be a Map",
    "INPUT_CONTRACT_VIOLATION": "Runtime input violated its declared contract",
    "INVALID_RETURN": "Operator must return boolean",
    "OUTPUT_CONTRACT_VIOLATION": "Successful output violates its declared contract",
    "OPERATOR_REJECTED": "Operator reported failure by returning False",
    "UNHANDLED_OPERATOR_EXCEPTION": "Operator raised an unhandled exception",
    "FALLBACK_FAILED": "Fallback did not recover the invocation",
    "ATTEMPT_LOST": "Attempt ownership was lost before completion",
    "EFFECT_IN_DOUBT": "Side-effect outcome is unknown",
    "CANCELLED": "Execution was cancelled cooperatively",
    "SCHEMA_INCOMPATIBLE": "Source and destination types are incompatible",
    "SCHEMA_VIOLATION": "Value violates its schema",
    "SCHEMA_PATH_TYPE_MISMATCH": "Schema path traverses a wrong container type",
    "UNKNOWN_SCHEMA_PATH": "Schema path does not resolve",
    "UNKNOWN_SCHEMA_RULE": "Unknown schema keyword is rejected",
    "INVALID_SCHEMA": "Schema definition is invalid",
    "INVALID_METRIC": "Metric record violates its declaration",
    "METRIC_LIMIT": "Metric record exceeds its budget",
    "INVALID_EVENT": "Event payload violates its schema",
    "EVENT_LIMIT": "Event exceeds its budget",
    "INVALID_QUERY": "Query bounds or cursor are invalid",
    # 注册
    "REGISTRY_SEALED": "Registry is sealed after compilation",
    "INVALID_OPERATOR_ID": "Operator name or version is invalid",
    "INVALID_SIGNATURE": "Handler signature must be (input, output, context, metrix, debug, log)",
    "INVALID_CAPABILITY": "Capability value is invalid",
    "INVALID_CAPABILITIES": "Capability declaration is invalid",
    "FALLBACK_CAPABILITY_REQUIRED": "Fallback capabilities must be declared explicitly",
    "MISSING_REGISTER": "Project module must expose register(registry)",
    "MODULE_IMPORT_FAILED": "Trusted module could not be imported",
    "MODULE_REGISTRATION_FAILED": "Registration of a trusted module failed",
    "DUPLICATE_MODULE": "Duplicate manifest module entry",
    "SOURCE_CHANGED": "Registered source changed before or during compilation",
    # 策略
    "INVALID_POLICY": "Policy configuration is invalid",
    "UNKNOWN_POLICY_FIELD": "Unknown policy field is rejected",
    "UNSUPPORTED_POLICY": "Policy combination is not supported",
    "UNSUPPORTED_LOCAL_NODE": "Local runner supports static DAGs only",
    "UNSUPPORTED_LOCAL_POLICY": "Policy requires a runtime this runner cannot provide",
    "FORBIDDEN_OVERRIDE": "Override is outside the explicit whitelist",
    "CAPABILITY_REQUIRED": "Required provider capability is missing",
    "ASYNC_CONTEXT": "Blocking run rejected inside a running event loop",
    # 协调与状态
    "INVALID_COMMAND": "State command is invalid or incomplete",
    "INVALID_REQUEST": "Control request is invalid",
    "INVALID_RECEIPT": "Receipt does not match the committed batch",
    "INVALID_BATCH": "State batch is invalid",
    "REQUEST_CONFLICT": "Same request id with a different digest",
    "REVISION_CONFLICT": "Expected revision does not match current state",
    "COMMIT_FAILED": "State commit failed durably",
    "COMMIT_IN_DOUBT": "State commit outcome is unknown",
    "INVALID_BINDING": "Storage binding is invalid",
    "BINDING_MISMATCH": "Operation does not match the fixed storage binding",
    "EXECUTION_BINDING_MISMATCH": "Execution does not match the claimed binding",
    "INVALID_OWNER": "Owner identity is invalid",
    "OWNER_BUSY": "Owner slot is occupied",
    "OWNER_FENCED": "Owner generation is fenced out",
    "STALE_ATTEMPT": "Attempt epoch is stale",
    "ATTEMPT_NOT_FENCED": "Attempt is not fenced as required",
    "UNKNOWN_EXECUTION": "Execution id is unknown to this partition",
    "EXECUTION_EXISTS": "Execution already exists for this request",
    "EXECUTION_STOPPED": "Execution is stopped and cannot accept the command",
    "EXECUTION_BACKPRESSURE": "Capacity budget exhausted",
    "EXECUTION_BUDGET": "Execution budget exhausted",
    "NODE_NOT_READY": "Node is not in a claimable state",
    "UNSUPPORTED_SCHEDULED_EFFECT": "Scheduled execution does not support this effect class",
    "UNSUPPORTED_SCHEDULED_NODE": "Scheduled execution does not support this node type",
    "UNSUPPORTED_SCHEDULED_POLICY": "Scheduled execution does not support this policy",
    "UNSUPPORTED_EXECUTION_STATE": "Persisted execution state version is unsupported",
    "INVALID_CLOCK": "Injected clock returned an invalid time",
    "CLOCK_REGRESSION": "Observed clock moved backwards against persisted time",
    "CHECKPOINT_BUDGET": "Checkpoint exceeds its budget",
    "CHECKPOINT_NOT_FOUND": "Checkpoint reference does not resolve",
    "CHECKPOINT_UNAVAILABLE": "Checkpoint is unavailable for recovery",
    "SNAPSHOT_BUDGET": "Debug snapshot exceeds its budget",
    "SNAPSHOT_LIMIT": "Debug snapshot exceeds its structural limit",
    "STATE_BUDGET": "State record exceeds its budget",
    "COORDINATOR_CLOSED": "Coordinator service is closed",
    # 幂等与确认
    "INVALID_OPERATION_KEY": "Business operation key is invalid",
    "INVALID_OPERATION_SCOPE": "Business operation scope is invalid",
    "OPERATION_SCOPE_REQUIRED": "Idempotent nodes require a bound operation scope",
    "OPERATION_PENDING": "Business operation is still in progress",
    "OPERATION_STATE_CONFLICT": "Business operation state conflicts with the request",
    "IDEMPOTENCY_RESULT_EXPIRED": "Confirmed result retention has ended",
    "IDEMPOTENCY_RESULT_INCOMPATIBLE": "Reused result does not satisfy the target contract",
    "UNSAFE_REEXECUTION": "Re-execution would repeat an unconfirmed side effect",
    "UNSAFE_CACHE": "Cache use would bypass a safety protocol",
    "UNSAFE_PAUSE": "Pause would hold critical resources indefinitely",
    # 持久化与产物
    "PROVIDER_PROTOCOL": "Provider protocol violation",
    "UNSUPPORTED_PROVIDER_PROTOCOL": "Provider protocol version is unsupported",
    "INVALID_PROVIDER_SCHEMA": "Provider configuration violates its schema",
    "INVALID_PERSISTENCE_VALUE": "Value cannot cross the persistence boundary",
    "INVALID_RECOVERY_VIEW": "Recovery view is inconsistent or out of bounds",
    "INVALID_RECOVERY_COMMAND": "Recovery command is invalid",
    "INVALID_CURSOR": "Pagination cursor is invalid or closed",
    "INVALID_RELEASE": "Value is not a compiled release",
    "ARTIFACT_DIGEST_MISMATCH": "Artifact bytes do not match their digest",
    "MANIFEST_DIGEST_MISMATCH": "Manifest digest does not match its content",
    "MISSING_ARTIFACT": "Referenced artifact is missing",
    "COLLECTOR_REJECTED": "Optional collector reported failure",
    "DEADLINE_EXCEEDED": "Root deadline exceeded",
    "ATTEMPT_TIMEOUT": "Attempt exhausted its time budget",
    "BUDGET_NOT_EXPIRED": "Referenced budget has not expired",
}


def describe_diagnostics() -> dict:
    """Independent JSON projection of the full code catalog, sorted by code."""
    entries = [{"code": code,
                "summary": summary,
                "stability": "shared" if code in _SHARED else "implementation"}
               for code, summary in sorted(_SUMMARIES.items())]
    return {"protocol": PROTOCOL, "count": len(entries), "diagnostics": entries}


DIAGNOSTICS = MappingProxyType(dict(_SUMMARIES))
