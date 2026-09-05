import unittest

from scripts.check_product_scope import audit_scope


class ProductScopeTests(unittest.TestCase):
    def test_primary_product_scope_is_consistent(self) -> None:
        result = audit_scope()

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["primary_tenant"], "kubernetes")
        self.assertEqual(result["failures"], [])
        self.assertTrue(all(result["checks"].values()))


if __name__ == "__main__":
    unittest.main()
