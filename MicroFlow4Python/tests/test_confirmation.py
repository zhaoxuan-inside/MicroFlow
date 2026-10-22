from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest
from microflow.confirmation import ConfirmationEvidence, ConfirmationGrant, ConfirmationService
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, PersistenceError
from microflow.idempotency import load_operation
from microflow.persistence import CommitReceipt, StateBatch
from microflow.testing import MemoryStateStore
from microflow.scheduling import ExecutionCommands
from microflow.values import digest
from microflow.values import thaw
from tests.test_idempotency import make, accept, claim, finish
from tests.test_policy import DURABLE


class Authorizer:
    def __init__(self, clock):
        self.clock = clock
        self.allowed = True
        self.subject = 'reviewer'
        self.calls = 0
        self.expiry = None
        self.target_override = None

    def authorize(self, principal, target):
        self.calls += 1
        if not self.allowed:
            return None
        return ConfirmationGrant(self.subject, 'grant-' + str(self.calls),
            self.target_override or digest(target), self.expiry if self.expiry is not None else self.clock.now + 10)


class Verifier:
    def __init__(self):
        self.calls = 0
        self.answer = True
        self.callback = None

    def verify(self, target, evidence):
        self.calls += 1
        if self.callback:
            return self.callback(target, evidence)
        return self.answer


