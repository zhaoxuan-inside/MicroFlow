import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, PersistenceError
from microflow.idempotency import OperationScope, load_operation
from microflow.persistence import StorageBinding, StateBatch
from microflow.registry import Registry
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.values import digest, thaw
from microflow.worker import ScheduledRuntime
from tests.test_policy import DURABLE
from tests.test_timing import ManualClock


INPUT = {'type': 'object', 'properties': {'key': {'type': 'string'}, 'n': {'type': 'integer'}}, 'required': ['key', 'n']}
SCOPE = OperationScope('tenant-a', 'example', 'calculate', '1')


def calculate(input, output, context, metrix, debug, log):
    output.set('key', input['key'])
    output.set('n', input['n'] + 1)
    return True


def make(*, store=None, coordinator=None, clock=None, scope=SCOPE, version='1', main=calculate,
         output_kind='integer', retention='10s', key_path='input.key', max_claimed=16, attempt=None):
    registered = Registry()
    registered.register_schema('input', INPUT)
    registered.register_schema('output', {'type': 'object', 'properties': {
        'key': {'type': 'string'}, 'n': {'type': output_kind}}, 'required': ['key', 'n']})
    registered.register_operator(name='calculate', version=version, method=main,
        input_schema='input', output_schema='output')
    definition = {'id': 'business', 'input_schema': 'input', 'output_schema': 'output',
        'nodes': {'call': {'operator': 'calculate@' + version, 'inputs': {
            'key': {'from': 'flow.input.key', 'required': True}, 'n': {'from': 'flow.input.n', 'required': True}},
            'policy': {'idempotency': {'enabled': True, 'key_paths': [key_path], 'result_retention': retention}}}},
        'outputs': {'key': {'from': 'nodes.call.output.data.key'}, 'n': {'from': 'nodes.call.output.data.n'}}}
    if attempt is not None:
        definition['nodes']['call']['policy']['timeout'] = {'attempt': attempt}
    release = compile_release(registered, [definition], provider_capabilities=DURABLE)
    store = store or (coordinator.store if coordinator else MemoryStateStore())
    coordinator = coordinator or Coordinator(store)
    clock = clock or ManualClock()
    binding = StorageBinding('test', 'runtime-state', 'idempotency', store.load_recovery_view().binding_revision, digest({}))
    scopes = {} if scope is None else {'calculate@' + version: scope}
    return ExecutionCommands(coordinator, release, binding=binding, clock=clock, protocol_test=True,
                             operation_scopes=scopes, max_claimed=max_claimed), store, clock


def accept(commands, request, n=1, key='order'):
    return commands.accept('business', {'key': key, 'n': n}, request_id=request)['execution_id']


def claim(commands, execution, request):
    return commands.claim(execution, 'call', worker_id='worker', request_id=request)


def finish(commands, task, request='finish', status='SUCCEEDED'):
    return commands.complete(task, status=status, data={'key': 'order', 'n': 2} if status == 'SUCCEEDED' else None,
                             request_id=request)


