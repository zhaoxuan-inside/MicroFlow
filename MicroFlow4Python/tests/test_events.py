import unittest
from microflow.events import EventIntent, MemoryEventStore
from microflow.errors import ContractError, PersistenceError


def event(event_id='e1', sequence=1, payload=None, recorded=2):
    return EventIntent(event_id, 'order.created', '1', 'order-1', sequence,
                       {'order': 3} if payload is None else payload,
                       'exec-1', 'release-1', 1, recorded)


class EventTests(unittest.TestCase):
    def test_append_is_idempotent_and_acknowledge_is_explicit(self):
        store = MemoryEventStore()
        first = store.append(event())
        self.assertEqual(store.append(event()), first)
        self.assertEqual(store.status('e1'), 'PENDING')
        store.acknowledge('e1', first.content_digest)
        self.assertEqual(store.status('e1'), 'DELIVERED')
        self.assertEqual(store.pending(), ())

    def test_id_conflict_and_contiguous_aggregate_sequence(self):
        store = MemoryEventStore()
        store.append(event())
        with self.assertRaisesRegex(PersistenceError, 'EVENT_ID_CONFLICT'):
            store.append(event(payload={'other': 1}))
        with self.assertRaisesRegex(PersistenceError, 'EVENT_SEQUENCE_CONFLICT'):
            store.append(event('e3', 3))
        store.append(event('e2', 2))

    def test_ordering_is_per_aggregate_and_capacity_is_atomic(self):
        store = MemoryEventStore(max_events=1)
        store.append(event())
        other = EventIntent('x1', 'x', '1', 'other', 1, {}, 'exec-1', 'release-1', 1, 1)
        with self.assertRaisesRegex(PersistenceError, 'EVENT_CAPACITY'):
            store.append(other)
        self.assertEqual(store.pending()[0].event_id, 'e1')

    def test_event_contract_and_ack_digest(self):
        with self.assertRaises(ContractError): event(recorded=0)
        store = MemoryEventStore(); store.append(event())
        with self.assertRaisesRegex(PersistenceError, 'EVENT_ID_CONFLICT'):
            store.acknowledge('e1', 'wrong')

