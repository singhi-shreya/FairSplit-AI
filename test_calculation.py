import unittest
from app import calculate_bill_split, app


class TestFairSplitCalculationEngine(unittest.TestCase):
    """
    Test suite for FairSplit AI core calculation engine and API.
    Covers Tests A, B, C, D, and E as requested.
    """

    def setUp(self):
        # Create a Flask test client for API integration testing
        self.client = app.test_client()

    def test_a_basic_split(self):
        """
        TEST A: Basic split
        - Members: Shreya, Rahul, Priya
        - Pizza: ₹600, shared by Shreya and Rahul
        - Pasta: ₹400, shared by Priya
        - Coke: ₹300, shared by all three
        - Tax: 10%
        - Tip: 0%

        Expected results:
        - Shreya: ₹440.00
        - Rahul: ₹440.00
        - Priya: ₹550.00
        - Grand total: ₹1,430.00 (Guaranteed NOT ₹1,429.99)
        """
        members = ["Shreya", "Rahul", "Priya"]
        items = [
            {"name": "Pizza", "price": 600.0, "shared_by": ["Shreya", "Rahul"]},
            {"name": "Pasta", "price": 400.0, "shared_by": ["Priya"]},
            {"name": "Coke", "price": 300.0, "shared_by": ["Shreya", "Rahul", "Priya"]}
        ]
        result = calculate_bill_split(members, items, tax_percentage=10.0, tip_percentage=0.0)

        self.assertTrue(result["success"])
        summary = result["summary"]
        breakdown = result["breakdown"]

        # Check subtotals and individual shares:
        # Shreya: 300 + 100 = 400; tax = 40; total = 440.00
        # Rahul: 300 + 100 = 400; tax = 40; total = 440.00
        # Priya: 400 + 100 = 500; tax = 50; total = 550.00
        self.assertEqual(breakdown["Shreya"]["total"], 440.00)
        self.assertEqual(breakdown["Shreya"]["total_formatted"], "₹440.00")
        self.assertEqual(breakdown["Rahul"]["total"], 440.00)
        self.assertEqual(breakdown["Rahul"]["total_formatted"], "₹440.00")
        self.assertEqual(breakdown["Priya"]["total"], 550.00)
        self.assertEqual(breakdown["Priya"]["total_formatted"], "₹550.00")

        # Crucial check: Grand total must be exactly 1,430.00, NEVER 1,429.99
        self.assertNotEqual(summary["grand_total"], 1429.99)
        self.assertEqual(summary["grand_total"], 1430.00)
        self.assertEqual(summary["grand_total_formatted"], "₹1,430.00")
        self.assertEqual(summary["subtotal"], 1300.00)
        self.assertEqual(summary["tax"], 130.00)
        self.assertEqual(summary["tip"], 0.00)

        # Sum of individual totals must strictly equal grand total in both paise and rupees
        sum_of_totals_paise = sum(b["total_paise"] for b in breakdown.values())
        self.assertEqual(sum_of_totals_paise, summary["grand_total_paise"])
        self.assertEqual(sum_of_totals_paise, 143000)

        sum_of_totals_rupees = round(sum(b["total"] for b in breakdown.values()), 2)
        self.assertEqual(sum_of_totals_rupees, summary["grand_total"])
        self.assertEqual(sum_of_totals_rupees, 1430.00)

    def test_b_uneven_division(self):
        """
        TEST B: Uneven division
        - Three people share an item costing ₹10.01 (1001 paise).
        - Verify that the allocations add up to exactly ₹10.01 and that any extra paise
          are allocated using a documented, deterministic rule.
        """
        members = ["Alice", "Bob", "Charlie"]
        items = [
            {"name": "Shared Snack", "price": 10.01, "shared_by": ["Alice", "Bob", "Charlie"]}
        ]
        result = calculate_bill_split(members, items, tax_percentage=0.0, tip_percentage=0.0)

        self.assertTrue(result["success"])
        breakdown = result["breakdown"]
        summary = result["summary"]

        # 1001 paise divided by 3:
        # base_share = 333 paise (₹3.33), remainder = 2 paise
        # Deterministic rule: first 2 members (Alice, Bob) receive 334 paise (₹3.34), Charlie receives 333 paise (₹3.33)
        self.assertEqual(breakdown["Alice"]["subtotal_paise"], 334)
        self.assertEqual(breakdown["Alice"]["total"], 3.34)

        self.assertEqual(breakdown["Bob"]["subtotal_paise"], 334)
        self.assertEqual(breakdown["Bob"]["total"], 3.34)

        self.assertEqual(breakdown["Charlie"]["subtotal_paise"], 333)
        self.assertEqual(breakdown["Charlie"]["total"], 3.33)

        # Sum of individual paise must equal 1001 paise exactly
        total_allocated_paise = sum(b["total_paise"] for b in breakdown.values())
        self.assertEqual(total_allocated_paise, 1001)
        self.assertEqual(summary["grand_total_paise"], 1001)
        self.assertEqual(summary["grand_total"], 10.01)

    def test_c_one_participant(self):
        """
        TEST C: One participant
        - One person orders an item costing ₹250.00.
        - Tax: 0%
        - Tip: 0%
        - Expected total: ₹250.00.
        """
        members = ["SoloDiner"]
        items = [
            {"name": "Lunch Thali", "price": 250.00, "shared_by": ["SoloDiner"]}
        ]
        result = calculate_bill_split(members, items, tax_percentage=0.0, tip_percentage=0.0)

        self.assertTrue(result["success"])
        self.assertEqual(result["breakdown"]["SoloDiner"]["total"], 250.00)
        self.assertEqual(result["summary"]["subtotal"], 250.00)
        self.assertEqual(result["summary"]["grand_total"], 250.00)

    def test_d_tax_and_tip(self):
        """
        TEST D: Tax and tip
        - Use a valid bill with both tax and tip enabled.
        - Verify the calculation against independently calculated expected values.
        """
        members = ["Ankit", "Bhavna"]
        items = [
            {"name": "Paneer Tikka", "price": 200.00, "shared_by": ["Ankit"]},
            {"name": "Butter Naan", "price": 100.00, "shared_by": ["Bhavna"]},
            {"name": "Biryani", "price": 300.00, "shared_by": ["Ankit", "Bhavna"]}
        ]
        # Pre-tax subtotals:
        # Ankit: 200 + 150 = 350 (35000 paise)
        # Bhavna: 100 + 150 = 250 (25000 paise)
        # Subtotal: 600.00 (60000 paise)
        # Tax 5%: 600 * 0.05 = 30.00 (3000 paise)
        #   Ankit tax: 3000 * (350/600) = 1750 paise (₹17.50)
        #   Bhavna tax: 3000 * (250/600) = 1250 paise (₹12.50)
        # Tip 10%: 600 * 0.10 = 60.00 (6000 paise)
        #   Ankit tip: 6000 * (350/600) = 3500 paise (₹35.00)
        #   Bhavna tip: 6000 * (250/600) = 2500 paise (₹25.00)
        # Grand Total: 600 + 30 + 60 = 690.00
        #   Ankit total: 350 + 17.50 + 35.00 = 402.50 (40250 paise)
        #   Bhavna total: 250 + 12.50 + 25.00 = 287.50 (28750 paise)
        result = calculate_bill_split(members, items, tax_percentage=5.0, tip_percentage=10.0)

        self.assertTrue(result["success"])
        breakdown = result["breakdown"]
        summary = result["summary"]

        self.assertEqual(summary["subtotal"], 600.00)
        self.assertEqual(summary["tax"], 30.00)
        self.assertEqual(summary["tip"], 60.00)
        self.assertEqual(summary["grand_total"], 690.00)

        self.assertEqual(breakdown["Ankit"]["subtotal"], 350.00)
        self.assertEqual(breakdown["Ankit"]["tax"], 17.50)
        self.assertEqual(breakdown["Ankit"]["tip"], 35.00)
        self.assertEqual(breakdown["Ankit"]["total"], 402.50)

        self.assertEqual(breakdown["Bhavna"]["subtotal"], 250.00)
        self.assertEqual(breakdown["Bhavna"]["tax"], 12.50)
        self.assertEqual(breakdown["Bhavna"]["tip"], 25.00)
        self.assertEqual(breakdown["Bhavna"]["total"], 287.50)

        # Exact mathematical sum check
        self.assertEqual(
            breakdown["Ankit"]["total_paise"] + breakdown["Bhavna"]["total_paise"],
            summary["grand_total_paise"]
        )

    def test_e_invalid_input(self):
        """
        TEST E: Invalid input
        - Test an item with no participants, a negative price, and an invalid tax percentage.
        - Confirm that the app rejects the invalid input with clear error messages.
        """
        # Case 1: Item with no participants
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Aarav"],
                items=[{"name": "Coffee", "price": 50.0, "shared_by": []}],
                tax_percentage=0.0
            )
        self.assertIn("must have at least one person selected", str(ctx.exception))

        # Case 2: Negative price
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Aarav"],
                items=[{"name": "Coffee", "price": -50.0, "shared_by": ["Aarav"]}],
                tax_percentage=0.0
            )
        self.assertIn("must be greater than ₹0.00", str(ctx.exception))

        # Case 3: Zero price
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Aarav"],
                items=[{"name": "Water", "price": 0.0, "shared_by": ["Aarav"]}],
                tax_percentage=0.0
            )
        self.assertIn("must be greater than ₹0.00", str(ctx.exception))

        # Case 4: Negative tax percentage
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Aarav"],
                items=[{"name": "Coffee", "price": 50.0, "shared_by": ["Aarav"]}],
                tax_percentage=-5.0
            )
        self.assertIn("Tax percentage cannot be negative", str(ctx.exception))

        # Case 5: Negative tip percentage
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Aarav"],
                items=[{"name": "Coffee", "price": 50.0, "shared_by": ["Aarav"]}],
                tip_percentage=-10.0
            )
        self.assertIn("Tip percentage cannot be negative", str(ctx.exception))

        # Case 6: Duplicate member names (case-insensitive)
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(
                members=["Rohan", " rohan "],
                items=[{"name": "Tea", "price": 20.0, "shared_by": ["Rohan"]}]
            )
        self.assertIn("Duplicate group member name", str(ctx.exception))

        # Case 7: Empty bill (no items)
        with self.assertRaises(ValueError) as ctx:
            calculate_bill_split(members=["Rohan"], items=[])
        self.assertIn("Please add at least one bill item", str(ctx.exception))

    def test_api_endpoint_integration(self):
        """
        Verify the Flask HTTP API endpoint /api/calculate with valid and invalid payloads.
        """
        # Valid POST request
        payload = {
            "members": ["Shreya", "Rahul", "Priya"],
            "items": [
                {"name": "Pizza", "price": 600.0, "shared_by": ["Shreya", "Rahul"]},
                {"name": "Pasta", "price": 400.0, "shared_by": ["Priya"]},
                {"name": "Coke", "price": 300.0, "shared_by": ["Shreya", "Rahul", "Priya"]}
            ],
            "tax_percentage": 10.0,
            "tip_percentage": 0.0
        }
        res = self.client.post("/api/calculate", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["summary"]["grand_total"], 1430.00)

        # Invalid POST request (missing members)
        bad_payload = {"members": [], "items": []}
        res_bad = self.client.post("/api/calculate", json=bad_payload)
        self.assertEqual(res_bad.status_code, 400)
        data_bad = res_bad.get_json()
        self.assertFalse(data_bad["success"])
        self.assertIn("error", data_bad)

    def test_f_uneven_splits_with_tax_and_tip(self):
        """
        TEST F: Uneven item price division with both tax and tip.
        - ₹100.00 divided among 3 people = 33.34, 33.33, 33.33.
        - Tax 5%: 5.00.
        - Tip 15%: 15.00.
        - Grand total: ₹120.00 (12000 paise).
        - Verifies that Largest Remainder Method distributes tax/tip without losing or creating 1 paise.
        """
        members = ["Alice", "Bob", "Charlie"]
        items = [
            {"name": "Shared Platter", "price": 100.00, "shared_by": ["Alice", "Bob", "Charlie"]}
        ]
        result = calculate_bill_split(members, items, tax_percentage=5.0, tip_percentage=15.0)

        self.assertTrue(result["success"])
        breakdown = result["breakdown"]
        summary = result["summary"]

        self.assertEqual(summary["subtotal"], 100.00)
        self.assertEqual(summary["subtotal_paise"], 10000)
        self.assertEqual(summary["tax"], 5.00)
        self.assertEqual(summary["tax_paise"], 500)
        self.assertEqual(summary["tip"], 15.00)
        self.assertEqual(summary["tip_paise"], 1500)
        self.assertEqual(summary["grand_total"], 120.00)
        self.assertEqual(summary["grand_total_paise"], 12000)

        # Mathematical guarantee: Individual totals must add up exactly to grand total
        sum_of_member_paise = sum(b["total_paise"] for b in breakdown.values())
        self.assertEqual(sum_of_member_paise, 12000)

        sum_of_member_rupees = round(sum(b["total"] for b in breakdown.values()), 2)
        self.assertEqual(sum_of_member_rupees, 120.00)

    def test_g_many_participants_and_remainders(self):
        """
        TEST G: Multiple uneven items and 4 participants with 18% GST and 7.5% tip.
        - Item 1: ₹700.05 shared by all 4
        - Item 2: ₹123.45 shared by 3 people
        - Verifies paise integrity under realistic Indian restaurant conditions.
        """
        members = ["Amit", "Dev", "Neha", "Pooja"]
        items = [
            {"name": "Buffet", "price": 700.05, "shared_by": ["Amit", "Dev", "Neha", "Pooja"]},
            {"name": "Dessert", "price": 123.45, "shared_by": ["Amit", "Dev", "Neha"]}
        ]
        result = calculate_bill_split(members, items, tax_percentage=18.0, tip_percentage=7.5)

        self.assertTrue(result["success"])
        summary = result["summary"]
        breakdown = result["breakdown"]

        # Ensure exact integer paise conservation
        sum_of_member_paise = sum(b["total_paise"] for b in breakdown.values())
        self.assertEqual(sum_of_member_paise, summary["grand_total_paise"])

        sum_of_member_rupees = round(sum(b["total"] for b in breakdown.values()), 2)
        self.assertEqual(sum_of_member_rupees, summary["grand_total"])

    def test_h_float_representation_artifacts(self):
        """
        TEST H: Edge cases that trigger IEEE 754 floating-point inaccuracies.
        Prices like ₹1.15 (114.999...), ₹29.99, and ₹14.30.
        Confirms Decimal conversion prevents dropping any paise.
        """
        from app import to_paise, to_rupees, format_rupees

        # 1.15 in float is 1.1499999999999999. to_paise must return 115, not 114.
        self.assertEqual(to_paise(1.15), 115)
        self.assertEqual(to_paise("1.15"), 115)
        self.assertEqual(to_paise(29.99), 2999)
        self.assertEqual(to_paise(14.30), 1430)

        # Formatting checks
        self.assertEqual(format_rupees(143000), "₹1,430.00")
        self.assertEqual(format_rupees(44000), "₹440.00")
        self.assertEqual(format_rupees(55000), "₹550.00")
        self.assertEqual(format_rupees(115), "₹1.15")


if __name__ == "__main__":
    unittest.main()

