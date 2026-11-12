"""
Unit and Integration Tests for FairSplit AI's PayPal Sandbox Integration.

Tests:
1. Currency conversion math and validation (INR -> USD).
2. Secure PayPal configuration API (never leaks secrets).
3. Bill calculation and SQLite persistence.
4. Individual order creation with server-side authoritativeness.
5. Isolation test: One member paying leaves other members pending.
6. Duplicate payment prevention (cannot pay an already-paid member).
7. Duplicate capture prevention (cannot reuse order ID).
8. Tampering prevention (mismatched member or bill rejected).
9. Mismatch amount and failed capture handling.
"""

import os
import unittest
import tempfile
import json
from unittest.mock import patch, MagicMock

# Import app components
import app as flask_app_module
from app import app
from bill_store import BillStore
from paypal_service import (
    convert_inr_to_usd,
    CurrencyConversionError,
    PayPalService,
    PayPalClient,
    PayPalAuthError,
    PayPalCaptureError,
    PayPalError
)


class TestCurrencyConversion(unittest.TestCase):
    """Tests for INR to USD conversion math and validation."""

    def test_standard_conversion(self):
        # 100 INR at 0.012 = 1.20 USD
        self.assertEqual(convert_inr_to_usd(100.0, 0.012), 1.20)
        # 440 INR at 0.012 = 5.28 USD
        self.assertEqual(convert_inr_to_usd(440.0, 0.012), 5.28)
        # 550 INR at 0.012 = 6.60 USD
        self.assertEqual(convert_inr_to_usd(550.0, 0.012), 6.60)

    def test_minimum_amount(self):
        # Small amounts round up to minimum of 0.01
        self.assertEqual(convert_inr_to_usd(0.10, 0.012), 0.01)

    def test_invalid_rate_rejected(self):
        with self.assertRaises(CurrencyConversionError):
            convert_inr_to_usd(100.0, 0.0)
        with self.assertRaises(CurrencyConversionError):
            convert_inr_to_usd(100.0, -0.05)
        with self.assertRaises(CurrencyConversionError):
            convert_inr_to_usd(100.0, "invalid")

    def test_invalid_amount_rejected(self):
        with self.assertRaises(CurrencyConversionError):
            convert_inr_to_usd(0.0, 0.012)
        with self.assertRaises(CurrencyConversionError):
            convert_inr_to_usd(-50.0, 0.012)


