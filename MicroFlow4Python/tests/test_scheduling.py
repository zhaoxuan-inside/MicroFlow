import concurrent.futures
from dataclasses import replace
import unittest
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, PersistenceError
from microflow.persistence import StorageBinding, CommitReceipt
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.values import digest, thaw
from tests.test_compiler import registry, flow, EPHEMERAL
from microflow.compiler import compile_release


class SchedulingTests(unittest.TestCase):
    def test_fenced_non_idempotent_claim_is_isolated_without_replay(self):
        commands, store = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        release, binding = commands.release, commands.binding
        commands.coordinator.close()
        restored = ExecutionCommands(Coordinator(store), release, binding=binding, protocol_test=True)
        result = restored.mark_in_doubt(execution, 'first', request_id='lost',
                                        expected_revision=store.load_recovery_view().revision)
        self.assertEqual(result['status'], 'IN_DOUBT')
        self.assertIsNone(restored.query(execution)['nodes']['first']['finished_at'])
        with self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
            restored.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='late')

    def make(self, definition=None, store=None, **options):
        store = store or MemoryStateStore()
        release = compile_release(registry(), [definition or flow()], defaults=EPHEMERAL)
        binding = StorageBinding('test', 'runtime-state', 'isolated', store.load_recovery_view().binding_revision, digest({}))
        commands = ExecutionCommands(Coordinator(store), release, binding=binding, protocol_test=True, **options)
        return commands, store

    def accept(self, commands, request='accept'):
        return commands.accept('example', {'n': 1}, request_id=request)['execution_id']

    def claim(self, commands, execution, node='first', request='claim'):
        return commands.claim(execution, node, worker_id='worker', request_id=request)

    def fork(self):
        definition = flow()
        definition['nodes']['peer'] = {'operator': 'increment@1', 'inputs': {'n': {'from': 'flow.input.n'}}}
        definition['nodes']['after'] = {'operator': 'increment@1', 'depends_on': ['peer'],
                                       'inputs': {'n': {'from': 'nodes.peer.output.data.n'}}}
        return definition

    def test_admission_is_distinct_from_completion_and_replays_original(self):
        commands, store = self.make()
        accepted = commands.accept('example', {'n': 1}, request_id='accept')
        execution = accepted['execution_id']
        self.assertEqual(accepted['status'], 'ACCEPTED')
        self.assertEqual(commands.query(execution)['status'], 'ACCEPTED')
        self.assertEqual(commands.ready(execution), ('first',))
        self.assertEqual(accepted['durability'], 'ephemeral')
        task = self.claim(commands, execution)
        self.assertEqual(task['input'], {'n': 1})
        self.assertEqual(commands.accept('example', {'n': 1}, request_id='accept'), accepted)
        with self.assertRaisesRegex(PersistenceError, 'REQUEST_CONFLICT'):
            commands.accept('example', {'n': 2}, request_id='accept')
        events = [r for k, r in store.load_recovery_view().records.items() if k.startswith('event-intent/')]
        self.assertEqual(len(events), 2)
        self.assertEqual([event['sequence'] for event in events], [1, 2])
        self.assertTrue(all(event['protocol'] == 'microflow-event-v1' for event in events))
        self.assertTrue(all(event['content_digest'] for event in events))

    def test_completion_and_successor_readiness_commit_together(self):
        commands, store = self.make()
        execution = self.accept(commands)
        first = self.claim(commands, execution)
        outcome = commands.complete(first, status='SUCCEEDED', data={'n': 2}, request_id='finish-first')
        self.assertEqual(outcome['status'], 'RUNNING')
        self.assertEqual(commands.ready(execution), ('second',))
        state = commands.query(execution)
        self.assertEqual(state['nodes']['first']['output']['data']['n'], 2)
        second = self.claim(commands, execution, 'second', 'claim-second')
        self.assertEqual(second['input'], {'n': 2})
        result = commands.complete(second, status='SUCCEEDED', data={'n': 3}, request_id='finish-second')
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(result['output']['data'], {'n': 3})
        self.assertEqual(commands.ready(execution), ())
        self.assertEqual(commands.complete(first, status='SUCCEEDED', data={'n': 2}, request_id='finish-first'), outcome)
        self.assertNotEqual(state['nodes']['first']['output']['meta']['invocationId'], execution)

    def test_dependency_cannot_be_claimed_from_acceptance(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        with self.assertRaisesRegex(ContractError, 'NODE_NOT_READY'):
            self.claim(commands, execution, 'second')

    def test_latch_waits_for_claimed_peer_and_late_success_cannot_advance(self):
        commands, _ = self.make(self.fork())
        execution = self.accept(commands)
        first = self.claim(commands, execution)
        peer = self.claim(commands, execution, 'peer', 'claim-peer')
        stopped = commands.complete(first, status='FAILED', error_code='UNHANDLED_OPERATOR_EXCEPTION',
                                    resolution='unhandled_exception', request_id='failure')
        self.assertEqual(stopped['status'], 'STOPPING')
        state = commands.query(execution)
        self.assertTrue(state['nodes']['peer']['cancel_requested'])
        self.assertEqual(state['nodes']['after']['status'], 'SKIPPED')
        with self.assertRaisesRegex(ContractError, 'EXECUTION_STOPPED'):
            self.claim(commands, execution, 'after', 'forbidden')
        done = commands.complete(peer, status='SUCCEEDED', data={'n': 2}, request_id='late')
        self.assertEqual(done['status'], 'FAILED')
        self.assertEqual(done['output']['error']['code'], 'UNHANDLED_OPERATOR_EXCEPTION')
        self.assertEqual(commands.query(execution)['nodes']['peer']['output']['data']['n'], 2)
        self.assertEqual(commands.ready(execution), ())

    def test_cancel_request_is_not_cancelled_while_work_is_claimed(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        self.assertEqual(commands.cancel(execution, request_id='cancel')['status'], 'STOPPING')
        result = commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='late')
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertIsNone(result['output']['data'])
        self.assertEqual(commands.cancel(execution, request_id='again'), result)

    def test_unknown_effect_blocks_success_and_stops_dependents(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        result = commands.complete(task, status='IN_DOUBT', request_id='unknown')
        self.assertEqual(result['status'], 'IN_DOUBT')
        self.assertEqual(commands.ready(execution), ())
        with self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
            commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='overwrite')

    def test_output_contract_failure_is_atomic(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        result = commands.complete(task, status='SUCCEEDED', data={'n': 'secret-value'}, request_id='bad-output')
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('secret-value', str(commands.query(execution)))
        self.assertEqual(result['output']['error']['code'], 'OUTPUT_CONTRACT_VIOLATION')

    def test_input_mapping_failure_never_grants_execution(self):
        definition = flow()
        definition['nodes']['first']['inputs']['n']['from'] = 'context.options.absent'
        commands, _ = self.make(definition)
        execution = self.accept(commands)
        result = self.claim(commands, execution)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(commands.query(execution)['nodes']['first']['attempt_epoch'], 0)

    def test_stale_identity_and_malformed_completion(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        for field, value in (('attempt_epoch', 2), ('worker_id', 'other'), ('release_id', 'other'), ('owner', {}),
                             ('owner', {**task['owner'], 'generation': True})):
            bad = {**task, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
                commands.complete(bad, status='SUCCEEDED', data={'n': 2}, request_id='bad-' + field)
        for bad in (None, {}, {**task, 'attempt_epoch': True}):
            with self.assertRaises(ContractError):
                commands.complete(bad, status='SUCCEEDED', request_id='malformed')
        self.assertEqual(commands.query(execution)['nodes']['first']['status'], 'CLAIMED')

    def test_reconstructs_ready_tasks_but_does_not_reassign_claimed_work(self):
        commands, store = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        release, binding = commands.release, commands.binding
        commands.coordinator.close()
        restored = ExecutionCommands(Coordinator(store), release, binding=binding, protocol_test=True)
        self.assertEqual(restored.ready(execution), ())
        with self.assertRaisesRegex(PersistenceError, 'OWNER_FENCED'):
            self.claim(restored, execution)
        with self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
            restored.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='old-worker')
        self.assertEqual(restored.query(execution)['nodes']['first']['status'], 'CLAIMED')

    def test_capacity_limits_and_expected_revision(self):
        commands, store = self.make(self.fork(), max_active=1, max_claimed=1)
        execution = self.accept(commands)
        with self.assertRaisesRegex(ContractError, 'EXECUTION_BACKPRESSURE'):
            self.accept(commands, 'another')
        first = self.claim(commands, execution)
        with self.assertRaisesRegex(ContractError, 'EXECUTION_BACKPRESSURE'):
            self.claim(commands, execution, 'peer', 'peer')
        with self.assertRaisesRegex(PersistenceError, 'REVISION_CONFLICT'):
            commands.complete(first, status='SUCCEEDED', data={'n': 2}, request_id='stale-rev', expected_revision=0)
        commands.complete(first, status='SUCCEEDED', data={'n': 2}, request_id='finish')
        self.assertEqual(self.claim(commands, execution, 'peer', 'peer')['status'], 'CLAIMED')

    def test_claim_race_only_one_request_gets_new_attempt(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        def claim(index):
            try:
                return self.claim(commands, execution, request='claim-' + str(index))['status']
            except ContractError as error:
                return error.diagnostic.error_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(claim, range(8)))
        self.assertEqual(outcomes.count('CLAIMED'), 1)
        self.assertEqual(outcomes.count('NODE_NOT_READY'), 7)

    def test_binding_release_and_production_capability_guards(self):
        commands, _ = self.make()
        with self.assertRaisesRegex(PersistenceError, 'CAPABILITY_REQUIRED'):
            ExecutionCommands(commands.coordinator, commands.release, binding=commands.binding)
        with self.assertRaisesRegex(PersistenceError, 'BINDING_MISMATCH'):
            ExecutionCommands(commands.coordinator, commands.release,
                              binding=replace(commands.binding, binding_revision='other'), protocol_test=True)
        execution = self.accept(commands)
        wrong = replace(commands.release, release_id='different')
        with self.assertRaises(ContractError):
            ExecutionCommands(commands.coordinator, wrong, binding=commands.binding, protocol_test=True)
        changed_binding = replace(commands.binding, namespace='other')
        other = ExecutionCommands(commands.coordinator, commands.release, binding=changed_binding, protocol_test=True)
        with self.assertRaisesRegex(PersistenceError, 'EXECUTION_BINDING_MISMATCH'):
            other.query(execution)

    def test_no_acceptance_or_dispatch_on_unknown_commit(self):
        class Unknown(MemoryStateStore):
            uncertain = True
            def commit(self, batch, expected_revision, request_id, owner_token):
                if self.uncertain:
                    return CommitReceipt('UNKNOWN', request_id)
                return super().commit(batch, expected_revision, request_id, owner_token)
            def get_commit(self, request_id):
                return CommitReceipt('UNKNOWN', request_id) if self.uncertain else super().get_commit(request_id)
        store = Unknown()
        commands, _ = self.make(store=store)
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_IN_DOUBT'):
            self.accept(commands)
        self.assertEqual(dict(store.load_recovery_view().records), {})
        store.uncertain = False
        execution = self.accept(commands)
        self.assertEqual(commands.ready(execution), ('first',))

    def test_lost_acknowledgment_retains_one_admission_and_intent(self):
        class LostAck(MemoryStateStore):
            def commit(self, *args):
                super().commit(*args)
                raise OSError('connection lost')
        commands, store = self.make(store=LostAck())
        execution = self.accept(commands)
        self.assertEqual(self.accept(commands), execution)
        self.assertEqual(len(store.load_recovery_view().records), 2)

    def test_unknown_after_commit_blocks_claim_until_original_request_resolves(self):
        class UnknownAck(MemoryStateStore):
            fail_next = True
            uncertain = False
            def commit(self, *args):
                receipt = super().commit(*args)
                if self.fail_next:
                    self.fail_next = False
                    self.uncertain = True
                    return CommitReceipt('UNKNOWN', args[2])
                return receipt
            def get_commit(self, request_id):
                return CommitReceipt('UNKNOWN', request_id) if self.uncertain else super().get_commit(request_id)
        store = UnknownAck()
        commands, _ = self.make(store=store)
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_IN_DOUBT'):
            self.accept(commands)
        records = store.load_recovery_view().records
        execution = next(r['execution_id'] for k, r in records.items() if k.startswith('execution/'))
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_IN_DOUBT'):
            self.claim(commands, execution)
        self.assertEqual(store.load_recovery_view().revision, 1)
        store.uncertain = False
        self.assertEqual(self.accept(commands), execution)
        self.assertEqual(self.claim(commands, execution)['status'], 'CLAIMED')
        self.assertEqual(store.load_recovery_view().revision, 2)

    def test_completed_claim_replay_cannot_offer_work_again(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        self.assertEqual(self.claim(commands, execution), task)
        commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='finish')
        with self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
            self.claim(commands, execution)

    def test_cancel_unclaimed_releases_admission_budget(self):
        commands, _ = self.make(max_active=1)
        execution = self.accept(commands)
        cancelled = commands.cancel(execution, request_id='cancel')
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertEqual(commands.query(execution)['nodes']['first']['status'], 'SKIPPED')
        self.assertNotEqual(self.accept(commands, 'new-admission'), execution)

    def test_inconsistent_worker_outcomes_are_rejected(self):
        commands, _ = self.make()
        execution = self.accept(commands)
        task = self.claim(commands, execution)
        for options in ({'status': 'SUCCEEDED', 'error_code': 'ERROR'},
                        {'status': 'SUCCEEDED', 'resolution': 'unhandled_exception'},
                        {'status': 'FAILED', 'resolution': 'fallback'}, {'status': []}):
            with self.subTest(options=options), self.assertRaises(ContractError):
                commands.complete(task, request_id='invalid', **options)
        self.assertEqual(commands.query(execution)['nodes']['first']['status'], 'CLAIMED')

    def test_empty_flow_has_confirmed_result_without_worker(self):
        definition = flow()
        definition['nodes'] = {}
        definition['outputs'] = {'n': {'from': 'flow.input.n'}}
        commands, _ = self.make(definition)
        accepted = commands.accept('example', {'n': 1}, request_id='accept')
        self.assertEqual(accepted['status'], 'ACCEPTED')
        self.assertEqual(accepted['execution_status'], 'SUCCEEDED')
        self.assertEqual(commands.query(accepted['execution_id'])['output']['data']['n'], 1)

    def test_node_budget_and_operator_concurrency(self):
        commands, store = self.make(max_nodes=1)
        with self.assertRaisesRegex(ContractError, 'EXECUTION_BUDGET'):
            self.accept(commands)
        self.assertEqual(dict(store.load_recovery_view().records), {})
        definition = self.fork()
        definition['nodes']['peer']['policy'] = {'concurrency': 1}
        commands, _ = self.make(definition)
        execution = self.accept(commands)
        self.claim(commands, execution)
        with self.assertRaisesRegex(ContractError, 'EXECUTION_BACKPRESSURE'):
            self.claim(commands, execution, 'peer', 'peer')

    def test_write_operator_requires_later_confirmation_protocol(self):
        registered = registry()
        registered.register_operator(name='write', version='1', method=registered.operators['increment@1'].method,
            input_schema='ints', output_schema='ints', capabilities={'effect': 'write', 'idempotency_support': 'natural'})
        definition = flow()
        definition['nodes']['first']['operator'] = 'write@1'
        release = compile_release(registered, [definition], defaults=EPHEMERAL)
        commands, store = self.make()
        commands = ExecutionCommands(commands.coordinator, release, binding=commands.binding, protocol_test=True)
        with self.assertRaisesRegex(ContractError, 'UNSUPPORTED_SCHEDULED_EFFECT'):
            self.accept(commands)
        self.assertEqual(dict(store.load_recovery_view().records), {})

    def test_unsupported_nodes_and_invalid_input_rejected_before_admission(self):
        definition = flow()
        definition['nodes']['first']['condition'] = {'exists': 'flow.input.n'}
        commands, store = self.make(definition)
        with self.assertRaisesRegex(ContractError, 'UNSUPPORTED_SCHEDULED_NODE'):
            self.accept(commands)
        self.assertEqual(dict(store.load_recovery_view().records), {})
        commands, store = self.make()
        with self.assertRaises(ContractError):
            commands.accept('example', {'n': 'bad'}, request_id='bad')
        self.assertEqual(dict(store.load_recovery_view().records), {})
