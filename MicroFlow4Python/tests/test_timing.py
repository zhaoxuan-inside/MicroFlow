import unittest
from unittest.mock import patch
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, PersistenceError
from microflow.persistence import StorageBinding, StateBatch
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.timing import BudgetClock
from microflow.values import digest, thaw
from tests.test_compiler import registry, flow, EPHEMERAL


class ManualClock:
    def __init__(self, now=100.0):
        self.now = now
    def __call__(self):
        return self.now


class BudgetTests(unittest.TestCase):
    def test_default_clock_uses_monotonic_elapsed_on_wall_rollback(self):
        with patch('microflow.timing.time.time', side_effect=[100.0, 90.0]), patch(
                'microflow.timing.time.monotonic', side_effect=[10.0, 12.0]):
            clock = BudgetClock()
            self.assertEqual(clock(), 102.0)

    def test_default_clock_retains_forward_adjustment_after_rollback(self):
        with patch('microflow.timing.time.time', side_effect=[100.0, 150.0, 90.0]), patch(
                'microflow.timing.time.monotonic', side_effect=[10.0, 11.0, 12.0]):
            clock = BudgetClock()
            self.assertEqual(clock(), 150.0)
            self.assertEqual(clock(), 151.0)

    def make(self, policies=None, store=None, **options):
        definition = flow()
        for name, policy in (policies or {}).items():
            definition['nodes'][name]['policy'] = policy
        release = compile_release(registry(), [definition], defaults=EPHEMERAL)
        self.clock = ManualClock()
        self.store = store or MemoryStateStore()
        binding = StorageBinding('test', 'runtime-state', 'timing', self.store.load_recovery_view().binding_revision, digest({}))
        self.commands = ExecutionCommands(Coordinator(self.store), release, binding=binding,
                                         protocol_test=True, clock=self.clock, **options)
        self.execution = self.commands.accept('example', {'n': 1}, request_id='accept')['execution_id']
        return self.commands

    def claim(self):
        return self.commands.claim(self.execution, 'first', worker_id='worker', request_id='claim')

    def test_queue_timeout_has_no_business_start_or_claim(self):
        commands = self.make({'first': {'timeout': {'queue': '5s'}}})
        self.clock.now = 105
        result = commands.expire(self.execution, request_id='expire')
        self.assertEqual(result['status'], 'FAILED')
        node = commands.query(self.execution)['nodes']['first']
        self.assertEqual(node['output']['error']['code'], 'QUEUE_TIMEOUT')
        self.assertEqual(node['output']['error']['effectStatus'], 'not_started')
        self.assertEqual(node['attempt_epoch'], 0)
        self.assertIsNone(node['claimed_at'])
        self.assertEqual(node['finished_at'], 105)
        self.assertEqual(commands.ready(self.execution), ())
        revision = self.store.load_recovery_view().revision
        self.assertEqual(commands.expire(self.execution, request_id='expire'), result)
        self.assertEqual(self.store.load_recovery_view().revision, revision)

    def test_early_timer_does_not_consume_request_identity(self):
        commands = self.make({'first': {'timeout': {'queue': '5s'}}})
        self.clock.now = 104
        with self.assertRaisesRegex(ContractError, 'BUDGET_NOT_EXPIRED'):
            commands.expire(self.execution, request_id='expire')
        self.assertEqual(self.store.get_commit('expire').status, 'NOT_COMMITTED')
        self.clock.now = 105
        self.assertEqual(commands.expire(self.execution, request_id='expire')['status'], 'FAILED')

    def test_claim_checks_due_budget_without_timer_tick(self):
        self.make({'first': {'timeout': {'queue': '5s'}}})
        self.clock.now = 105
        denied = self.claim()
        self.assertEqual(denied['status'], 'FAILED')
        self.assertEqual(denied['output']['error']['code'], 'QUEUE_TIMEOUT')
        self.assertNotIn('owner', denied)

    def test_dependency_wait_does_not_spend_queue_budget(self):
        commands = self.make({'second': {'timeout': {'queue': '2s'}}})
        task = self.claim()
        self.assertIsNone(commands.query(self.execution)['nodes']['second']['queue_deadline_at'])
        self.clock.now = 106
        commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='complete')
        state = commands.query(self.execution)
        self.assertEqual(state['nodes']['second']['ready_at'], 106)
        self.assertEqual(state['nodes']['second']['queue_deadline_at'], 108)
        self.clock.now = 107
        self.assertEqual(commands.claim(self.execution, 'second', worker_id='worker', request_id='second')['status'], 'CLAIMED')

    def test_attempt_timeout_retains_capacity_until_late_result(self):
        commands = self.make({'first': {'timeout': {'attempt': '3s'}}}, max_active=1)
        task = self.claim()
        self.clock.now = 103
        self.assertEqual(commands.expire(self.execution, request_id='expire')['status'], 'STOPPING')
        node = commands.query(self.execution)['nodes']['first']
        self.assertEqual(node['status'], 'CLAIMED')
        self.assertIsNone(node['finished_at'])
        self.assertTrue(node['cancel_requested'])
        with self.assertRaisesRegex(ContractError, 'EXECUTION_STOPPED'):
            self.claim()
        with self.assertRaisesRegex(ContractError, 'EXECUTION_BACKPRESSURE'):
            commands.accept('example', {'n': 1}, request_id='other')
        self.clock.now = 104
        result = commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='late')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['output']['error']['code'], 'ATTEMPT_TIMEOUT')
        self.assertEqual(commands.query(self.execution)['nodes']['first']['output']['data']['n'], 2)
        self.assertEqual(commands.query(self.execution)['nodes']['first']['finished_at'], 104)
        self.assertEqual(commands.ready(self.execution), ())
        self.assertEqual(commands.accept('example', {'n': 1}, request_id='other')['status'], 'ACCEPTED')

    def test_root_deadline_is_fixed_and_tighter_than_descendant(self):
        commands = self.make({'first': {'timeout': {'deadline': '20s'}}, 'second': {'timeout': {'deadline': '5s'}}})
        task = self.claim()
        self.assertEqual(task['deadline_at'], 105)
        self.clock.now = 106
        result = commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='complete')
        self.assertEqual(result['output']['error']['code'], 'DEADLINE_EXCEEDED')
        self.assertEqual(commands.query(self.execution)['deadline_at'], 105)
        self.assertEqual(commands.query(self.execution)['nodes']['second']['status'], 'SKIPPED')

    def test_late_success_is_rejected_even_without_expiry_pump(self):
        commands = self.make({'first': {'timeout': {'attempt': '3s'}}})
        task = self.claim()
        self.clock.now = 104
        result = commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='late')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['output']['error']['code'], 'ATTEMPT_TIMEOUT')
        self.assertEqual(commands.query(self.execution)['nodes']['first']['output']['data']['n'], 2)

    def test_expired_grant_is_not_reissued_without_timer_pump(self):
        commands = self.make({'first': {'timeout': {'attempt': '3s'}}})
        self.claim()
        self.clock.now = 104
        with self.assertRaisesRegex(ContractError, 'EXECUTION_STOPPED'):
            self.claim()
        self.assertEqual(commands.expire(self.execution, request_id='expire')['status'], 'STOPPING')

    def test_first_due_budget_and_root_tie_are_deterministic(self):
        commands = self.make({'first': {'timeout': {'queue': '5s', 'deadline': '10s'}}})
        self.clock.now = 115
        result = commands.expire(self.execution, request_id='expire')
        self.assertEqual(result['output']['error']['code'], 'QUEUE_TIMEOUT')
        commands = self.make({'first': {'timeout': {'queue': '5s', 'deadline': '5s'}}})
        self.clock.now = 105
        result = commands.expire(self.execution, request_id='expire')
        self.assertEqual(result['output']['error']['code'], 'DEADLINE_EXCEEDED')

    def test_clock_rollback_and_nonfinite_values_fail_before_mutation(self):
        commands = self.make()
        task = self.claim()
        revision = self.store.load_recovery_view().revision
        for now, code in ((99, 'CLOCK_REGRESSION'), (float('nan'), 'INVALID_CLOCK'), (True, 'INVALID_CLOCK')):
            self.clock.now = now
            with self.subTest(now=now), self.assertRaisesRegex(PersistenceError, code):
                commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='invalid')
            self.assertEqual(self.store.load_recovery_view().revision, revision)
        self.clock.now = 101
        self.assertEqual(commands.complete(task, status='SUCCEEDED', data={'n': 2}, request_id='valid')['status'], 'RUNNING')

    def test_cancel_does_not_hide_already_due_timeout(self):
        commands = self.make({'first': {'timeout': {'attempt': '3s'}}})
        self.claim()
        self.clock.now = 103
        result = commands.cancel(self.execution, request_id='cancel')
        self.assertEqual(result['status'], 'STOPPING')
        self.assertEqual(commands.query(self.execution)['stop']['code'], 'ATTEMPT_TIMEOUT')

    def test_legacy_state_requires_explicit_migration(self):
        commands = self.make()
        legacy = thaw(commands.query(self.execution))
        legacy['protocol'] = 'microflow-execution-state-v1'
        commands.coordinator.transact(lambda view: (StateBatch({'execution/' + self.execution: legacy}), None))
        with self.assertRaisesRegex(PersistenceError, 'UNSUPPORTED_EXECUTION_STATE'):
            commands.query(self.execution)

    def test_reconstructed_ready_work_keeps_original_deadlines(self):
        commands = self.make({'first': {'timeout': {'queue': '5s'}}})
        release, binding = commands.release, commands.binding
        commands.coordinator.close()
        self.clock.now = 106
        restored = ExecutionCommands(Coordinator(self.store), release, binding=binding,
                                     protocol_test=True, clock=self.clock)
        denied = restored.claim(self.execution, 'first', worker_id='new', request_id='new-claim')
        self.assertEqual(denied['output']['error']['code'], 'QUEUE_TIMEOUT')
        self.assertEqual(restored.query(self.execution)['accepted_at'], 100)
        self.assertEqual(restored.query(self.execution)['nodes']['first']['queue_deadline_at'], 105)

    def test_lost_timer_acknowledgment_does_not_duplicate_effects(self):
        class LostAck(MemoryStateStore):
            def commit(self, batch, *args):
                receipt = super().commit(batch, *args)
                if any(k.startswith('execution/') and r['stop'] is not None for k, r in batch.puts.items()):
                    raise OSError('lost acknowledgment')
                return receipt
        commands = self.make({'first': {'timeout': {'queue': '5s'}}}, store=LostAck())
        self.clock.now = 105
        result = commands.expire(self.execution, request_id='expire')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(commands.expire(self.execution, request_id='expire'), result)
        self.assertEqual(self.store.load_recovery_view().revision, 2)
