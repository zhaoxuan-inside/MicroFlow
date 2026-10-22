"""Explicit local synchronous execution; no durable acceptance is claimed.

Every run owns its state. Definitions are immutable and input data is copied at
invocation boundaries. Durable scheduling and dynamic controls use later APIs.
"""
import asyncio
from dataclasses import dataclass
from typing import Mapping
from datetime import datetime, timezone
import inspect
import logging
import threading
import time
import uuid

from .errors import Cancelled, ContractError
from .paths import map_values
from .policy import seconds
from .schema import validate
from .sdk import Context, Debug, Input, Log, Metrics, Output
from .values import freeze, thaw, validate_value

logger = logging.getLogger("microflow.lifecycle")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _error(code, phase, exception=None):
    # Raw exception strings and traceback locals may contain credentials.
    return {"code": code, "type": type(exception).__name__ if exception else "FrameworkError",
            "message": code, "phase": phase, "stackRef": None, "effectStatus": "unknown"}


@dataclass(frozen=True)
class RunResult:
    output: Mapping
    nodes: Mapping
    records: tuple


class LocalRuntime:
    """Run an explicitly ephemeral compiled release without background workers.

    A LocalRuntime may be reused, but a run's state and cancellation event are
    independent. This runner intentionally rejects policies it cannot honor.
    """

    def __init__(self, release, *, resources=None):
        self.release = release
        self.resources = dict(resources or {})

    def _preflight(self, flow_id):
        if flow_id not in self.release.flows:
            raise ContractError("UNKNOWN_FLOW", "Flow is not in this release", flow_id)
        visited, pending = set(), [flow_id]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            plan = self.release.flows[current]
            for name, node in plan.definition["nodes"].items():
                kind = node.get("type", "operator")
                policy = plan.policies[name]
                if kind not in ("operator", "subflow", "join") or "condition" in node:
                    raise ContractError("UNSUPPORTED_LOCAL_NODE", "Local runner supports static DAGs only", name)
                if (policy["durability"] != "ephemeral" or policy["execution_mode"] != "sync"
                        or policy["recovery"]["enabled"] or policy["idempotency"]["enabled"]
                        or policy["cache"]["enabled"] or policy["retry"]["max_attempts"] != 1
                        or policy["resource_policy"]["keys"]):
                    raise ContractError("UNSUPPORTED_LOCAL_POLICY", "Policy requires a different runtime", name)
                if kind == "subflow":
                    pending.append(node["flow"])

    def run(self, flow_id, data, *, cancel=None):
        self._preflight(flow_id)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise ContractError("ASYNC_CONTEXT", "Use run_async inside an event loop")
        return asyncio.run(self.run_async(flow_id, data, cancel=cancel))

    async def run_async(self, flow_id, data, *, cancel=None):
        self._preflight(flow_id)
        state = {"cancel": cancel if cancel is not None else threading.Event(), "records": [],
                 "nodes": {}, "stop": None, "root_id": uuid.uuid4().hex, "trace_id": uuid.uuid4().hex,
                 "deadline": float("inf")}
        # An isolated root has no durable execution state and cannot be recovered.
        output = await self._flow(flow_id, data, state, "", None)
        return RunResult(freeze(output), freeze(state["nodes"]), tuple(freeze(state["records"])))

    async def _call(self, method, args):
        if inspect.iscoroutinefunction(method):
            return await method(*args)
        # Blocking Python code never occupies the event loop. No parent waits in
        # this pool, so even a single-thread executor can run nested subflows.
        return await asyncio.to_thread(method, *args)

    def _record(self, state, event, options, **fields):
        record = {"event": event, **thaw(options), **fields}
        state["records"].append(record)
        try:
            logger.info("%s", event, extra={"microflow": record})
        except Exception:
            # A host logging sink cannot alter a committed business outcome.
            pass

    async def _operator(self, op, data, policy, state, flow_options, parent_id, *,
                        on_result=None, invocation_id=None, attempt_id=None, can_pause=True,
                        enforce_return_budget=True):
        invocation = invocation_id or uuid.uuid4().hex
        started = time.monotonic()
        options = {**flow_options, "operatorName": op.name, "operatorVersion": op.version,
                   "invocationId": invocation, "attemptId": attempt_id or uuid.uuid4().hex,
                   "parentInvocationId": parent_id, "executionMode": policy["execution_mode"], "startedAt": None,
                   "endedAt": None, "policy": thaw(policy.values), "policyDigest": policy.policy_digest}
        metrics, log = Metrics(), Log()
        debug = Debug(state["cancel"], can_pause=can_pause)
        resolution, status, error, data_result = "main", "FAILED", None, None
        output = Output()
        try:
            validate(data, self.release.registry.schemas[op.input_schema], "input")
            debug.check_cancelled()
            if time.monotonic() >= state["deadline"]:
                raise ContractError("DEADLINE_EXCEEDED", "Root deadline exceeded")
            options["startedAt"] = _now()
            self._record(state, "attempt_started", options)
            context = Context(options, self.resources)
            args = (Input(data), output, context, metrics, debug, log)
            try:
                accepted = await self._call(op.method, args)
            except (Cancelled, ContractError):
                raise
            except Exception as exc:
                error = _error("UNHANDLED_OPERATOR_EXCEPTION", "main", exc)
                if op.fallback is None:
                    state["stop"] = state["stop"] or error
                    accepted = False
                    resolution = "unhandled_exception"
                else:
                    debug.check_cancelled()
                    output = Output()
                    fallback_input = Input({"business_input": data, "error": error})
                    try:
                        accepted = await self._call(op.fallback, (fallback_input, output, context, metrics, debug, log))
                        resolution = "fallback"
                        if accepted is True:
                            error = None
                        else:
                            error = _error("FALLBACK_FAILED", "fallback")
                    except (Cancelled, ContractError):
                        raise
                    except Exception as fallback_exc:
                        error = {**_error("FALLBACK_FAILED", "fallback", fallback_exc), "cause": error}
                        accepted = False
            if type(accepted) is not bool:
                raise ContractError("INVALID_RETURN", "Operator must return boolean")
            if resolution != "unhandled_exception" and enforce_return_budget:
                debug.check_cancelled()
                if time.monotonic() - started > seconds(policy["timeout"]["attempt"]) or time.monotonic() >= state["deadline"]:
                    raise ContractError("ATTEMPT_TIMEOUT", "Attempt exhausted its time budget")
            if accepted:
                try:
                    validate(output.data, self.release.registry.schemas[op.output_schema], "output.data")
                except ContractError as exc:
                    raise ContractError("OUTPUT_CONTRACT_VIOLATION", "Invalid successful output", exc.diagnostic.path) from exc
                status, data_result = "SUCCEEDED", thaw(output.data)
            elif error is None:
                error = _error("OPERATOR_REJECTED", "main")
        except Cancelled:
            status, error = "CANCELLED", _error("CANCELLED", "execution")
        except ContractError as exc:
            error = _error(exc.diagnostic.error_code, "contract", exc)
        finally:
            options = {**options, "endedAt": _now()}
        result = {"data": data_result, "meta": {"status": status, "resolution": resolution,
                  "releaseId": self.release.release_id, "traceId": state["trace_id"],
                  "invocationId": invocation}, "error": error}
        # State publication precedes optional collectors in scheduled execution.
        # A failed commit escapes without rerunning the business method.
        if on_result is not None:
            await on_result(result)
        self._record(state, "attempt_finished", options, status=status, resolution=resolution,
                     durationMs=(time.monotonic() - started) * 1000, errorCode=error["code"] if error else None)
        # Always record the base lifecycle before optional diagnostic handlers.
        for role in ("metrix", "log"):
            handler = getattr(op, role)
            if handler is None:
                continue
            try:
                payload = Input({"business_input": data, "output": result, "options": options})
                success = await self._call(handler, (payload, Output(), Context(options, self.resources),
                                                    metrics, Debug(threading.Event(), can_pause=False), log))
                if success is not True:
                    raise ContractError("COLLECTOR_REJECTED", "Collector returned failure")
            except Exception as exc:
                self._record(state, "collector_failed", options, role=role, exceptionType=type(exc).__name__)
        self._record(state, "invocation_completed", options, status=status, resolution=resolution,
                     metrics={"counts": dict(metrics.counts), "distributions": metrics.samples})
        return result

    async def _flow(self, flow_id, data, state, prefix, parent_id):
        plan = self.release.flows[flow_id]
        definition = plan.definition
        invocation = parent_id or state["root_id"]
        flow_options = {"scene": definition.get("options", {}).get("scene", flow_id),
                        "version": definition.get("options", {}).get("version", flow_id),
                        "releaseId": self.release.release_id, "traceId": state["trace_id"],
                        "flowInstanceId": state["root_id"]}
        local_nodes = {}
        error, status = None, "SUCCEEDED"
        ancestor_deadline = state["deadline"]
        try:
            validate(data, self.release.registry.schemas[definition["input_schema"]], "flow.input")
            if state["cancel"].is_set() and not plan.graph.order:
                return {"data": None, "meta": {"status": "CANCELLED", "releaseId": self.release.release_id,
                        "traceId": state["trace_id"], "invocationId": invocation, "stopReason": None},
                        "error": _error("CANCELLED", "execution")}
            for policy in plan.policies.values():
                state["deadline"] = min(state["deadline"], time.monotonic() + seconds(policy["timeout"]["deadline"]))
            for name in plan.graph.order:
                node = definition["nodes"][name]
                key = prefix + name
                if state["stop"] or error or state["cancel"].is_set():
                    state["nodes"][key] = {"data": None, "meta": {"status": "SKIPPED"}, "error": None}
                    if state["cancel"].is_set() and error is None:
                        status, error = "CANCELLED", _error("CANCELLED", "execution")
                    continue
                policy = plan.policies[name]
                sources = {"flow": {"input": data}, "nodes": local_nodes, "context": {"options": flow_options}}
                try:
                    mapped = map_values(node.get("inputs", {}), sources)
                    kind = node.get("type", "operator")
                    if kind == "operator":
                        output = await self._operator(self.release.registry.operators[node["operator"]], mapped,
                                                      policy, state, flow_options, invocation)
                    elif kind == "subflow":
                        output = await self._flow(node["flow"], mapped, state, key + "/", uuid.uuid4().hex)
                    else:
                        output = {"data": mapped, "meta": {"status": "SUCCEEDED"}, "error": None}
                except ContractError as exc:
                    output = {"data": None, "meta": {"status": "FAILED"},
                              "error": _error(exc.diagnostic.error_code, "mapping", exc)}
                state["nodes"][key] = output
                local_nodes[name] = {"output": output}
                if output["meta"]["status"] != "SUCCEEDED":
                    status, error = output["meta"]["status"], output["error"]
            if state["stop"]:
                error, status = state["stop"], "FAILED"
            if error:
                result_data = None
            else:
                result_data = map_values(definition.get("outputs", {}), {
                    "flow": {"input": data}, "nodes": local_nodes, "context": {"options": flow_options}})
                validate(result_data, self.release.registry.schemas[definition["output_schema"]], "flow.output.data")
        except ContractError as exc:
            result_data, error, status = None, _error(exc.diagnostic.error_code, "flow", exc), "FAILED"
        finally:
            state["deadline"] = ancestor_deadline
        return {"data": result_data, "meta": {"status": status, "releaseId": self.release.release_id,
                "traceId": state["trace_id"], "invocationId": invocation,
                "stopReason": "CIRCUIT_BROKEN" if state["stop"] else None}, "error": error}
