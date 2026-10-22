"""Authorized, evidence-bound reconciliation of unknown business outcomes.

Host callbacks verify identity and external facts. This service never executes,
retries, or resumes business work.
"""
from dataclasses import dataclass, replace
import math
from typing import Protocol
from .errors import ContractError, PersistenceError
from .idempotency import OperationScope, load_operation
from .policy import seconds
from .schema import validate
from .values import digest, freeze, thaw, validate_value


def _text(value):
    if type(value) is not str or not value or len(value) > 256:
        raise ContractError('INVALID_CONFIRMATION', 'Expected a bounded nonempty identifier')


@dataclass(frozen=True)
class ConfirmationEvidence:
    evidence_id: str
    source: str
    operation_id: str
    request_digest: str
    origin_digest: str
    status: str
    data: object = None

    def __post_init__(self):
        for value in (self.evidence_id, self.source, self.operation_id, self.request_digest, self.origin_digest):
            _text(value)
        if self.status not in ('SUCCEEDED', 'FAILED'):
            raise ContractError('INVALID_CONFIRMATION', 'Evidence must confirm success or failure, not absence or unknown')
        validate_value(self.data)
        if self.status == 'FAILED' and self.data is not None:
            raise ContractError('INVALID_CONFIRMATION', 'Confirmed failure cannot publish successful data')
        object.__setattr__(self, 'data', freeze(self.data))

    def value(self):
        return {'evidence_id': self.evidence_id, 'source': self.source, 'operation_id': self.operation_id,
                'request_digest': self.request_digest, 'origin_digest': self.origin_digest,
                'status': self.status, 'data': thaw(self.data)}


@dataclass(frozen=True)
class ConfirmationGrant:
    subject_id: str
    decision_id: str
    target_digest: str
    expires_at: float

    def __post_init__(self):
        for value in (self.subject_id, self.decision_id, self.target_digest):
            _text(value)
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at) or self.expires_at < 0:
            raise ContractError('INVALID_AUTHORIZATION_GRANT', 'Authorization expiry must be finite nonnegative seconds')


class ConfirmationAuthorizer(Protocol):
    def authorize(self, principal, target) -> ConfirmationGrant | None: ...


class ConfirmationVerifier(Protocol):
    # Only read/query existing facts; never perform or retry business effects.
    def verify(self, target, evidence: ConfirmationEvidence) -> bool: ...


class _VerificationRequired(Exception):
    pass


