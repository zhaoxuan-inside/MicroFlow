"""Atomic static-DAG commands. This module does not execute or redeliver business work."""
from dataclasses import asdict
from collections.abc import Mapping
import math
from .errors import ContractError, PersistenceError
from .paths import Field, map_values, parse
from .persistence import StateBatch, StorageBinding
from .events import EventIntent
from .schema import validate
from .releases import build_candidate
from .policy import seconds
from .timing import BudgetClock
from .idempotency import OperationScope, OPERATION_PROTOCOL, load_operation
from .values import digest, freeze, thaw, validate_value

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "IN_DOUBT"})
NODE_TERMINAL = TERMINAL | {"SKIPPED"}
STATE_PROTOCOL = "microflow-execution-state-v2"


def _id(value, label):
    if type(value) is not str or not value or len(value) > 256:
        raise ContractError("INVALID_COMMAND", f"{label} must be a nonempty string of at most 256 characters")


def _error(code):
    return {"code": code, "message": code, "phase": "execution", "effectStatus": "unknown"}


class ExecutionCommands:
    """Trusted host state API; workers never mutate the store directly.

    Production requires a durable Coordinator. protocol_test explicitly permits
    ephemeral stores for protocol tests, never production async acceptance.
    Claimed attempts are not automatically reassigned after a lost worker.
    """
    def __init__(self, coordinator, release, *, binding, protocol_test=False,
                 max_active=100, max_nodes=1000, max_claimed=16, clock=None, operation_scopes=None):
        if not isinstance(binding, StorageBinding):
            raise PersistenceError("INVALID_BINDING", "Expected a StorageBinding")
        if type(protocol_test) is not bool:
            raise ContractError("INVALID_COMMAND", "protocol_test must be boolean")
        if not protocol_test and not coordinator.durable:
            raise PersistenceError("CAPABILITY_REQUIRED", "Execution acceptance requires a durable coordinator")
        for budget in (max_active, max_nodes, max_claimed):
            if type(budget) is not int or budget < 1:
                raise ContractError("INVALID_COMMAND", "Command budgets must be positive integers")
        if coordinator.view().binding_revision != binding.binding_revision:
            raise PersistenceError("BINDING_MISMATCH", "Recovery view does not match the bound revision")
        build_candidate(release).verify()
        self.coordinator = coordinator
        self.release = release
        self.binding = binding
        self.protocol_test = protocol_test
        self.max_active, self.max_nodes = max_active, max_nodes
        self.max_claimed = max_claimed
        self._clock = BudgetClock() if clock is None else clock
        if not callable(self._clock):
            raise ContractError("INVALID_CLOCK", "Expected a callable budget clock")
        if operation_scopes is not None and (not isinstance(operation_scopes, Mapping)
                or any(type(k) is not str or not isinstance(v, OperationScope) for k, v in operation_scopes.items())):
            raise ContractError("INVALID_OPERATION_SCOPE", "Expected trusted operator-to-scope bindings")
        self.operation_scopes = freeze(dict(operation_scopes or {}))

    def clock_time(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise PersistenceError("INVALID_CLOCK", "Budget clock must return nonnegative finite seconds")
        return now

    def _observe(self, run):
        now = self.clock_time()
        if now < run["observed_at"]:
            raise PersistenceError("CLOCK_REGRESSION", "Clock is behind the persisted observation")
        run["observed_at"] = now
        return now

    def _preflight(self, flow_id):
        if type(flow_id) is not str or flow_id not in self.release.flows:
            raise ContractError("UNKNOWN_FLOW", "Unknown flow")
        plan = self.release.flows[flow_id]
        if len(plan.graph.order) > self.max_nodes:
            raise ContractError("EXECUTION_BUDGET", "Flow exceeds command node budget")
        for name, node in plan.definition["nodes"].items():
            _id(name, "node_id")
            if node.get("type", "operator") != "operator" or "condition" in node:
                raise ContractError("UNSUPPORTED_SCHEDULED_NODE", "Commands currently support static operator DAGs", name)
            policy = plan.policies[name]
            operator = self.release.registry.operators[node["operator"]]
            if operator.capabilities.get("effect") not in ("pure", "read"):
                raise ContractError("UNSUPPORTED_SCHEDULED_EFFECT", "Write operations require the effect confirmation protocol", name)
            if operator.fallback and operator.fallback_capabilities.get("effect") not in ("pure", "read"):
                raise ContractError("UNSUPPORTED_SCHEDULED_EFFECT", "Fallback needs the effect confirmation protocol", name)
            if policy["idempotency"]["enabled"] and node["operator"] not in self.operation_scopes:
                raise ContractError("OPERATION_SCOPE_REQUIRED", "Business idempotency requires a trusted operation scope", name)
            if policy["idempotency"]["enabled"]:
                for path in policy["idempotency"]["key_paths"]:
                    tokens = parse(path)
                    if len(tokens) < 2 or tokens[0] != Field("input"):
                        raise ContractError("INVALID_OPERATION_KEY", "Business keys must reference input fields", name)
            if (policy["cache"]["enabled"]
                    or policy["retry"]["max_attempts"] != 1 or policy["resource_policy"]["keys"]):
                raise ContractError("UNSUPPORTED_SCHEDULED_POLICY", "Policy needs a later scheduling protocol", name)
            if not self.protocol_test and (policy["durability"] != "durable"
                    or policy["persistence_binding"] != self.binding.binding_id):
                raise PersistenceError("BINDING_MISMATCH", "Node policy does not match the durable binding", name)
        return plan

    def _sources(self, run):
        return {"flow": {"input": run["input"]},
                "nodes": {name: {"output": node["output"]} for name, node in run["nodes"].items()
                          if node["output"] is not None}, "context": {"options": run["options"]}}

    def _load(self, view, execution_id):
        if view.binding_revision != self.binding.binding_revision:
            raise PersistenceError("BINDING_MISMATCH", "Recovery view changed binding revision")
        _id(execution_id, "execution_id")
        key = "execution/" + execution_id
        if key not in view.records:
            raise ContractError("UNKNOWN_EXECUTION", "Execution does not exist")
        run = thaw(view.records[key])
        if run.get("protocol") != STATE_PROTOCOL:
            raise PersistenceError("UNSUPPORTED_EXECUTION_STATE", "Execution state needs an explicit timing migration")
        if (run["release_id"] != self.release.release_id or run["binding"] != asdict(self.binding)
                or run["protocol_test"] != self.protocol_test):
            raise PersistenceError("EXECUTION_BINDING_MISMATCH", "Execution belongs to another release or binding")
        return key, run

    def _summary(self, run):
        return {"execution_id": run["execution_id"], "status": run["status"],
                "release_id": run["release_id"], "output": run["output"],
                "protocol_test": self.protocol_test, "durability": "ephemeral" if self.protocol_test else "durable"}

    def _batch(self, key, run, command_id, event, *, operations=None):
        event_id = digest({"execution": run["execution_id"], "command": command_id})
        sequence = run.get("event_sequence", 0) + 1
        run["event_sequence"] = sequence
        event_record = EventIntent(event_id, "microflow.execution", "1", run["execution_id"], sequence,
                                    {"event": event, "status": run["status"]}, run["execution_id"],
                                    run["release_id"], run["observed_at"], run["observed_at"])
        intent = {**event_record.value(), "execution_id": run["execution_id"], "event": event,
                  "owner": asdict(self.coordinator.owner), "release_id": run["release_id"],
                  "status": run["status"], "delivery": "PENDING",
                  "content_digest": event_record.content_digest}
        return StateBatch({key: run, "event-intent/" + event_id: intent,
                           **{"operation/" + oid: record for oid, record in (operations or {}).items()}})

    def _transact(self, operation, payload, decide, request_id, expected_revision):
        _id(request_id, "request_id")
        command = {"operation": operation, "binding": asdict(self.binding),
                   "release_id": self.release.release_id, "payload": payload,
                   "expected_revision": expected_revision}
        def checked(view):
            if view.binding_revision != self.binding.binding_revision:
                raise PersistenceError("BINDING_MISMATCH", "Recovery view changed binding revision")
            return decide(view)
        return self.coordinator.transact(checked, request_id, request_digest=digest(command),
                                         expected_revision=expected_revision)

    def accept(self, flow_id, data, *, request_id, expected_revision=None):
        _id(request_id, "request_id")
        plan = self._preflight(flow_id)
        validate_value(data)
        data = freeze(data)
        validate(data, self.release.registry.schemas[plan.definition["input_schema"]], "flow.input")
        execution_id = digest({"binding": asdict(self.binding), "request_id": request_id})
        key = "execution/" + execution_id
        def decide(view):
            if key in view.records:
                raise PersistenceError("EXECUTION_EXISTS", "Execution identity already exists without its command receipt")
            active = sum(1 for k, r in view.records.items() if k.startswith("execution/") and r["status"] not in TERMINAL)
            if active >= self.max_active:
                raise ContractError("EXECUTION_BACKPRESSURE", "Active execution budget exhausted")
            options = {"scene": flow_id, "version": flow_id, **thaw(plan.definition.get("options", {})), "releaseId": self.release.release_id,
                       "flowInstanceId": execution_id, "traceId": execution_id}
            now = self.clock_time()
            deadline = min((seconds(p["timeout"]["deadline"]) for p in plan.policies.values()), default=300)
            run = {"protocol": STATE_PROTOCOL, "execution_id": execution_id,
                   "flow_id": flow_id, "release_id": self.release.release_id, "binding": asdict(self.binding),
                   "protocol_test": self.protocol_test, "input": thaw(data), "options": options,
                   "status": "ACCEPTED", "stop": None, "output": None,
                   "accepted_at": now, "observed_at": now, "deadline_at": now + deadline,
                   "policies": {n: {"values": thaw(p.values), "digest": p.policy_digest,
                                    **({"operation_scope": asdict(self.operation_scopes[plan.definition["nodes"][n]["operator"]])}
                                       if p["idempotency"]["enabled"] else {})} for n, p in plan.policies.items()},
                   "nodes": {n: {"status": "WAITING" if plan.graph.predecessors[n] else "READY",
                                  "operator": plan.definition["nodes"][n]["operator"],
                                  "attempt_epoch": 0, "owner": None, "worker_id": None,
                                  "input": None, "output": None, "cancel_requested": False,
                                  "ready_at": None, "queue_deadline_at": None, "claimed_at": None,
                                  "attempt_deadline_at": None, "finished_at": None, "timeout_code": None}
                             for n in plan.graph.order}}
            for name in plan.graph.order:
                if run["nodes"][name]["status"] == "READY":
                    self._mark_ready(run, name, now)
            self._advance(run, now)
            result = {**self._summary(run), "status": "ACCEPTED", "execution_status": run["status"]}
            return self._batch(key, run, request_id, "execution_accepted"), result
        return self._transact("accept", {"flow_id": flow_id, "input": data}, decide, request_id, expected_revision)

    def query(self, execution_id):
        _, run = self._load(self.coordinator.view(), execution_id)
        return freeze(run)

    def ready(self, execution_id):
        run = self.query(execution_id)
        return tuple(n for n in self.release.flows[run["flow_id"]].graph.order
                     if run["nodes"][n]["status"] == "READY" and run["stop"] is None)

    @staticmethod
    def _deadlines(run):
        if run["status"] in TERMINAL:
            return []
        pending = []
        if run["stop"] is None:
            pending.append((run["deadline_at"], 0, "", "DEADLINE_EXCEEDED"))
            pending.extend((n["queue_deadline_at"], 1, name, "QUEUE_TIMEOUT")
                           for name, n in run["nodes"].items() if n["status"] in ("READY", "WAITING_OPERATION"))
        pending.extend((n["attempt_deadline_at"], 2, name, "ATTEMPT_TIMEOUT")
                       for name, n in run["nodes"].items()
                       if n["status"] == "CLAIMED" and n["timeout_code"] is None)
        return sorted(pending)

    def next_expiry(self, run):
        pending = self._deadlines(run)
        return pending[0][0] if pending else None

    def _expire(self, run, now):
        changed = False
        for deadline, _, name, code in self._deadlines(run):
            if now < deadline:
                break
            if code == "DEADLINE_EXCEEDED":
                if run["stop"] is not None:
                    continue
                for node in run["nodes"].values():
                    if node["status"] == "CLAIMED" and node["timeout_code"] is None:
                        node["timeout_code"] = code
            elif code == "QUEUE_TIMEOUT":
                node = run["nodes"][name]
                if node["status"] not in ("READY", "WAITING_OPERATION"):
                    continue
                node.update(status="FAILED", timeout_code=code, finished_at=now)
                node["output"] = self._output(run, "FAILED", None,
                    {**_error(code), "phase": "queue", "effectStatus": "not_started"}, node_id=name)
            else:
                node = run["nodes"][name]
                if node["status"] != "CLAIMED" or node["timeout_code"] is not None:
                    continue
                node["timeout_code"] = code
            self._stop(run, _error(code))
            changed = True
        return changed

    def expire(self, execution_id, *, request_id, expected_revision=None):
        """Observe due budgets atomically; never claim that a live thread has stopped."""
        def decide(view):
            key, run = self._load(view, execution_id)
            now = self._observe(run)
            if run["status"] in TERMINAL:
                return None, self._summary(run)
            if not self._expire(run, now):
                raise ContractError("BUDGET_NOT_EXPIRED", "No pending budget has expired")
            self._advance(run, now)
            return self._batch(key, run, request_id, "budget_expired"), self._summary(run)
        return self._transact("expire", {"execution_id": execution_id}, decide, request_id, expected_revision)

    def _stop(self, run, reason):
        run["stop"] = run["stop"] or reason
        for node in run["nodes"].values():
            if node["status"] in ("READY", "WAITING", "WAITING_OPERATION"):
                node["status"] = "SKIPPED"
            elif node["status"] == "CLAIMED":
                node["cancel_requested"] = True

    def _mark_ready(self, run, name, now):
        run["nodes"][name].update(status="READY", ready_at=now,
            queue_deadline_at=now + seconds(run["policies"][name]["values"]["timeout"]["queue"]))

    def _advance(self, run, now):
        plan = self.release.flows[run["flow_id"]]
        nodes = run["nodes"]
        if run["stop"] is None:
            for name in plan.graph.order:
                node = nodes[name]
                if node["status"] == "WAITING" and all(nodes[p]["status"] == "SUCCEEDED" for p in plan.graph.predecessors[name]):
                    self._mark_ready(run, name, now)
            if not all(n["status"] == "SUCCEEDED" for n in nodes.values()):
                return
            try:
                data = map_values(plan.definition.get("outputs", {}), self._sources(run))
                validate(data, self.release.registry.schemas[plan.definition["output_schema"]], "output.data")
                run["status"] = "SUCCEEDED"
                run["output"] = self._output(run, "SUCCEEDED", data, None)
                return
            except ContractError:
                self._stop(run, _error("OUTPUT_CONTRACT_VIOLATION"))
        if any(n["status"] == "CLAIMED" for n in nodes.values()):
            run["status"] = "STOPPING"
            return
        run["status"] = ("IN_DOUBT" if any(n["status"] == "IN_DOUBT" for n in nodes.values())
                         else "CANCELLED" if run["stop"]["code"] == "CANCELLED" else "FAILED")
        run["output"] = self._output(run, run["status"], None, run["stop"])

    def _output(self, run, status, data, error, resolution="main", node_id=None):
        return {"data": data, "meta": {"status": status, "resolution": resolution,
                "releaseId": run["release_id"], "traceId": run["options"]["traceId"],
                "invocationId": digest([run["execution_id"], node_id]) if node_id else run["execution_id"]}, "error": error}

    def _reject_node(self, run, name, code, now):
        node = run["nodes"][name]
        node.update(status="FAILED", finished_at=now,
                    output=self._output(run, "FAILED", None, _error(code), node_id=name))
        self._stop(run, node["output"]["error"])
        self._advance(run, now)

    def _apply_operation(self, run, name, record, now):
        node = run["nodes"][name]
        if now < record["observed_at"]:
            raise PersistenceError("CLOCK_REGRESSION", "Clock is behind the business operation observation")
        if record["status"] == "IN_PROGRESS":
            node["status"] = "WAITING_OPERATION"
            return
        if record["status"] == "IN_DOUBT":
            node.update(status="IN_DOUBT", finished_at=None,
                output=self._output(run, "IN_DOUBT", None, _error("EFFECT_IN_DOUBT"), "idempotency", name))
        else:
            if now >= record["retain_until"]:
                raise ContractError("IDEMPOTENCY_RESULT_EXPIRED", "Business result retention elapsed; identity remains reserved")
            result = record["result"]
            if result["status"] == "SUCCEEDED":
                plan = self.release.flows[run["flow_id"]]
                op = self.release.registry.operators[plan.definition["nodes"][name]["operator"]]
                try:
                    validate(result["data"], self.release.registry.schemas[op.output_schema], "output.data")
                except ContractError as error:
                    raise ContractError("IDEMPOTENCY_RESULT_INCOMPATIBLE", "Original result cannot satisfy this release") from error
            node.update(status=result["status"], finished_at=now,
                output=self._output(run, result["status"], thaw(result["data"]), thaw(result["error"]), "idempotency", name))
        node["operation_replayed"] = True
        node["output"]["meta"].update(sourceReleaseId=record["origin"]["release_id"],
            sourceInvocationId=digest([record["origin"]["execution_id"], record["origin"]["node_id"]]))
        if node["status"] != "SUCCEEDED":
            self._stop(run, node["output"]["error"])

    def _owned_operation(self, view, run, name):
        node = run["nodes"][name]
        if not node.get("operation_id"):
            return None
        record = load_operation(view, node["operation_id"], node["operation_request_digest"])
        origin = {"execution_id": run["execution_id"], "node_id": name, "release_id": run["release_id"],
                  "owner": node["owner"], "attempt_epoch": node["attempt_epoch"]}
        if record is None or record["status"] != "IN_PROGRESS" or digest(record["origin"]) != digest(origin):
            raise PersistenceError("OPERATION_STATE_CONFLICT", "Attempt does not own the business operation")
        return record

    def pending_operations(self, execution_id):
        view = self.coordinator.view()
        _, run = self._load(view, execution_id)
        pending = {}
        for name, node in run["nodes"].items():
            if node["status"] != "WAITING_OPERATION":
                continue
            record = load_operation(view, node["operation_id"], node["operation_request_digest"])
            if record is None:
                raise PersistenceError("OPERATION_STATE_CONFLICT", "Referenced business operation is missing")
            pending[name] = {"operation_id": node["operation_id"], "status": record["status"]}
        return pending

    def refresh_operations(self, execution_id, *, request_id, expected_revision=None):
        def decide(view):
            key, run = self._load(view, execution_id)
            now = self._observe(run)
            changed = self._expire(run, now)
            if run["stop"] is None:
                for name, node in run["nodes"].items():
                    if node["status"] != "WAITING_OPERATION":
                        continue
                    record = load_operation(view, node["operation_id"], node["operation_request_digest"])
                    if record is None:
                        raise PersistenceError("OPERATION_STATE_CONFLICT", "Referenced business operation is missing")
                    if record["status"] == "IN_PROGRESS":
                        continue
                    try:
                        self._apply_operation(run, name, record, now)
                    except ContractError as error:
                        self._reject_node(run, name, error.diagnostic.error_code, now)
                    changed = True
                    if run["stop"] is not None:
                        break
            if not changed:
                raise ContractError("OPERATION_PENDING", "No confirmed business operation became available")
            self._advance(run, now)
            return self._batch(key, run, request_id, "operation_reused"), self._summary(run)
        return self._transact("refresh_operations", {"execution_id": execution_id}, decide, request_id, expected_revision)

    def claim(self, execution_id, node_id, *, worker_id, request_id, expected_revision=None):
        _id(node_id, "node_id")
        _id(worker_id, "worker_id")
        def decide(view):
            key, run = self._load(view, execution_id)
            now = self._observe(run)
            if self._expire(run, now):
                self._advance(run, now)
                return self._batch(key, run, request_id, "budget_expired"), self._summary(run)
            if run["stop"] is not None or run["status"] in TERMINAL:
                raise ContractError("EXECUTION_STOPPED", "Execution no longer permits dispatch")
            node = run["nodes"].get(node_id)
            if node is None or node["status"] != "READY":
                raise ContractError("NODE_NOT_READY", "Node is not ready for a new claim")
            plan = self.release.flows[run["flow_id"]]
            operator = self.release.registry.operators[plan.definition["nodes"][node_id]["operator"]]
            try:
                data = map_values(plan.definition["nodes"][node_id].get("inputs", {}), self._sources(run))
                validate(data, self.release.registry.schemas[operator.input_schema], "input")
            except ContractError:
                node["status"] = "FAILED"
                node["finished_at"] = now
                node["output"] = self._output(run, "FAILED", None, _error("INPUT_CONTRACT_VIOLATION"), node_id=node_id)
                self._stop(run, node["output"]["error"])
                self._advance(run, now)
                return self._batch(key, run, request_id, "input_rejected"), self._summary(run)
            operations = {}
            policy = run["policies"][node_id]["values"]
            if policy["idempotency"]["enabled"]:
                try:
                    scope = OperationScope(**run["policies"][node_id]["operation_scope"])
                    operation_id, request_digest = scope.identify(data, policy["idempotency"]["key_paths"])
                    record = load_operation(view, operation_id, request_digest)
                    node.update(operation_id=operation_id, operation_request_digest=request_digest)
                    if record is not None:
                        self._apply_operation(run, node_id, record, now)
                        self._advance(run, now)
                        return self._batch(key, run, request_id, "operation_reused"), self._summary(run)
                except ContractError as error:
                    self._reject_node(run, node_id, error.diagnostic.error_code, now)
                    return self._batch(key, run, request_id, "operation_rejected"), self._summary(run)
            in_flight = sum(1 for k, r in view.records.items() if k.startswith("execution/")
                            for n in r["nodes"].values() if n["status"] == "CLAIMED")
            operator_in_flight = sum(1 for k, r in view.records.items() if k.startswith("execution/")
                                     for n in r["nodes"].values() if n["status"] == "CLAIMED" and n["operator"] == node["operator"])
            if in_flight >= self.max_claimed or operator_in_flight >= policy["concurrency"]:
                raise ContractError("EXECUTION_BACKPRESSURE", "Claim capacity is exhausted")
            node.update(status="CLAIMED", attempt_epoch=node["attempt_epoch"] + 1,
                        owner=asdict(self.coordinator.owner), worker_id=worker_id, input=data,
                        claimed_at=now, attempt_deadline_at=now + seconds(plan.policies[node_id]["timeout"]["attempt"]))
            if node.get("operation_id"):
                operations[node["operation_id"]] = {"protocol": OPERATION_PROTOCOL,
                    "operation_id": node["operation_id"], "request_digest": node["operation_request_digest"],
                    "status": "IN_PROGRESS", "created_at": now, "observed_at": now, "retain_until": None, "result": None,
                    "origin": {"execution_id": execution_id, "node_id": node_id, "release_id": run["release_id"],
                               "owner": node["owner"], "attempt_epoch": node["attempt_epoch"]}}
            run["status"] = "RUNNING"
            task = {"execution_id": execution_id, "node_id": node_id, "status": "CLAIMED",
                    "release_id": run["release_id"], "binding": run["binding"], "input": data,
                    "attempt_epoch": node["attempt_epoch"], "owner": node["owner"], "worker_id": worker_id,
                    "operator": plan.definition["nodes"][node_id]["operator"], "policy": run["policies"][node_id]}
            task.update(claimed_at=now, attempt_deadline_at=node["attempt_deadline_at"], deadline_at=run["deadline_at"])
            return self._batch(key, run, request_id, "node_claimed", operations=operations), task
        task = self._transact("claim", {"execution_id": execution_id, "node_id": node_id, "worker_id": worker_id},
                              decide, request_id, expected_revision)
        if task.get("owner") is not None and task["owner"] != asdict(self.coordinator.owner):
            raise PersistenceError("OWNER_FENCED", "Replayed claim belongs to a previous owner")
        if task.get("status") == "CLAIMED":
            run = self.query(execution_id)
            current = run["nodes"][node_id]
            if current["status"] != "CLAIMED" or current["attempt_epoch"] != task["attempt_epoch"]:
                raise PersistenceError("STALE_ATTEMPT", "Replayed claim is no longer active")
            if (run["stop"] is not None or current["cancel_requested"]
                    or self.clock_time() >= min(current["attempt_deadline_at"], run["deadline_at"])):
                raise ContractError("EXECUTION_STOPPED", "Replayed claim no longer permits business dispatch")
        return task

    def complete(self, task, *, status, data=None, error_code=None, resolution="main", request_id,
                 expected_revision=None):
        required = {"execution_id", "node_id", "release_id", "binding", "attempt_epoch", "owner", "worker_id"}
        if not isinstance(task, Mapping) or not required <= task.keys():
            raise ContractError("INVALID_COMMAND", "Completion requires a task identity")
        for field in ("execution_id", "node_id", "release_id", "worker_id"):
            _id(task[field], field)
        if type(task["attempt_epoch"]) is not int or task["attempt_epoch"] < 1:
            raise ContractError("INVALID_COMMAND", "Attempt epoch must be a positive integer")
        validate_value(task)
        validate_value(data)
        task, data = freeze(task), freeze(data)
        if type(status) is not str or status not in TERMINAL or resolution not in ("main", "fallback", "unhandled_exception"):
            raise ContractError("INVALID_COMMAND", "Invalid completion status or resolution")
        if error_code is not None:
            _id(error_code, "error_code")
        def decide(view):
            key, run = self._load(view, task["execution_id"])
            now = self._observe(run)
            node = run["nodes"].get(task["node_id"])
            if (node is None or node["status"] != "CLAIMED" or node["attempt_epoch"] != task["attempt_epoch"]
                    or digest(node["owner"]) != digest(task["owner"]) or node["owner"] != asdict(self.coordinator.owner)
                    or node["worker_id"] != task["worker_id"] or task["release_id"] != run["release_id"]
                    or digest(task["binding"]) != digest(run["binding"])):
                raise PersistenceError("STALE_ATTEMPT", "Completion does not belong to the active attempt")
            operation = self._owned_operation(view, run, task["node_id"])
            plan = self.release.flows[run["flow_id"]]
            operator = self.release.registry.operators[plan.definition["nodes"][task["node_id"]]["operator"]]
            final_status, code = status, error_code
            if resolution == "fallback" and operator.fallback is None:
                raise ContractError("INVALID_COMMAND", "Operator has no fallback")
            if resolution == "unhandled_exception" and (status != "FAILED" or error_code != "UNHANDLED_OPERATOR_EXCEPTION"):
                raise ContractError("INVALID_COMMAND", "Unhandled exceptions require the fatal failure outcome")
            if status == "SUCCEEDED" and error_code is not None:
                raise ContractError("INVALID_COMMAND", "Successful completion cannot carry an error")
            if resolution == "unhandled_exception":
                self._stop(run, _error(error_code))
            self._expire(run, now)
            if status == "SUCCEEDED":
                try:
                    validate(data, self.release.registry.schemas[operator.output_schema], "output.data")
                except ContractError:
                    final_status, code = "FAILED", "OUTPUT_CONTRACT_VIOLATION"
            if final_status != "SUCCEEDED":
                code = code or {"FAILED": "OPERATOR_REJECTED", "CANCELLED": "CANCELLED", "IN_DOUBT": "EFFECT_IN_DOUBT"}[final_status]
            node["status"] = final_status
            node["finished_at"] = now
            node["output"] = self._output(run, final_status, thaw(data) if final_status == "SUCCEEDED" else None,
                                           _error(code) if final_status != "SUCCEEDED" else None, resolution, task["node_id"])
            if final_status != "SUCCEEDED":
                self._stop(run, node["output"]["error"])
            self._advance(run, now)
            operations = {}
            if operation is not None:
                operation.update(observed_at=now, status="IN_DOUBT" if final_status == "IN_DOUBT" else
                                 "SUCCEEDED" if final_status == "SUCCEEDED" else "FAILED",
                    result={"status": final_status, "data": node["output"]["data"],
                            "error": node["output"]["error"], "resolution": resolution},
                    retain_until=None if final_status == "IN_DOUBT" else
                        now + seconds(run["policies"][task["node_id"]]["values"]["idempotency"]["result_retention"]))
                operations[node["operation_id"]] = operation
            return self._batch(key, run, request_id, "node_completed", operations=operations), self._summary(run)
        return self._transact("complete", {"task": task, "status": status, "data": data,
            "error_code": error_code, "resolution": resolution}, decide, request_id, expected_revision)

    def mark_in_doubt(self, execution_id, node_id, *, request_id, expected_revision):
        """Isolate a fenced, lost attempt. Never confirms effects or authorizes replay."""
        _id(node_id, "node_id")
        if expected_revision is None:
            raise ContractError("INVALID_RECOVERY_COMMAND", "Recovery requires an expected revision")
        if not self.protocol_test and not self.coordinator.store.capabilities.ownership_fencing:
            raise PersistenceError("CAPABILITY_REQUIRED", "Recovery requires declared ownership fencing")
        def decide(view):
            key, run = self._load(view, execution_id)
            now = self._observe(run)
            node = run["nodes"].get(node_id)
            if node is None or node["status"] != "CLAIMED":
                raise PersistenceError("STALE_ATTEMPT", "Only a claimed lost attempt can be isolated")
            if digest(node["owner"]) == digest(asdict(self.coordinator.owner)):
                raise PersistenceError("ATTEMPT_NOT_FENCED", "Current owner cannot declare its live attempt lost")
            operation = self._owned_operation(view, run, node_id)
            node.update(status="IN_DOUBT", finished_at=None, observed_ended_at=now,
                output=self._output(run, "IN_DOUBT", None, _error("ATTEMPT_LOST"), "recovery", node_id))
            self._stop(run, node["output"]["error"])
            self._advance(run, now)
            operations = {}
            if operation is not None:
                operation.update(status="IN_DOUBT", observed_at=now, result=None, retain_until=None)
                operations[node["operation_id"]] = operation
            return self._batch(key, run, request_id, "attempt_in_doubt", operations=operations), self._summary(run)
        return self._transact("mark_in_doubt", {"execution_id": execution_id, "node_id": node_id},
                              decide, request_id, expected_revision)

    def cancel(self, execution_id, *, request_id, expected_revision=None):
        def decide(view):
            key, run = self._load(view, execution_id)
            now = self._observe(run)
            if run["status"] not in TERMINAL:
                self._expire(run, now)
                self._stop(run, _error("CANCELLED"))
                self._advance(run, now)
            return self._batch(key, run, request_id, "cancellation_requested"), self._summary(run)
        return self._transact("cancel", {"execution_id": execution_id}, decide, request_id, expected_revision)