class TestPayPalIntegrationEndpoints(unittest.TestCase):
    """Integration tests for Flask endpoints using an isolated SQLite database."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()

        # Initialize fresh store with temporary database
        self.test_store = BillStore(db_path=self.temp_db.name)

        # Patch app.bill_store with our test store
        self.store_patch = patch.object(flask_app_module, "bill_store", self.test_store)
        self.store_patch.start()

        self.client = app.test_client()

    def tearDown(self):
        self.store_patch.stop()
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_config_endpoint_security(self):
        """GET /api/paypal/config returns public details and NEVER exposes secret."""
        with patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "sandbox_client_test_123",
            "PAYPAL_CLIENT_SECRET": "SUPER_SECRET_NEVER_LEAK",
            "PAYPAL_MODE": "sandbox",
            "INR_TO_USD_RATE": "0.0125"
        }):
            resp = self.client.get("/api/paypal/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()

            self.assertTrue(data["is_enabled"])
            self.assertEqual(data["client_id"], "sandbox_client_test_123")
            self.assertEqual(data["currency"], "USD")
            self.assertEqual(data["inr_to_usd_rate"], 0.0125)
            self.assertEqual(data["mode"], "sandbox")
            self.assertIn("currency_disclosure", data)
            # Crucial security check: secret must not appear anywhere
            self.assertNotIn("SUPER_SECRET_NEVER_LEAK", json.dumps(data))
            self.assertNotIn("client_secret", data)

    def test_calculate_persists_bill_and_returns_id(self):
        """POST /api/calculate automatically persists the bill and member shares."""
        payload = {
            "members": ["Shreya", "Rahul", "Priya"],
            "items": [
                {"name": "Pizza", "price": 900.0, "shared_by": ["Shreya", "Rahul", "Priya"]},
                {"name": "Brownie", "price": 300.0, "shared_by": ["Priya"]}
            ],
            "tax_percentage": 5.0,
            "tip_percentage": 10.0
        }
        resp = self.client.post("/api/calculate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertTrue(data["success"])
        self.assertIn("bill_id", data)
        bill_id = data["bill_id"]

        # Check that it exists in the test database
        saved = self.test_store.get_bill(bill_id)
        self.assertIsNotNone(saved)
        self.assertEqual(len(saved["members"]), 3)

        # Check members and statuses
        summary = self.test_store.get_settlement_summary(bill_id)
        self.assertEqual(summary["total_members"], 3)
        self.assertEqual(summary["pending_members"], 3)
        self.assertEqual(summary["paid_members"], 0)

    @patch.object(PayPalService, "create_individual_order")
    def test_create_order_individual_share(self, mock_create_order):
        """POST /api/paypal/create-order fetches share from server database and calls PayPal."""
        # Setup bill in database
        bill_id = "test_bill_001"
        summary = {"grand_total": 1380.0}
        breakdown = {
            "Shreya": {"total": 440.0, "items": []},
            "Rahul": {"total": 440.0, "items": []},
            "Priya": {"total": 550.0, "items": []}
        }
        self.test_store.save_bill(bill_id, "Dinner Split", summary, breakdown)

        mock_create_order.return_value = {
            "order_id": "PAYPAL_ORDER_SHREYA_999",
            "status": "CREATED"
        }

        with patch.dict(os.environ, {
            "INR_TO_USD_RATE": "0.012",
            "PAYPAL_CLIENT_ID": "test_sandbox_client_id",
            "PAYPAL_CLIENT_SECRET": "test_sandbox_secret"
        }):
            resp = self.client.post("/api/paypal/create-order", json={
                "bill_id": bill_id,
                "member_name": "Shreya"
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()

            self.assertTrue(data["success"])
            self.assertEqual(data["orderID"], "PAYPAL_ORDER_SHREYA_999")
            self.assertEqual(data["member_name"], "Shreya")
            self.assertEqual(data["amount_inr"], 440.0)
            self.assertEqual(data["amount_usd"], 5.28)  # 440 * 0.012

            # Verify mock called with server-calculated USD amount (5.28)
            mock_create_order.assert_called_once_with(
                amount_usd=5.28,
                member_name="Shreya",
                bill_title="Dinner Split",
                bill_id=bill_id
            )

            # Verify recorded in store
            order_record = self.test_store.get_paypal_order("PAYPAL_ORDER_SHREYA_999")
            self.assertIsNotNone(order_record)
            self.assertEqual(order_record["member_name"], "Shreya")
            self.assertEqual(order_record["amount_usd"], 5.28)
            self.assertEqual(order_record["status"], "CREATED")

    def test_create_order_prevents_duplicate_if_already_paid(self):
        """POST /api/paypal/create-order returns 400 if member has already paid."""
        bill_id = "test_bill_paid_member"
        summary = {"grand_total": 440.0}
        breakdown = {"Rahul": {"total": 440.0, "items": []}}
        self.test_store.save_bill(bill_id, "Cafe Split", summary, breakdown)

        # Mark Rahul as paid
        self.test_store.mark_member_paid(
            bill_id=bill_id,
            member_name="Rahul",
            order_id="PREV_ORDER_123",
            capture_id="CAPTURE_123",
            amount_usd=5.28
        )

        with patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "test_sandbox_client_id",
            "PAYPAL_CLIENT_SECRET": "test_sandbox_secret"
        }):
            resp = self.client.post("/api/paypal/create-order", json={
                "bill_id": bill_id,
                "member_name": "Rahul"
            })
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertFalse(data["success"])
            self.assertIn("already paid", data["error"].lower())

    @patch.object(PayPalService, "capture_order")
    def test_capture_order_updates_ONLY_target_member(self, mock_capture):
        """
        CRITICAL ISOLATION REQUIREMENT:
        When Rahul pays his share, ONLY Rahul is marked paid.
        Shreya and Priya MUST remain Pending.
        """
        bill_id = "test_bill_isolation"
        summary = {"grand_total": 1430.0}
        breakdown = {
            "Shreya": {"total": 440.0, "items": []},
            "Rahul": {"total": 440.0, "items": []},
            "Priya": {"total": 550.0, "items": []}
        }
        self.test_store.save_bill(bill_id, "Dinner Split", summary, breakdown)

        # Record a created order for Rahul
        order_id = "ORDER_RAHUL_001"
        self.test_store.record_paypal_order(
            order_id=order_id,
            bill_id=bill_id,
            member_name="Rahul",
            amount_inr=440.0,
            amount_usd=5.28,
            currency="USD"
        )

        mock_capture.return_value = {
            "order_id": order_id,
            "capture_id": "CAP_RAHUL_777",
            "status": "COMPLETED",
            "amount_usd": 5.28,
            "currency": "USD"
        }

        # Execute capture for Rahul
        resp = self.client.post("/api/paypal/capture-order", json={
            "order_id": order_id,
            "bill_id": bill_id,
            "member_name": "Rahul"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

        # Check member statuses in store
        rahul = self.test_store.get_member(bill_id, "Rahul")
        shreya = self.test_store.get_member(bill_id, "Shreya")
        priya = self.test_store.get_member(bill_id, "Priya")

        # Rahul MUST be paid
        self.assertEqual(rahul["status"], "paid")
        self.assertEqual(rahul["paypal_order_id"], order_id)
        self.assertEqual(rahul["amount_paid_usd"], 5.28)

        # Shreya and Priya MUST STILL BE PENDING
        self.assertEqual(shreya["status"], "pending")
        self.assertEqual(priya["status"], "pending")

        # Settlement summary verification
        summary = self.test_store.get_settlement_summary(bill_id)
        self.assertEqual(summary["total_members"], 3)
        self.assertEqual(summary["paid_members"], 1)
        self.assertEqual(summary["pending_members"], 2)
        self.assertAlmostEqual(summary["total_collected_inr"], 440.0)
        self.assertAlmostEqual(summary["total_outstanding_inr"], 990.0)

    @patch.object(PayPalService, "capture_order")
    def test_capture_order_tampering_mismatch_rejected(self, mock_capture):
        """Attempting to capture order created for Rahul under Priya's name is rejected."""
        bill_id = "test_bill_tamper"
        summary = {"grand_total": 990.0}
        breakdown = {
            "Rahul": {"total": 440.0, "items": []},
            "Priya": {"total": 550.0, "items": []}
        }
        self.test_store.save_bill(bill_id, "Lunch Split", summary, breakdown)

        order_id = "ORDER_RAHUL_TAMPER"
        self.test_store.record_paypal_order(
            order_id=order_id,
            bill_id=bill_id,
            member_name="Rahul",
            amount_inr=440.0,
            amount_usd=5.28,
            currency="USD"
        )

        # Attacker tries to pass member_name: 'Priya' with Rahul's order_id
        resp = self.client.post("/api/paypal/capture-order", json={
            "order_id": order_id,
            "bill_id": bill_id,
            "member_name": "Priya"
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("mismatch", data["error"].lower())

    @patch.object(PayPalService, "capture_order")
    def test_duplicate_capture_rejected(self, mock_capture):
        """Capturing an already completed order is rejected with 400."""
        bill_id = "test_bill_dup"
        summary = {"grand_total": 440.0}
        breakdown = {"Rahul": {"total": 440.0, "items": []}}
        self.test_store.save_bill(bill_id, "Split", summary, breakdown)

        order_id = "ORDER_DUP_123"
        self.test_store.record_paypal_order(
            order_id=order_id,
            bill_id=bill_id,
            member_name="Rahul",
            amount_inr=440.0,
            amount_usd=5.28,
            currency="USD"
        )

        mock_capture.return_value = {
            "order_id": order_id,
            "capture_id": "CAP_DUP_123",
            "status": "COMPLETED",
            "amount_usd": 5.28,
            "currency": "USD"
        }

        # 1. First capture succeeds
        resp1 = self.client.post("/api/paypal/capture-order", json={
            "order_id": order_id,
            "bill_id": bill_id,
            "member_name": "Rahul"
        })
        self.assertEqual(resp1.status_code, 200)

        # 2. Second capture for same order is rejected
        resp2 = self.client.post("/api/paypal/capture-order", json={
            "order_id": order_id,
            "bill_id": bill_id,
            "member_name": "Rahul"
        })
        self.assertEqual(resp2.status_code, 400)
        data = resp2.get_json()
        self.assertFalse(data["success"])
        self.assertIn("already been completed", data["error"].lower())

    def test_settle_offline_payment_success(self):
        """POST /api/bills/<bill_id>/settle-offline marks only target member as paid offline."""
        bill_id = "test_bill_offline_1"
        summary = {"grand_total": 990.0}
        breakdown = {
            "Rahul": {"total": 440.0, "items": []},
            "Shreya": {"total": 550.0, "items": []}
        }
        self.test_store.save_bill(bill_id, "Dinner", summary, breakdown)

        resp = self.client.post(f"/api/bills/{bill_id}/settle-offline", json={
            "member_name": "Rahul"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["member_name"], "Rahul")
        self.assertEqual(data["payment_method"], "offline")

        # Verify Rahul is paid, but Shreya remains pending
        m_rahul = self.test_store.get_member(bill_id, "Rahul")
        m_shreya = self.test_store.get_member(bill_id, "Shreya")
        self.assertEqual(m_rahul["status"], "paid")
        self.assertEqual(m_rahul["payment_method"], "offline")
        self.assertEqual(m_shreya["status"], "pending")
        self.assertIsNone(m_shreya["payment_method"])

    def test_settle_offline_duplicate_prevention(self):
        """Cannot mark a member as offline paid if they are already paid."""
        bill_id = "test_bill_offline_dup"
        summary = {"grand_total": 440.0}
        breakdown = {"Rahul": {"total": 440.0, "items": []}}
        self.test_store.save_bill(bill_id, "Dinner", summary, breakdown)

        # 1. First offline mark succeeds
        resp1 = self.client.post(f"/api/bills/{bill_id}/settle-offline", json={"member_name": "Rahul"})
        self.assertEqual(resp1.status_code, 200)

        # 2. Second offline mark rejected
        resp2 = self.client.post(f"/api/bills/{bill_id}/settle-offline", json={"member_name": "Rahul"})
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("already marked as paid", resp2.get_json()["error"])

    def test_revert_offline_payment_success(self):
        """Accidental offline payment can be reverted back to pending."""
        bill_id = "test_bill_offline_rev"
        summary = {"grand_total": 440.0}
        breakdown = {"Rahul": {"total": 440.0, "items": []}}
        self.test_store.save_bill(bill_id, "Dinner", summary, breakdown)

        # Mark paid offline
        self.test_store.mark_member_offline_paid(bill_id, "Rahul")
        self.assertEqual(self.test_store.get_member(bill_id, "Rahul")["status"], "paid")

        # Revert offline
        resp = self.client.post(f"/api/bills/{bill_id}/revert-offline", json={"member_name": "Rahul"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "pending")

        # Verify database record
        m = self.test_store.get_member(bill_id, "Rahul")
        self.assertEqual(m["status"], "pending")
        self.assertIsNone(m["payment_method"])

    def test_cannot_revert_paypal_via_offline_endpoint(self):
        """Safety invariant: Revert offline endpoint strictly rejects reverting PayPal captures."""
        bill_id = "test_bill_paypal_no_rev"
        summary = {"grand_total": 440.0}
        breakdown = {"Rahul": {"total": 440.0, "items": []}}
        self.test_store.save_bill(bill_id, "Dinner", summary, breakdown)

        # Rahul paid via PayPal
        self.test_store.mark_member_paid(
            bill_id=bill_id,
            member_name="Rahul",
            order_id="ORD_123",
            capture_id="CAP_123",
            amount_usd=5.28,
            payment_method="paypal"
        )

        resp = self.client.post(f"/api/bills/{bill_id}/revert-offline", json={"member_name": "Rahul"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cannot revert a payment completed through paypal", resp.get_json()["error"].lower())

    @patch.object(PayPalService, "capture_order")
    def test_settlement_summary_separate_channels(self, mock_capture):
        """Settlement summary correctly separates verified PayPal payments from offline cash payments."""
        bill_id = "test_bill_multi_channel"
        summary = {"grand_total": 1430.0}
        breakdown = {
            "Rahul": {"total": 440.0, "items": []},
            "Shreya": {"total": 440.0, "items": []},
            "Priya": {"total": 550.0, "items": []}
        }
        self.test_store.save_bill(bill_id, "Group Dinner", summary, breakdown)

        # 1. Rahul pays via PayPal
        self.test_store.record_paypal_order(
            order_id="ORD_RAHUL_440",
            bill_id=bill_id,
            member_name="Rahul",
            amount_inr=440.0,
            amount_usd=5.28,
            currency="USD"
        )
        mock_capture.return_value = {
            "order_id": "ORD_RAHUL_440",
            "capture_id": "CAP_RAHUL_440",
            "status": "COMPLETED",
            "amount_usd": 5.28,
            "currency": "USD"
        }
        self.client.post("/api/paypal/capture-order", json={
            "order_id": "ORD_RAHUL_440",
            "bill_id": bill_id,
            "member_name": "Rahul"
        })

        # 2. Shreya pays via Offline Cash
        self.client.post(f"/api/bills/{bill_id}/settle-offline", json={
            "member_name": "Shreya"
        })

        # 3. Priya remains pending

        # Check settlement summary via API
        resp = self.client.get(f"/api/bills/{bill_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        settlement = data["settlement"]

        self.assertEqual(settlement["total_members"], 3)
        self.assertEqual(settlement["paid_members"], 2)
        self.assertEqual(settlement["pending_members"], 1)
        self.assertEqual(settlement["paypal_paid_count"], 1)
        self.assertEqual(settlement["offline_paid_count"], 1)

        # Financial breakdown
        self.assertEqual(settlement["paypal_collected_inr"], 440.0)
        self.assertEqual(settlement["offline_collected_inr"], 440.0)
        self.assertEqual(settlement["total_collected_inr"], 880.0)
        self.assertEqual(settlement["total_outstanding_inr"], 550.0)
        self.assertEqual(settlement["progress_percentage"], 67)
        self.assertFalse(settlement["all_settled"])


if __name__ == "__main__":
    unittest.main()

