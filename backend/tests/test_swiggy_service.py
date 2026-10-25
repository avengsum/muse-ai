import unittest
from decimal import Decimal

from app.swiggy_service import (
    cart_total,
    create_pkce_pair,
    enforce_cart_cap,
    normalize_cart,
    order_eta_minutes,
    order_status,
)


class SwiggyServiceTests(unittest.TestCase):
    def test_pkce_challenge_is_derived_from_verifier(self):
        verifier, challenge = create_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertTrue(challenge)
        self.assertNotIn("=", challenge)

    def test_cart_total_and_normalization(self):
        cart = {
            "restaurantName": "Truffles",
            "items": [{"name": "Burger", "quantity": 2, "price": 249}],
            "grandTotal": "498",
        }

        self.assertEqual(cart_total(cart), Decimal("498"))
        self.assertEqual(enforce_cart_cap(cart)["restaurant_name"], "Truffles")
        self.assertEqual(normalize_cart(cart)["items"][0]["quantity"], 2)

    def test_cart_cap_is_enforced(self):
        with self.assertRaisesRegex(Exception, "₹1,000"):
            enforce_cart_cap({"total": 1001, "items": []})

    def test_order_status_and_eta_are_normalized(self):
        payload = {"order": {"deliveryStatus": "Out for delivery", "etaMinutes": "2"}}
        self.assertEqual(order_status(payload), "OUT_FOR_DELIVERY")
        self.assertEqual(order_eta_minutes(payload), 2)


if __name__ == "__main__":
    unittest.main()
