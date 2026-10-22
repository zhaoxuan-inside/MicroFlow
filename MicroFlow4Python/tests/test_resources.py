import unittest
from microflow.resources import LeaseRequest, MemoryLeaseProvider
from microflow.errors import ContractError


class ResourceTests(unittest.TestCase):
    def setUp(self): self.provider = MemoryLeaseProvider()

    def test_sorted_multi_resource_lease_and_renew(self):
        request = LeaseRequest(('db:1', 'queue:1'), 'worker', 1, 5)
        lease = self.provider.acquire(request, 10)
        self.assertEqual(lease.expires_at, 15)
        renewed = self.provider.renew(lease, 4, 12)
        self.assertEqual(renewed.expires_at, 16)
        self.provider.release(renewed, 13)

    def test_conflict_and_expiry_allow_next_owner(self):
        lease = self.provider.acquire(LeaseRequest(('a',), 'one', 1, 2), 0)
        with self.assertRaisesRegex(ContractError, 'RESOURCE_BUSY'):
            self.provider.acquire(LeaseRequest(('a',), 'two', 1, 2), 1)
        self.assertEqual(self.provider.acquire(LeaseRequest(('a',), 'two', 2, 2), 2).owner_id, 'two')

    def test_fencing_and_invalid_order(self):
        with self.assertRaises(ContractError): LeaseRequest(('b', 'a'), 'w', 1, 1)
        lease = self.provider.acquire(LeaseRequest(('a',), 'w', 1, 1), 0)
        with self.assertRaisesRegex(ContractError, 'LEASE_FENCED'):
            self.provider.renew(lease, 1, 1)
        with self.assertRaisesRegex(ContractError, 'LEASE_FENCED'):
            self.provider.release(lease, 1)

    def test_generation_does_not_merge_old_owner(self):
        first = self.provider.acquire(LeaseRequest(('a',), 'w', 1, 1), 0)
        with self.assertRaises(ContractError): self.provider.acquire(LeaseRequest(('a',), 'w', 2, 1), .5)
        self.provider.release(first, .5)
        second = self.provider.acquire(LeaseRequest(('a',), 'w', 2, 1), .5)
        self.assertNotEqual(first.lease_id, second.lease_id)

