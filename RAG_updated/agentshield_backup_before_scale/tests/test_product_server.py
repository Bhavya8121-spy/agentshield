import unittest
from product_server import check_action


class ProductDemoTests(unittest.TestCase):
    def test_reader_read(self):
        self.assertEqual(check_action('reader', 'view', 1042)['decision'], 'ALLOW')

    def test_reader_delete_denied(self):
        self.assertEqual(check_action('reader', 'delete', 1042)['decision'], 'DENY')

    def test_admin_delete_own_allowed(self):
        self.assertEqual(check_action('admin', 'delete', 1042)['decision'], 'ALLOW')

    def test_cross_tenant_even_admin_denied(self):
        self.assertEqual(check_action('admin', 'view', 2042)['decision'], 'DENY')

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            check_action('admin', 'shell', 1042)

    def test_no_persistent_mutation(self):
        self.assertEqual(check_action('admin', 'delete', 1042)['decision'], 'ALLOW')
        self.assertEqual(check_action('reader', 'view', 1042)['decision'], 'ALLOW')