class IdempotencyTests(unittest.TestCase):
    def test_same_key_in_progress_waits_without_second_claim_or_capacity(self):
        commands, store, _ = make(max_claimed=1)
        first = accept(commands, 'first')
        second = accept(commands, 'second')
        task = claim(commands, first, 'claim-first')
        waiting = claim(commands, second, 'claim-second')
        self.assertNotEqual(waiting['status'], 'CLAIMED')
        self.assertEqual(commands.query(second)['nodes']['call']['status'], 'WAITING_OPERATION')
        self.assertEqual(commands.query(second)['nodes']['call']['attempt_epoch'], 0)
        operation_id = commands.query(first)['nodes']['call']['operation_id']
        self.assertEqual(load_operation(store.load_recovery_view(), operation_id)['status'], 'IN_PROGRESS')
        with self.assertRaisesRegex(ContractError, 'OPERATION_PENDING'):
            commands.refresh_operations(second, request_id='refresh')
        finish(commands, task)
        self.assertEqual(commands.pending_operations(second)['call']['status'], 'SUCCEEDED')
        result = commands.refresh_operations(second, request_id='refresh')
        self.assertEqual(result['status'], 'SUCCEEDED')
        output = commands.query(second)['nodes']['call']['output']
        self.assertEqual(output['meta']['resolution'], 'idempotency')
        self.assertNotEqual(output['meta']['invocationId'], commands.query(first)['nodes']['call']['output']['meta']['invocationId'])
        self.assertEqual(output['data']['n'], 2)

    def test_concurrent_business_claims_have_one_owner(self):
        commands, store, _ = make()
        executions = [accept(commands, 'accept-' + str(i)) for i in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda item: claim(commands, item[1], 'claim-' + str(item[0])), enumerate(executions)))
        self.assertEqual(sum(outcome['status'] == 'CLAIMED' for outcome in outcomes), 1)
        self.assertEqual(sum(k.startswith('operation/') for k in store.load_recovery_view().records), 1)

    def test_different_input_same_key_is_conflict_not_business(self):
        commands, store, _ = make()
        first, second = accept(commands, 'first'), accept(commands, 'second', n=9)
        claim(commands, first, 'claim-first')
        result = claim(commands, second, 'claim-conflict')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['output']['error']['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(commands.query(second)['nodes']['call']['attempt_epoch'], 0)
        self.assertEqual(sum(k.startswith('operation/') for k in store.load_recovery_view().records), 1)

    def test_confirmed_failure_is_reused_without_retry(self):
        commands, _, _ = make()
        first = accept(commands, 'first')
        finish(commands, claim(commands, first, 'claim-first'), status='FAILED')
        second = accept(commands, 'second')
        result = claim(commands, second, 'claim-second')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['output']['error']['code'], 'OPERATOR_REJECTED')
        self.assertTrue(commands.query(second)['nodes']['call']['operation_replayed'])

    def test_new_release_reuses_original_business_result(self):
        commands, store, clock = make()
        original = accept(commands, 'first')
        finish(commands, claim(commands, original, 'claim-first'))
        newer, _, _ = make(coordinator=commands.coordinator, clock=clock, version='2')
        self.assertNotEqual(newer.release.release_id, commands.release.release_id)
        execution = accept(newer, 'new-release')
        result = claim(newer, execution, 'claim-new-release')
        self.assertEqual(result['status'], 'SUCCEEDED')
        node = newer.query(execution)['nodes']['call']
        self.assertEqual(node['attempt_epoch'], 0)
        self.assertEqual(node['output']['meta']['sourceReleaseId'], commands.release.release_id)
        self.assertEqual(sum(k.startswith('operation/') for k in store.load_recovery_view().records), 1)

    def test_semantic_version_change_conflicts_instead_of_new_identity(self):
        commands, _, clock = make()
        original = accept(commands, 'first')
        finish(commands, claim(commands, original, 'claim-first'))
        newer, _, _ = make(coordinator=commands.coordinator, clock=clock,
                            scope=replace(SCOPE, semantic_version='2'), version='2')
        result = claim(newer, accept(newer, 'new-release'), 'claim-new')
        self.assertEqual(result['output']['error']['code'], 'IDEMPOTENCY_CONFLICT')

    def test_incompatible_replay_schema_fails_without_executing(self):
        commands, _, clock = make()
        original = accept(commands, 'first')
        finish(commands, claim(commands, original, 'claim-first'))
        newer, _, _ = make(coordinator=commands.coordinator, clock=clock, version='2', output_kind='string')
        result = claim(newer, accept(newer, 'new'), 'claim-new')
        self.assertEqual(result['output']['error']['code'], 'IDEMPOTENCY_RESULT_INCOMPATIBLE')

    def test_tenant_isolation_and_typed_keys(self):
        first, first_digest = SCOPE.identify({'n': True}, ['input.n'])
        second, _ = SCOPE.identify({'n': 1}, ['input.n'])
        self.assertNotEqual(first, second)
        other, _ = replace(SCOPE, tenant='tenant-b').identify({'n': True}, ['input.n'])
        self.assertNotEqual(first, other)
        commands, store, clock = make()
        claim(commands, accept(commands, 'tenant-a'), 'claim-a')
        another, _, _ = make(coordinator=commands.coordinator, clock=clock, scope=replace(SCOPE, tenant='tenant-b'))
        self.assertEqual(claim(another, accept(another, 'tenant-b'), 'claim-b')['status'], 'CLAIMED')
        self.assertEqual(sum(k.startswith('operation/') for k in store.load_recovery_view().records), 2)

    def test_scope_is_pinned_at_admission(self):
        commands, store, clock = make()
        execution = accept(commands, 'first')
        rebound, _, _ = make(coordinator=commands.coordinator, clock=clock, scope=replace(SCOPE, tenant='tenant-b'))
        claim(rebound, execution, 'claim')
        expected, _ = SCOPE.identify({'key': 'order', 'n': 1}, ['input.key'])
        self.assertEqual(rebound.query(execution)['nodes']['call']['operation_id'], expected)

    def test_retention_expiry_reserves_business_identity(self):
        commands, store, clock = make(retention='2s')
        first = accept(commands, 'first')
        finish(commands, claim(commands, first, 'claim-first'))
        operation = commands.query(first)['nodes']['call']['operation_id']
        clock.now = 102
        result = claim(commands, accept(commands, 'second'), 'claim-second')
        self.assertEqual(result['output']['error']['code'], 'IDEMPOTENCY_RESULT_EXPIRED')
        self.assertIsNotNone(load_operation(store.load_recovery_view(), operation))

    def test_scope_and_key_validation_precede_business(self):
        commands, store, _ = make(scope=None)
        with self.assertRaisesRegex(ContractError, 'OPERATION_SCOPE_REQUIRED'):
            accept(commands, 'missing-scope')
        self.assertEqual(dict(store.load_recovery_view().records), {})
        commands, store, _ = make(key_path='context.options.traceId')
        with self.assertRaisesRegex(ContractError, 'INVALID_OPERATION_KEY'):
            accept(commands, 'wrong-key')
        commands, store, _ = make(key_path='input.absent')
        result = claim(commands, accept(commands, 'missing-key'), 'claim')
        self.assertEqual(result['output']['error']['code'], 'MISSING_OPERATION_KEY')
        self.assertFalse(any(k.startswith('operation/') for k in store.load_recovery_view().records))

    def test_lost_completion_ack_keeps_ledger_and_result_atomic(self):
        class LostAck(MemoryStateStore):
            def commit(self, batch, *args):
                receipt = super().commit(batch, *args)
                if any(k.startswith('operation/') and r['status'] == 'SUCCEEDED' for k, r in batch.puts.items()):
                    raise OSError('lost receipt')
                return receipt
        commands, store, _ = make(store=LostAck())
        execution = accept(commands, 'first')
        self.assertEqual(finish(commands, claim(commands, execution, 'claim'))['status'], 'SUCCEEDED')
        second = accept(commands, 'second')
        self.assertEqual(claim(commands, second, 'claim-second')['status'], 'SUCCEEDED')
        self.assertEqual(sum(k.startswith('operation/') for k in store.load_recovery_view().records), 1)

    def test_current_owner_cannot_mark_live_attempt_lost(self):
        commands, store, _ = make()
        execution = accept(commands, 'first')
        claim(commands, execution, 'claim')
        with self.assertRaisesRegex(PersistenceError, 'ATTEMPT_NOT_FENCED'):
            commands.mark_in_doubt(execution, 'call', request_id='lost', expected_revision=store.load_recovery_view().revision)
        self.assertEqual(commands.query(execution)['nodes']['call']['status'], 'CLAIMED')

    def test_fenced_lost_attempt_becomes_unknown_without_fake_end_time(self):
        commands, store, clock = make()
        execution = accept(commands, 'first')
        task = claim(commands, execution, 'claim')
        waiting = accept(commands, 'waiting')
        claim(commands, waiting, 'claim-waiting')
        commands.coordinator.close()
        restored, _, _ = make(store=store, clock=clock)
        revision = store.load_recovery_view().revision
        with self.assertRaisesRegex(PersistenceError, 'REVISION_CONFLICT'):
            restored.mark_in_doubt(execution, 'call', request_id='stale', expected_revision=revision - 1)
        result = restored.mark_in_doubt(execution, 'call', request_id='lost', expected_revision=revision)
        self.assertEqual(result['status'], 'IN_DOUBT')
        self.assertEqual(restored.mark_in_doubt(execution, 'call', request_id='lost', expected_revision=revision), result)
        node = restored.query(execution)['nodes']['call']
        self.assertIsNone(node['finished_at'])
        self.assertEqual(node['observed_ended_at'], clock.now)
        self.assertEqual(load_operation(store.load_recovery_view(), node['operation_id'])['status'], 'IN_DOUBT')
        with self.assertRaisesRegex(PersistenceError, 'STALE_ATTEMPT'):
            finish(restored, task, 'late')
        self.assertEqual(restored.refresh_operations(waiting, request_id='refresh')['status'], 'IN_DOUBT')
        another = accept(restored, 'another')
        self.assertEqual(claim(restored, another, 'claim-another')['status'], 'IN_DOUBT')

    def test_corrupt_operation_record_blocks_instead_of_new_claim(self):
        commands, store, _ = make()
        execution = accept(commands, 'first')
        claim(commands, execution, 'claim')
        operation = commands.query(execution)['nodes']['call']['operation_id']
        commands.coordinator.transact(lambda view: (StateBatch({'operation/' + operation: {'protocol': 'unknown'}}), None))
        second = accept(commands, 'second')
        with self.assertRaisesRegex(PersistenceError, 'INVALID_OPERATION_RECORD'):
            claim(commands, second, 'claim-second')
        self.assertEqual(commands.query(second)['nodes']['call']['attempt_epoch'], 0)

    def test_cancelling_duplicate_does_not_cancel_original_operation(self):
        commands, store, _ = make()
        first, second = accept(commands, 'first'), accept(commands, 'second')
        task = claim(commands, first, 'claim-first')
        claim(commands, second, 'claim-second')
        self.assertEqual(commands.cancel(second, request_id='cancel-second')['status'], 'CANCELLED')
        self.assertFalse(commands.query(first)['nodes']['call']['cancel_requested'])
        self.assertEqual(finish(commands, task)['status'], 'SUCCEEDED')
        self.assertEqual(commands.query(second)['status'], 'CANCELLED')

    def test_failed_completion_cannot_publish_ledger_success(self):
        class FailedCompletion(MemoryStateStore):
            def commit(self, batch, *args):
                if any(k.startswith('operation/') and r['status'] == 'SUCCEEDED' for k, r in batch.puts.items()):
                    raise OSError('storage unavailable')
                return super().commit(batch, *args)
        commands, store, _ = make(store=FailedCompletion())
        first = accept(commands, 'first')
        task = claim(commands, first, 'claim-first')
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_FAILED'):
            finish(commands, task)
        operation = commands.query(first)['nodes']['call']['operation_id']
        self.assertEqual(load_operation(store.load_recovery_view(), operation)['status'], 'IN_PROGRESS')
        second = accept(commands, 'second')
        claim(commands, second, 'claim-second')
        self.assertEqual(commands.query(second)['nodes']['call']['status'], 'WAITING_OPERATION')

    def test_capacity_failure_does_not_separate_operation_from_claim(self):
        commands, store, _ = make(store=MemoryStateStore(max_records=2))
        execution = accept(commands, 'first')
        with self.assertRaisesRegex(PersistenceError, 'COMMIT_FAILED'):
            claim(commands, execution, 'claim')
        self.assertEqual(commands.query(execution)['nodes']['call']['status'], 'READY')
        self.assertFalse(any(k.startswith('operation/') for k in store.load_recovery_view().records))

    def test_malformed_confirmed_result_cannot_be_replayed(self):
        commands, store, _ = make()
        first = accept(commands, 'first')
        finish(commands, claim(commands, first, 'claim-first'), status='FAILED')
        operation = commands.query(first)['nodes']['call']['operation_id']
        bad = load_operation(store.load_recovery_view(), operation)
        bad['result']['error'] = None
        commands.coordinator.transact(lambda view: (StateBatch({'operation/' + operation: bad}), None))
        second = accept(commands, 'second')
        with self.assertRaisesRegex(PersistenceError, 'INVALID_OPERATION_RECORD'):
            claim(commands, second, 'claim-second')

    def test_unknown_result_from_worker_is_reserved_without_result_expiry(self):
        commands, store, clock = make()
        first = accept(commands, 'first')
        finish(commands, claim(commands, first, 'claim-first'), status='IN_DOUBT')
        clock.now = 1000
        second = accept(commands, 'second')
        result = claim(commands, second, 'claim-second')
        self.assertEqual(result['status'], 'IN_DOUBT')
        operation = commands.query(first)['nodes']['call']['operation_id']
        self.assertIsNone(load_operation(store.load_recovery_view(), operation)['retain_until'])

    def test_duplicate_queue_timeout_does_not_expire_original_attempt(self):
        commands, store, clock = make(attempt='100s')
        first, second = accept(commands, 'first'), accept(commands, 'second')
        task = claim(commands, first, 'claim-first')
        claim(commands, second, 'claim-second')
        clock.now = 131
        self.assertEqual(commands.expire(second, request_id='expire')['output']['error']['code'], 'QUEUE_TIMEOUT')
        self.assertFalse(commands.query(first)['nodes']['call']['cancel_requested'])
        self.assertEqual(finish(commands, task)['status'], 'SUCCEEDED')
        self.assertEqual(commands.query(second)['status'], 'FAILED')

    def test_new_run_cannot_extend_retention_with_older_clock(self):
        commands, store, clock = make()
        first = accept(commands, 'first')
        task = claim(commands, first, 'claim-first')
        clock.now = 105
        finish(commands, task)
        clock.now = 101
        second = accept(commands, 'second')
        with self.assertRaisesRegex(PersistenceError, 'CLOCK_REGRESSION'):
            claim(commands, second, 'claim-second')
        self.assertEqual(commands.query(second)['nodes']['call']['attempt_epoch'], 0)


class IdempotentWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_roots_share_one_business_attempt(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def business(input, output, context, metrix, debug, log):
            calls.append(1)
            entered.set()
            await release.wait()
            output.set('key', input['key'])
            output.set('n', input['n'] + 1)
            return True
        commands, store, _ = make(main=business)
        async with ScheduledRuntime(commands, workers=2) as runtime:
            first = (await runtime.submit('business', {'key': 'order', 'n': 1}, request_id='first'))['execution_id']
            await asyncio.wait_for(entered.wait(), 1)
            second = (await runtime.submit('business', {'key': 'order', 'n': 1}, request_id='second'))['execution_id']
            try:
                for _ in range(100):
                    if commands.query(second)['nodes']['call']['status'] == 'WAITING_OPERATION':
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(commands.query(second)['nodes']['call']['status'], 'WAITING_OPERATION')
            finally:
                release.set()
            first_result, second_result = await asyncio.gather(runtime.wait(first, timeout=2), runtime.wait(second, timeout=2))
        self.assertEqual(calls, [1])
        self.assertEqual(first_result['output']['data'], second_result['output']['data'])
        self.assertNotEqual(first_result['output']['meta']['traceId'], second_result['output']['meta']['traceId'])
        self.assertEqual(sum(r['event'] == 'attempt_started' for r in runtime.records), 1)

    async def test_new_request_reuses_success_without_running_method_again(self):
        calls = []
        def business(input, output, context, metrix, debug, log):
            calls.append(1)
            return calculate(input, output, context, metrix, debug, log)
        commands, _, _ = make(main=business)
        async with ScheduledRuntime(commands) as runtime:
            first = await runtime.run('business', {'key': 'order', 'n': 1}, request_id='first', timeout=2)
            second = await runtime.run('business', {'key': 'order', 'n': 1}, request_id='second', timeout=2)
        self.assertEqual(calls, [1])
        self.assertEqual(second['nodes']['call']['output']['meta']['resolution'], 'idempotency')
        self.assertEqual(first['output']['data'], second['output']['data'])