class ConfirmationService:
    def __init__(self, commands, *, authorizer, verifier):
        if not callable(getattr(authorizer, 'authorize', None)) or not callable(getattr(verifier, 'verify', None)):
            raise ContractError('CONFIRMATION_PROVIDER_REQUIRED', 'Confirmation requires authorization and evidence providers')
        self.commands, self.authorizer, self.verifier = commands, authorizer, verifier

    def _target(self, view, operation_id):
        record = load_operation(view, operation_id)
        if record is None:
            raise ContractError('UNKNOWN_OPERATION', 'Business operation does not exist')
        origin = record['origin']
        key, run = self.commands._load(view, origin['execution_id'])
        node = run['nodes'].get(origin['node_id'])
        if (node is None or node.get('operation_id') != operation_id
                or node.get('operation_request_digest') != record['request_digest']
                or digest(origin) != digest({'execution_id': run['execution_id'], 'node_id': origin['node_id'],
                    'release_id': run['release_id'], 'owner': node['owner'], 'attempt_epoch': node['attempt_epoch']})):
            raise PersistenceError('OPERATION_STATE_CONFLICT', 'Confirmation target does not match the original attempt')
        scope = run['policies'][origin['node_id']].get('operation_scope')
        if scope is None:
            raise PersistenceError('OPERATION_STATE_CONFLICT', 'Confirmation target has no pinned business scope')
        try:
            identity, request_digest = OperationScope(**scope).identify(node['input'],
                run['policies'][origin['node_id']]['values']['idempotency']['key_paths'])
        except (TypeError, KeyError, ContractError) as error:
            raise PersistenceError('OPERATION_STATE_CONFLICT', 'Original business identity cannot be reconstructed') from error
        if identity != operation_id or request_digest != record['request_digest']:
            raise PersistenceError('OPERATION_STATE_CONFLICT', 'Pinned business scope or original input changed')
        return key, run, node, record, scope

    def confirm(self, operation_id, evidence, *, principal, request_id, expected_revision):
        _text(operation_id)
        _text(request_id)
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(evidence, ConfirmationEvidence):
            raise ContractError('INVALID_CONFIRMATION', 'Confirmation requires evidence and an expected revision')
        commands = self.commands
        initial = self._target(commands.coordinator.view(), operation_id)
        _, _, _, original, scope = initial
        evidence_value = evidence.value()
        if (evidence.operation_id != operation_id or evidence.request_digest != original['request_digest']
                or evidence.origin_digest != digest(original['origin'])):
            raise ContractError('CONFIRMATION_TARGET_MISMATCH', 'Evidence belongs to another request or attempt')
        target = freeze({'action': 'operation.confirm', 'operation_id': operation_id,
            'request_digest': original['request_digest'], 'origin': original['origin'],
            'binding': thaw(initial[1]['binding']), 'scope': scope,
            'proposal_digest': digest(evidence_value), 'request_id': request_id,
            'expected_revision': expected_revision})
        try:
            grant = self.authorizer.authorize(principal, target)
        except Exception as error:
            raise ContractError('AUTHORIZATION_UNAVAILABLE', 'Cannot obtain confirmation authorization') from error
        if grant is None or grant is False:
            raise ContractError('CONFIRMATION_FORBIDDEN', 'Confirmation is not authorized')
        if not isinstance(grant, ConfirmationGrant) or grant.target_digest != digest(target):
            raise ContractError('INVALID_AUTHORIZATION_GRANT', 'Authorization is not bound to this confirmation')

        def authorized(now):
            if now >= grant.expires_at:
                raise ContractError('AUTHORIZATION_EXPIRED', 'Confirmation authorization expired')
        authorized(commands.clock_time())
        payload = {'operation_id': operation_id, 'evidence': evidence_value, 'subject_id': grant.subject_id}

        def current(view):
            result = self._target(view, operation_id)
            _, run, node, record, current_scope = result
            now = commands._observe(run)
            authorized(now)
            if now < record['observed_at']:
                raise PersistenceError('CLOCK_REGRESSION', 'Clock is behind the business operation')
            if (digest(record['origin']) != evidence.origin_digest or record['request_digest'] != evidence.request_digest
                    or digest(current_scope) != digest(scope)):
                raise ContractError('CONFIRMATION_TARGET_MISMATCH', 'Confirmation target changed')
            if record['status'] != 'IN_DOUBT' or node['status'] != 'IN_DOUBT':
                raise ContractError('OPERATION_NOT_IN_DOUBT', 'Only an unknown outcome may be confirmed')
            if run['stop'] is None:
                raise PersistenceError('OPERATION_STATE_CONFLICT', 'Unknown execution has no stop latch')
            plan = commands.release.flows[run['flow_id']]
            op = commands.release.registry.operators[plan.definition['nodes'][record['origin']['node_id']]['operator']]
            if evidence.status == 'SUCCEEDED':
                validate(evidence.data, commands.release.registry.schemas[op.output_schema], 'confirmation.data')
            return (*result, now)

        # Probe deduplication after fresh authorization. A known receipt can be
        # returned without re-querying external evidence; the probe never writes.
        def probe(view):
            current(view)
            raise _VerificationRequired()
        try:
            return commands._transact('confirm_operation', payload, probe, request_id, expected_revision)
        except _VerificationRequired:
            pass
        verification_target = freeze({**thaw(target), 'input': thaw(initial[2]['input'])})
        try:
            verified = self.verifier.verify(verification_target, evidence)
        except Exception as error:
            raise ContractError('EVIDENCE_VERIFICATION_UNAVAILABLE', 'Cannot verify confirmation evidence') from error
        if verified is not True:
            raise ContractError('EVIDENCE_UNVERIFIED', 'Evidence does not establish a confirmed outcome')

        def decide(view):
            key, run, node, record, _, now = current(view)
            name = record['origin']['node_id']
            error = None if evidence.status == 'SUCCEEDED' else {
                'code': 'CONFIRMED_OPERATION_FAILED', 'message': 'Confirmed business failure',
                'phase': 'confirmation', 'effectStatus': 'confirmed_failed'}
            node.update(status=evidence.status,
                output=commands._output(run, evidence.status, thaw(evidence.data), error, 'confirmation', name))
            audit_id = digest({'operation_id': operation_id, 'request_id': request_id, 'action': 'operation.confirm'})
            node['confirmation'] = {'audit_id': audit_id, 'confirmed_at': now, 'status': evidence.status}
            record.update(status=evidence.status, observed_at=now,
                result={'status': evidence.status, 'data': thaw(evidence.data), 'error': error, 'resolution': 'confirmation'},
                retain_until=now + seconds(run['policies'][name]['values']['idempotency']['result_retention']),
                confirmation={'audit_id': audit_id, 'evidence_digest': digest(evidence_value)})
            # Preserve the stop latch and skipped successors: confirmation is not
            # a command to resume the interrupted root or invent its end time.
            commands._advance(run, now)
            audit = {'protocol': 'microflow-confirmation-audit-v1', 'action': 'operation.confirm',
                'audit_id': audit_id, 'operation_id': operation_id, 'origin_digest': evidence.origin_digest,
                'request_digest': record['request_digest'], 'subject_id': grant.subject_id,
                'authorization_id': grant.decision_id, 'evidence_id': evidence.evidence_id,
                'authorization_target_digest': grant.target_digest, 'authorization_expires_at': grant.expires_at,
                'evidence_source': evidence.source, 'evidence_digest': digest(evidence_value),
                'expected_revision': expected_revision, 'confirmed_at': now, 'status': evidence.status}
            batch = commands._batch(key, run, request_id, 'operation_confirmed', operations={operation_id: record})
            batch = replace(batch, puts={**thaw(batch.puts), 'confirmation-audit/' + audit_id: audit})
            return batch, commands._summary(run)
        return commands._transact('confirm_operation', payload, decide, request_id, expected_revision)