class ConfirmationTests(unittest.TestCase):
    def setup_case(self, store=None, lost=False):
        self.commands, self.store, self.clock = make(store=store)
        self.execution = accept(self.commands, 'original')
        self.task = claim(self.commands, self.execution, 'claim')
        if lost:
            old = self.commands
            old.coordinator.close()
            self.commands, _, _ = make(coordinator=Coordinator(self.store), clock=self.clock)
            self.commands.mark_in_doubt(self.execution, 'call', request_id='lost',
                                       expected_revision=self.store.load_recovery_view().revision)
        else:
            finish(self.commands, self.task, status='IN_DOUBT')
        self.operation_id = self.commands.query(self.execution)['nodes']['call']['operation_id']
        record = load_operation(self.store.load_recovery_view(), self.operation_id)
        self.evidence = ConfirmationEvidence('proof-1', 'test-resource', self.operation_id,
            record['request_digest'], digest(record['origin']), 'SUCCEEDED', {'key': 'order', 'n': 2})
        self.authorizer, self.verifier = Authorizer(self.clock), Verifier()
        self.service = ConfirmationService(self.commands, authorizer=self.authorizer, verifier=self.verifier)
        self.revision = self.store.load_recovery_view().revision

    def confirm(self, evidence=None, request='confirm', revision=None):
        return self.service.confirm(self.operation_id, self.evidence if evidence is None else evidence,
            principal={'opaque_session': 'session-secret'}, request_id=request,
            expected_revision=self.revision if revision is None else revision)

    def test_success_confirms_business_without_resuming_original_root(self):
        self.setup_case(lost=True)
        result = self.confirm()
        self.assertEqual(result['status'], 'FAILED')
        state = self.commands.query(self.execution)
        node = state['nodes']['call']
        self.assertEqual(node['status'], 'SUCCEEDED')
        self.assertEqual(node['output']['data']['n'], 2)
        self.assertIsNone(node['finished_at'])
        self.assertEqual(state['stop']['code'], 'ATTEMPT_LOST')
        record = load_operation(self.store.load_recovery_view(), self.operation_id)
        self.assertEqual(record['status'], 'SUCCEEDED')
        self.assertEqual(record['result']['resolution'], 'confirmation')
        self.assertEqual(self.commands.ready(self.execution), ())
        audits = [v for k, v in self.store.load_recovery_view().records.items() if k.startswith('confirmation-audit/')]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]['subject_id'], 'reviewer')
        self.assertEqual(audits[0]['authorization_id'], 'grant-1')
        self.assertEqual(audits[0]['evidence_digest'], digest(self.evidence.value()))
        self.assertNotIn('session-secret', str(self.store.load_recovery_view().records))
        next_execution = accept(self.commands, 'new-logical-call')
        self.assertEqual(claim(self.commands, next_execution, 'new-claim')['status'], 'SUCCEEDED')
        self.assertEqual(self.commands.query(next_execution)['nodes']['call']['attempt_epoch'], 0)

    def test_confirmed_failure_is_reused_without_retry(self):
        self.setup_case()
        failure = replace(self.evidence, status='FAILED', data=None)
        self.confirm(failure)
        next_execution = accept(self.commands, 'new')
        result = claim(self.commands, next_execution, 'new-claim')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['output']['error']['code'], 'CONFIRMED_OPERATION_FAILED')
        self.assertEqual(self.commands.query(next_execution)['nodes']['call']['attempt_epoch'], 0)

    def test_replay_requires_fresh_authorization_but_no_second_verification(self):
        self.setup_case()
        result = self.confirm()
        revision = self.store.load_recovery_view().revision
        self.assertEqual(self.confirm(), result)
        self.assertEqual(self.authorizer.calls, 2)
        self.assertEqual(self.verifier.calls, 1)
        self.assertEqual(self.store.load_recovery_view().revision, revision)
        self.authorizer.allowed = False
        with self.assertRaisesRegex(ContractError, 'CONFIRMATION_FORBIDDEN'):
            self.confirm()
        self.assertEqual(self.verifier.calls, 1)

    def test_another_subject_cannot_reuse_confirmation_request_identity(self):
        self.setup_case()
        self.confirm()
        self.authorizer.subject = 'other-reviewer'
        with self.assertRaisesRegex(PersistenceError, 'REQUEST_CONFLICT'):
            self.confirm()

    def test_missing_providers_and_unbound_grants_are_rejected(self):
        self.setup_case()
        with self.assertRaisesRegex(ContractError, 'CONFIRMATION_PROVIDER_REQUIRED'):
            ConfirmationService(self.commands, authorizer=None, verifier=self.verifier)
        self.authorizer.target_override = 'another-target'
        with self.assertRaisesRegex(ContractError, 'INVALID_AUTHORIZATION_GRANT'):
            self.confirm()
        self.assertEqual(self.verifier.calls, 0)
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_denied_or_expired_authorization_never_queries_evidence(self):
        self.setup_case()
        self.authorizer.allowed = False
        with self.assertRaisesRegex(ContractError, 'CONFIRMATION_FORBIDDEN'):
            self.confirm()
        self.authorizer.allowed = True
        self.authorizer.expiry = self.clock.now
        with self.assertRaisesRegex(ContractError, 'AUTHORIZATION_EXPIRED'):
            self.confirm()
        self.assertEqual(self.verifier.calls, 0)
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_evidence_is_bound_to_original_identity_and_data_is_immutable(self):
        self.setup_case()
        with self.assertRaises(TypeError):
            self.evidence.data['n'] = 9
        for field in ('operation_id', 'request_digest', 'origin_digest'):
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, 'CONFIRMATION_TARGET_MISMATCH'):
                self.confirm(replace(self.evidence, **{field: 'wrong'}))
        self.assertEqual(self.verifier.calls, 0)
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_unverified_or_unavailable_evidence_keeps_unknown(self):
        self.setup_case()
        self.verifier.answer = False
        with self.assertRaisesRegex(ContractError, 'EVIDENCE_UNVERIFIED'):
            self.confirm()
        def failing(target, evidence):
            raise RuntimeError('private resource password')
        self.verifier.callback = failing
        with self.assertRaisesRegex(ContractError, 'EVIDENCE_VERIFICATION_UNAVAILABLE') as caught:
            self.confirm()
        self.assertNotIn('private resource password', str(caught.exception.diagnostic))
        self.assertEqual(load_operation(self.store.load_recovery_view(), self.operation_id)['status'], 'IN_DOUBT')

    def test_non_boolean_verification_cannot_authorize_confirmation(self):
        self.setup_case()
        self.verifier.answer = 1
        with self.assertRaisesRegex(ContractError, 'EVIDENCE_UNVERIFIED'):
            self.confirm()

    def test_stale_revision_and_bad_schema_are_rejected_before_verifier(self):
        self.setup_case()
        with self.assertRaisesRegex(PersistenceError, 'REVISION_CONFLICT'):
            self.confirm(revision=self.revision - 1)
        with self.assertRaisesRegex(ContractError, 'SCHEMA_VIOLATION'):
            self.confirm(replace(self.evidence, data={'key': 'order', 'n': 'secret-output'}))
        self.assertEqual(self.verifier.calls, 0)
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_authorization_expiring_during_verification_does_not_commit(self):
        self.setup_case()
        def slow(target, evidence):
            self.clock.now += 11
            return True
        self.verifier.callback = slow
        with self.assertRaisesRegex(ContractError, 'AUTHORIZATION_EXPIRED'):
            self.confirm()
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_revision_change_during_verification_rejects_stale_commit(self):
        self.setup_case()
        def change(target, evidence):
            accept(self.commands, 'unrelated')
            return True
        self.verifier.callback = change
        with self.assertRaisesRegex(PersistenceError, 'REVISION_CONFLICT'):
            self.confirm()
        self.assertEqual(load_operation(self.store.load_recovery_view(), self.operation_id)['status'], 'IN_DOUBT')
        self.assertFalse(any(k.startswith('confirmation-audit/') for k in self.store.load_recovery_view().records))

    def test_verification_runs_outside_coordinator_lock(self):
        self.setup_case()
        def query(target, evidence):
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(self.commands.coordinator.transact, lambda view: (None, True)).result(timeout=1))
            return True
        self.verifier.callback = query
        self.confirm()
        self.assertEqual(self.verifier.calls, 1)

    def test_capacity_failure_never_separates_audit_ledger_and_node(self):
        self.setup_case(store=MemoryStateStore(max_records=6))
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_FAILED'):
            self.confirm()
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)
        self.assertEqual(load_operation(self.store.load_recovery_view(), self.operation_id)['status'], 'IN_DOUBT')
        self.assertEqual(self.commands.query(self.execution)['nodes']['call']['status'], 'IN_DOUBT')
        self.assertFalse(any(k.startswith('confirmation-audit/') for k in self.store.load_recovery_view().records))

    def test_lost_confirmation_acknowledgment_produces_one_audit(self):
        class LostAck(MemoryStateStore):
            def commit(self, batch, *args):
                receipt = super().commit(batch, *args)
                if any(k.startswith('confirmation-audit/') for k in batch.puts):
                    raise OSError('lost acknowledgment')
                return receipt
        self.setup_case(store=LostAck())
        result = self.confirm()
        self.assertEqual(self.confirm(), result)
        self.assertEqual(sum(k.startswith('confirmation-audit/') for k in self.store.load_recovery_view().records), 1)
        self.assertEqual(self.verifier.calls, 1)

    def test_confirmed_operation_cannot_be_overwritten_with_new_command(self):
        self.setup_case()
        self.confirm()
        with self.assertRaisesRegex(ContractError, 'OPERATION_NOT_IN_DOUBT'):
            self.confirm(request='overwrite', revision=self.store.load_recovery_view().revision)
        self.assertEqual(self.verifier.calls, 1)

    def test_confirmation_requires_origin_release_and_explicit_revision(self):
        self.setup_case()
        newer, _, _ = make(coordinator=self.commands.coordinator, clock=self.clock, version='2')
        service = ConfirmationService(newer, authorizer=self.authorizer, verifier=self.verifier)
        with self.assertRaisesRegex(PersistenceError, 'EXECUTION_BINDING_MISMATCH'):
            service.confirm(self.operation_id, self.evidence, principal=None, request_id='wrong-release', expected_revision=self.revision)
        with self.assertRaisesRegex(ContractError, 'INVALID_CONFIRMATION'):
            self.service.confirm(self.operation_id, self.evidence, principal=None, request_id='missing-revision', expected_revision=None)

    def test_absence_or_unknown_is_not_a_confirmed_failure(self):
        self.setup_case()
        for status in ('UNKNOWN', 'NOT_FOUND', 'CANCELLED'):
            with self.subTest(status=status), self.assertRaisesRegex(ContractError, 'INVALID_CONFIRMATION'):
                replace(self.evidence, status=status)

    def test_authorization_provider_outage_does_not_fall_back_to_allow(self):
        self.setup_case()
        def unavailable(principal, target):
            raise RuntimeError('private credential')
        self.authorizer.authorize = unavailable
        with self.assertRaisesRegex(ContractError, 'AUTHORIZATION_UNAVAILABLE') as caught:
            self.confirm()
        self.assertNotIn('private credential', str(caught.exception.diagnostic))
        self.assertEqual(self.verifier.calls, 0)
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_clock_rollback_during_verification_cannot_commit(self):
        self.setup_case()
        def rollback(target, evidence):
            self.clock.now -= 1
            return True
        self.verifier.callback = rollback
        with self.assertRaisesRegex(PersistenceError, 'CLOCK_REGRESSION'):
            self.confirm()
        self.assertEqual(self.store.load_recovery_view().revision, self.revision)

    def test_pinned_scope_corruption_is_not_a_new_confirmation_target(self):
        self.setup_case()
        run = thaw(self.commands.query(self.execution))
        run['policies']['call']['operation_scope']['tenant'] = 'another-tenant'
        self.commands.coordinator.transact(lambda view: (StateBatch({'execution/' + self.execution: run}), None))
        with self.assertRaisesRegex(PersistenceError, 'OPERATION_STATE_CONFLICT'):
            self.confirm(revision=self.store.load_recovery_view().revision)
        self.assertEqual(self.verifier.calls, 0)

    def test_unknown_commit_reuses_original_request_after_resolution(self):
        class UnknownAck(MemoryStateStore):
            uncertain = False
            def commit(self, batch, *args):
                receipt = super().commit(batch, *args)
                if any(k.startswith('confirmation-audit/') for k in batch.puts):
                    self.uncertain = True
                    return CommitReceipt('UNKNOWN', args[1])
                return receipt
            def get_commit(self, request_id):
                return CommitReceipt('UNKNOWN', request_id) if self.uncertain else super().get_commit(request_id)
        self.setup_case(store=UnknownAck())
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_IN_DOUBT'):
            self.confirm()
        self.assertEqual(self.verifier.calls, 1)
        self.assertEqual(load_operation(self.store.load_recovery_view(), self.operation_id)['status'], 'SUCCEEDED')
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_IN_DOUBT'):
            self.confirm()
        self.store.uncertain = False
        self.assertEqual(self.confirm()['status'], 'FAILED')
        self.assertEqual(self.verifier.calls, 1)
        self.assertEqual(sum(k.startswith('confirmation-audit/') for k in self.store.load_recovery_view().records), 1)

    def test_confirmation_never_reactivates_skipped_successors(self):
        original, store, clock = make()
        definition = thaw(original.release.flows['business'].definition)
        definition['nodes']['after'] = {'operator': 'calculate@1', 'depends_on': ['call'], 'inputs': {
            'key': {'from': 'nodes.call.output.data.key'}, 'n': {'from': 'nodes.call.output.data.n'}}}
        release = compile_release(original.release.registry, [definition], provider_capabilities=DURABLE)
        commands = ExecutionCommands(original.coordinator, release, binding=original.binding, clock=clock,
            protocol_test=True, operation_scopes=original.operation_scopes)
        execution = accept(commands, 'original')
        finish(commands, claim(commands, execution, 'claim'), status='IN_DOUBT')
        operation_id = commands.query(execution)['nodes']['call']['operation_id']
        record = load_operation(store.load_recovery_view(), operation_id)
        evidence = ConfirmationEvidence('proof', 'test-resource', operation_id, record['request_digest'],
            digest(record['origin']), 'SUCCEEDED', {'key': 'order', 'n': 2})
        service = ConfirmationService(commands, authorizer=Authorizer(clock), verifier=Verifier())
        result = service.confirm(operation_id, evidence, principal=None, request_id='confirm',
                                 expected_revision=store.load_recovery_view().revision)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(commands.query(execution)['nodes']['after']['status'], 'SKIPPED')
        self.assertEqual(commands.ready(execution), ())
