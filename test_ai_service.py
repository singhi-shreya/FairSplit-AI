"""
Unit tests for FairSplit AI - Phase 2 AI-Powered Item Assignment.
Tests all 7 scenarios specified in the requirements:
1. Clear description where every item is assigned.
2. Description with an ambiguous pronoun ("We shared the pizza").
3. Unknown person's name.
4. Unknown item.
5. Description that does not mention every bill item.
6. Invalid or malformed AI response.
7. Missing Gemini API key.
"""

import base64
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from ai_service import (
    AiServiceError,
    MissingApiKeyError,
    parse_bill_description,
    scan_receipt_image,
    validate_and_sanitize_ai_response,
)
from app import app, calculate_bill_split


class TestAiService(unittest.TestCase):

    def setUp(self):
        self.flask_client = app.test_client()
        self.members = ["Shreya", "Rahul", "Priya"]
        self.items = [
            {"name": "Pizza", "price": 600.0},
            {"name": "Pasta", "price": 400.0},
            {"name": "Coke", "price": 300.0}
        ]

    def test_1_clear_description_all_items_assigned(self):
        """
        Scenario 1: A clear description where every item is assigned.
        'Rahul ordered the pasta. Priya and I shared the pizza. All three of us shared the Coke.'
        """
        mock_gemini_payload = {
            "assignments": [
                {"item": "Pasta", "participants": ["Rahul"]},
                {"item": "Pizza", "participants": ["Shreya", "Priya"]},
                {"item": "Coke", "participants": ["Shreya", "Rahul", "Priya"]}
            ],
            "ambiguities": [],
            "unrecognized_members": [],
            "unrecognized_items": [],
            "unmentioned_items": [],
            "needs_clarification": False,
            "clarifications": []
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_gemini_payload)
        mock_client.models.generate_content.return_value = mock_response

        desc = "Rahul ordered the pasta. Priya and I shared the pizza. All three of us shared the Coke."
        result = parse_bill_description(self.members, self.items, desc, client=mock_client)

        self.assertTrue(result["success"])
        self.assertFalse(result["needs_clarification"])
        self.assertEqual(len(result["assignments"]), 3)

        # Check item mappings
        assigned_map = {a["item"]: set(a["participants"]) for a in result["assignments"]}
        self.assertEqual(assigned_map["Pasta"], {"Rahul"})
        self.assertEqual(assigned_map["Pizza"], {"Shreya", "Priya"})
        self.assertEqual(assigned_map["Coke"], {"Shreya", "Rahul", "Priya"})

    def test_2_ambiguous_pronoun(self):
        """
        Scenario 2: Description with an ambiguous pronoun ('We shared the pizza').
        Should detect ambiguity and flag for clarification instead of guessing.
        """
        mock_gemini_payload = {
            "assignments": [],
            "ambiguities": ["The pronoun 'we' is ambiguous because it is unclear which group members are included."],
            "unrecognized_members": [],
            "unrecognized_items": [],
            "unmentioned_items": ["Pasta", "Coke"],
            "needs_clarification": True,
            "clarifications": ["Who does 'we' refer to for the Pizza?"]
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_gemini_payload)
        mock_client.models.generate_content.return_value = mock_response

        desc = "We shared the pizza."
        result = parse_bill_description(self.members, self.items, desc, client=mock_client)

        self.assertTrue(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertTrue(len(result["ambiguities"]) > 0)
        self.assertTrue(any("we" in c.lower() for c in result["clarifications"]))

    def test_3_unknown_person_name(self):
        """
        Scenario 3: An unknown person's name is mentioned in the description.
        (e.g., 'Vikram ordered the pizza' when Vikram is not in the group).
        """
        mock_gemini_payload = {
            "assignments": [
                {"item": "Pizza", "participants": ["Vikram"]}
            ],
            "ambiguities": [],
            "unrecognized_members": ["Vikram"],
            "unrecognized_items": [],
            "unmentioned_items": ["Pasta", "Coke"],
            "needs_clarification": True,
            "clarifications": ["Person 'Vikram' is not in the group members list."]
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_gemini_payload)
        mock_client.models.generate_content.return_value = mock_response

        desc = "Vikram ordered the pizza."
        result = parse_bill_description(self.members, self.items, desc, client=mock_client)

        self.assertTrue(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertIn("Vikram", result["unrecognized_members"])
        # Vikram must NOT be assigned as a valid participant
        for assign in result["assignments"]:
            self.assertNotIn("Vikram", assign["participants"])

    def test_4_unknown_item(self):
        """
        Scenario 4: An unknown item is mentioned that is not on the bill.
        (e.g., 'Rahul had the Sushi' when Sushi is not on the bill).
        """
        mock_gemini_payload = {
            "assignments": [
                {"item": "Sushi", "participants": ["Rahul"]}
            ],
            "ambiguities": [],
            "unrecognized_members": [],
            "unrecognized_items": ["Sushi"],
            "unmentioned_items": ["Pizza", "Pasta", "Coke"],
            "needs_clarification": True,
            "clarifications": ["Dish 'Sushi' is not in your bill items."]
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_gemini_payload)
        mock_client.models.generate_content.return_value = mock_response

        desc = "Rahul had the sushi."
        result = parse_bill_description(self.members, self.items, desc, client=mock_client)

        self.assertTrue(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertIn("Sushi", result["unrecognized_items"])
        # Sushi must NOT be in valid assignments
        assigned_items = [a["item"] for a in result["assignments"]]
        self.assertNotIn("Sushi", assigned_items)

    def test_5_unmentioned_bill_item(self):
        """
        Scenario 5: Description that does not mention every bill item.
        (e.g. only Pasta and Pizza mentioned; Coke was omitted).
        """
        mock_gemini_payload = {
            "assignments": [
                {"item": "Pizza", "participants": ["Shreya"]},
                {"item": "Pasta", "participants": ["Rahul"]}
            ],
            "ambiguities": [],
            "unrecognized_members": [],
            "unrecognized_items": [],
            "unmentioned_items": ["Coke"],
            "needs_clarification": False,
            "clarifications": []
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_gemini_payload)
        mock_client.models.generate_content.return_value = mock_response

        desc = "Shreya had pizza and Rahul had pasta."
        result = parse_bill_description(self.members, self.items, desc, client=mock_client)

        self.assertTrue(result["success"])
        self.assertIn("Coke", result["unmentioned_items"])

    def test_6_invalid_or_malformed_ai_response(self):
        """
        Scenario 6: Invalid or malformed AI response (e.g., non-JSON text).
        """
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "I am an AI and here is your bill split in plain text without JSON."
        mock_client.models.generate_content.return_value = mock_response

        with self.assertRaises(AiServiceError) as ctx:
            parse_bill_description(self.members, self.items, "Some description", client=mock_client)
        self.assertIn("invalid non-JSON", str(ctx.exception))

    def test_7_missing_gemini_api_key(self):
        """
        Scenario 7: Missing Gemini API key.
        Verifies MissingApiKeyError is raised and API returns a user-friendly error.
        Also verifies manual calculation remains 100% operational.
        """
        # Ensure GEMINI_API_KEY is unset for this test
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=True):
            with self.assertRaises(MissingApiKeyError) as ctx:
                parse_bill_description(self.members, self.items, "Rahul had pasta.", client=None)
            self.assertIn("Gemini API key is not configured", str(ctx.exception))

            # Verify Flask API endpoint handles missing key gracefully
            res = self.flask_client.post("/api/ai/assign", json={
                "members": self.members,
                "items": self.items,
                "description": "Rahul had pasta."
            })
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertFalse(data["success"])
            self.assertTrue(data.get("is_missing_api_key"))
            self.assertIn("Gemini API key is not configured", data["error"])

            # Verify manual calculation STILL works 100% when AI is unavailable
            manual_split = calculate_bill_split(
                members=["Shreya", "Rahul"],
                items=[{"name": "Pizza", "price": 600.0, "shared_by": ["Shreya", "Rahul"]}],
                tax_percentage=5.0
            )
            self.assertTrue(manual_split["success"])
            self.assertEqual(manual_split["summary"]["grand_total"], 630.00)

    def test_8_one_sentence_bill_creation(self):
        """
        Scenario 8: One-sentence bill extraction with dish names, prices, and people.
        'Rahul ate Pizza with was 600rs, Priya and I shared 400rs pasta and we all shared coke worth rs180'
        """
        from ai_service import parse_natural_language_bill

        mock_payload = {
            "items": [
                {"name": "Pizza", "price": 600.0, "shared_by": ["Rahul"]},
                {"name": "Pasta", "price": 400.0, "shared_by": ["Priya", "Shreya"]},
                {"name": "Coke", "price": 180.0, "shared_by": ["Rahul", "Priya", "Shreya"]}
            ],
            "ambiguities": [],
            "unrecognized_members": [],
            "needs_clarification": False,
            "clarifications": []
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_payload)
        mock_client.models.generate_content.return_value = mock_response

        text = "Rahul ate Pizza with was 600rs, Priya and I shared 400rs pasta and we all shared coke worth rs180"
        result = parse_natural_language_bill(self.members, text, client=mock_client)

        self.assertTrue(result["success"])
        self.assertFalse(result["needs_clarification"])
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["items"][0]["name"], "Pizza")
        self.assertEqual(result["items"][0]["price"], 600.0)
        self.assertEqual(result["items"][0]["shared_by"], ["Rahul"])

    def test_9_one_sentence_api_endpoint(self):
        """
        Scenario 9: POST /api/ai/parse-bill endpoint handles valid and missing inputs.
        """
        # 1. Missing description returns 400 with user-friendly error
        res = self.flask_client.post("/api/ai/parse-bill", json={
            "description": ""
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("Please enter a description of your bill", res.get_json()["error"])

        # 2. Mock full bill parsing via endpoint
        mock_payload = {
            "members": ["Rahul", "Priya", "Sneha"],
            "items": [
                {"name": "Pizza", "price": 600.0, "shared_by": ["Rahul"]},
                {"name": "Pasta", "price": 400.0, "shared_by": ["Priya", "Sneha"]},
                {"name": "Coke", "price": 180.0, "shared_by": ["Rahul", "Priya", "Sneha"]}
            ],
            "ambiguities": [],
            "needs_clarification": False,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_json", return_value=mock_payload):
            res = self.flask_client.post("/api/ai/parse-bill", json={
                "description": "Rahul ate pizza 600rs, Priya and I shared 400rs pasta, coke 180rs all three of us",
                "speaker_name": "Sneha"
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(len(data["members"]), 3)
            self.assertEqual(len(data["items"]), 3)
            self.assertEqual(data["subtotal"], 1180.0)

            # 3. Pass structured result directly into /api/calculate to verify full pipeline
            calc_res = self.flask_client.post("/api/calculate", json={
                "members": data["members"],
                "items": data["items"],
                "tax_percentage": 5.0,
                "tip_percentage": 0.0
            })
            self.assertEqual(calc_res.status_code, 200)
            calc_data = calc_res.get_json()
            self.assertTrue(calc_data["success"])
            self.assertEqual(calc_data["summary"]["subtotal"], 1180.0)
            self.assertEqual(calc_data["summary"]["grand_total"], 1239.0)

    def test_10_missing_price_detection(self):
        """
        Scenario 10: Item mentioned without price flags missing price and asks for clarification.
        """
        from ai_service import parse_complete_bill

        mock_payload = {
            "members": ["Rahul", "Priya"],
            "items": [
                {"name": "Pizza", "price": 600.0, "shared_by": ["Rahul"]},
                {"name": "Ice Cream", "price": 0.0, "shared_by": ["Priya"]}  # Missing price
            ],
            "ambiguities": [],
            "needs_clarification": True,
            "clarifications": ["Price for 'Ice Cream' was not mentioned. Please enter its price."]
        }

        with patch("ai_service._call_gemini_json", return_value=mock_payload):
            result = parse_complete_bill(
                description="Rahul had pizza for 600 and Priya had ice cream.",
                speaker_name=""
            )
            self.assertTrue(result["success"])
            self.assertTrue(result["needs_clarification"])
            self.assertTrue(result["items"][1]["has_missing_price"])
            self.assertEqual(result["items"][1]["price"], 0.0)
            self.assertTrue(any("ice cream" in c.lower() for c in result["clarifications"]))

    def test_11_receipt_scan_success(self):
        """
        Scenario 11: Successful receipt scanning with restaurant name, items, quantities,
        prices, subtotal, tax and tip. Shared_by defaults to empty for manual assignment.
        """
        mock_vision_payload = {
            "restaurant_name": "Toscano Trattoria",
            "is_receipt": True,
            "is_readable": True,
            "items": [
                {
                    "name": "Margherita Pizza",
                    "quantity": 2,
                    "unit_price": 450.0,
                    "total_price": 900.0,
                    "has_uncertain_price": False,
                    "has_uncertain_name": False
                },
                {
                    "name": "Tiramisu",
                    "quantity": 1,
                    "unit_price": 350.0,
                    "total_price": 350.0,
                    "has_uncertain_price": False,
                    "has_uncertain_name": False
                }
            ],
            "subtotal": 1250.0,
            "tax_percentage": 5.0,
            "tax_amount": 62.5,
            "tip_percentage": 10.0,
            "tip_amount": 125.0,
            "grand_total": 1437.5,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            fake_image = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 50
            result = scan_receipt_image(
                image_bytes=fake_image,
                mime_type="image/jpeg",
                members=["Shreya", "Rahul", "Priya"]
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["restaurant_name"], "Toscano Trattoria")
            self.assertEqual(len(result["items"]), 2)
            self.assertEqual(result["items"][0]["name"], "Margherita Pizza")
            self.assertEqual(result["items"][0]["quantity"], 2)
            self.assertEqual(result["items"][0]["unit_price"], 450.0)
            self.assertEqual(result["items"][0]["price"], 900.0)
            self.assertEqual(result["items"][0]["shared_by"], [])  # User must assign participants
            self.assertEqual(result["subtotal"], 1250.0)
            self.assertEqual(result["tax_percentage"], 5.0)
            self.assertEqual(result["tip_percentage"], 10.0)
            self.assertFalse(result["needs_clarification"])
            self.assertEqual(result["members"], ["Shreya", "Rahul", "Priya"])

    def test_12_receipt_scan_non_receipt_detection(self):
        """
        Scenario 12: Image is not a receipt (e.g., photo of a cat or selfie).
        Should raise a clean ValueError instructing user to upload a dining receipt.
        """
        mock_vision_payload = {
            "is_receipt": False,
            "is_readable": False,
            "clarifications": ["This appears to be a landscape photo, not a restaurant bill."]
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            fake_image = b"not_a_receipt"
            with self.assertRaises(ValueError) as ctx:
                scan_receipt_image(image_bytes=fake_image, mime_type="image/jpeg")
            self.assertIn("does not appear to be a dining or restaurant receipt", str(ctx.exception))

    def test_13_receipt_scan_blurry_unreadable(self):
        """
        Scenario 13: Receipt image is blurry or difficult to read.
        Should flag needs_clarification and prompt user to review items and prices.
        """
        mock_vision_payload = {
            "restaurant_name": "Cafe Mocha",
            "is_receipt": True,
            "is_readable": False,
            "items": [
                {"name": "Cappuccino", "quantity": 1, "total_price": 220.0}
            ],
            "subtotal": 220.0,
            "tax_percentage": 5.0,
            "grand_total": 231.0,
            "clarifications": ["Low resolution or motion blur detected."]
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            fake_image = b"blurry_receipt_data"
            result = scan_receipt_image(image_bytes=fake_image, mime_type="image/jpeg")

            self.assertTrue(result["success"])
            self.assertTrue(result["needs_clarification"])
            self.assertTrue(any("blurry" in c.lower() or "readable" in c.lower() or "blur" in c.lower() for c in result["clarifications"]))

    def test_14_receipt_scan_missing_price(self):
        """
        Scenario 14: Receipt has an item where price is torn or unreadable.
        Should mark has_missing_price=True and generate clarification for user.
        """
        mock_vision_payload = {
            "restaurant_name": "Spice Route",
            "is_receipt": True,
            "is_readable": True,
            "items": [
                {"name": "Butter Naan", "quantity": 2, "total_price": 120.0},
                {"name": "Paneer Tikka", "quantity": 1, "total_price": None, "unit_price": None}
            ],
            "subtotal": 120.0,
            "tax_percentage": 5.0,
            "grand_total": 126.0,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            fake_image = b"missing_price_data"
            result = scan_receipt_image(image_bytes=fake_image, mime_type="image/jpeg")

            self.assertTrue(result["success"])
            self.assertTrue(result["items"][1]["has_missing_price"])
            self.assertEqual(result["items"][1]["price"], 0.0)
            self.assertTrue(result["needs_clarification"])
            self.assertTrue(any("paneer tikka" in c.lower() for c in result["clarifications"]))

    def test_15_receipt_scan_subtotal_mismatch(self):
        """
        Scenario 15: Discrepancy between sum of items and printed subtotal on receipt.
        Should flag discrepancy in clarifications.
        """
        mock_vision_payload = {
            "restaurant_name": "Bistro",
            "is_receipt": True,
            "is_readable": True,
            "items": [
                {"name": "Burger", "quantity": 1, "total_price": 300.0}
            ],
            "subtotal": 500.0,  # Differs from 300.0 by > 1.0
            "tax_percentage": 0.0,
            "grand_total": 500.0,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            fake_image = b"mismatch_receipt_data"
            result = scan_receipt_image(image_bytes=fake_image, mime_type="image/jpeg")

            self.assertTrue(result["success"])
            self.assertTrue(result["needs_clarification"])
            self.assertTrue(any("differs from printed receipt subtotal" in c.lower() for c in result["clarifications"]))

    def test_16_receipt_scan_api_endpoint_multipart(self):
        """
        Scenario 16: Test /api/ai/scan-receipt with multipart/form-data upload.
        Tests:
        - Valid JPG upload -> 200 with receipt structure
        - Unsupported file type (.pdf/.txt) -> 400
        - Empty upload -> 400
        """
        mock_vision_payload = {
            "restaurant_name": "Main Street Cafe",
            "is_receipt": True,
            "is_readable": True,
            "items": [{"name": "Coffee", "quantity": 1, "total_price": 150.0}],
            "subtotal": 150.0,
            "tax_percentage": 5.0,
            "grand_total": 157.5,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            # 1. Valid file upload
            valid_img_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 200
            file_data = io.BytesIO(valid_img_bytes)
            res = self.flask_client.post(
                "/api/ai/scan-receipt",
                data={
                    "receipt": (file_data, "bill.jpg"),
                    "members": "Shreya, Rahul"
                },
                content_type="multipart/form-data"
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["restaurant_name"], "Main Street Cafe")
            self.assertEqual(data["members"], ["Shreya", "Rahul"])

            # 2. Unsupported extension (.pdf)
            pdf_data = io.BytesIO(b"%PDF-1.4..." + b"\x00" * 200)
            res_bad = self.flask_client.post(
                "/api/ai/scan-receipt",
                data={"receipt": (pdf_data, "bill.pdf")},
                content_type="multipart/form-data"
            )
            self.assertEqual(res_bad.status_code, 400)
            self.assertIn("Unsupported file type", res_bad.get_json()["error"])

            # 3. No file provided
            res_empty = self.flask_client.post(
                "/api/ai/scan-receipt",
                data={},
                content_type="multipart/form-data"
            )
            self.assertEqual(res_empty.status_code, 400)

    def test_17_receipt_scan_api_endpoint_base64_json(self):
        """
        Scenario 17: Test /api/ai/scan-receipt with base64 data URI in JSON payload.
        """
        mock_vision_payload = {
            "restaurant_name": "Dosa House",
            "is_receipt": True,
            "is_readable": True,
            "items": [{"name": "Masala Dosa", "quantity": 2, "unit_price": 120.0, "total_price": 240.0}],
            "subtotal": 240.0,
            "tax_percentage": 5.0,
            "grand_total": 252.0,
            "clarifications": []
        }

        b64_img = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 200).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{b64_img}"

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            res = self.flask_client.post(
                "/api/ai/scan-receipt",
                json={
                    "image": data_uri,
                    "members": ["Aman", "Rohan"]
                }
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["restaurant_name"], "Dosa House")
            self.assertEqual(data["members"], ["Aman", "Rohan"])
            self.assertEqual(data["items"][0]["quantity"], 2)

    def test_18_receipt_to_calculation_pipeline(self):
        """
        Scenario 18: Full integration pipeline from receipt scan through user review
        to /api/calculate with exact integer-paise math.
        """
        mock_vision_payload = {
            "restaurant_name": "Pizzeria Deliciosa",
            "is_receipt": True,
            "is_readable": True,
            "items": [
                {"name": "Pizza", "quantity": 1, "unit_price": 600.0, "total_price": 600.0},
                {"name": "Pasta", "quantity": 1, "unit_price": 400.0, "total_price": 400.0}
            ],
            "subtotal": 1000.0,
            "tax_percentage": 10.0,
            "tip_percentage": 0.0,
            "grand_total": 1100.0,
            "clarifications": []
        }

        with patch("ai_service._call_gemini_vision_json", return_value=mock_vision_payload):
            # Step 1: Scan receipt
            valid_img_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 200
            scan_res = self.flask_client.post(
                "/api/ai/scan-receipt",
                data={
                    "receipt": (io.BytesIO(valid_img_bytes), "receipt.jpg"),
                    "members": "Shreya, Rahul, Priya"
                },
                content_type="multipart/form-data"
            )
            self.assertEqual(scan_res.status_code, 200)
            scan_data = scan_res.get_json()
            self.assertTrue(scan_data["success"])

            # Step 2: User assigns participants on the review screen
            # Pizza (₹600) -> Shreya & Rahul (₹300 each)
            # Pasta (₹400) -> Priya (₹400)
            items_to_calculate = [
                {"name": "Pizza", "price": 600.0, "shared_by": ["Shreya", "Rahul"]},
                {"name": "Pasta", "price": 400.0, "shared_by": ["Priya"]}
            ]

            # Step 3: Pass to existing /api/calculate engine
            calc_res = self.flask_client.post(
                "/api/calculate",
                json={
                    "members": scan_data["members"],
                    "items": items_to_calculate,
                    "tax_percentage": scan_data["tax_percentage"],
                    "tip_percentage": scan_data["tip_percentage"]
                }
            )
            self.assertEqual(calc_res.status_code, 200)
            calc_data = calc_res.get_json()
            self.assertTrue(calc_data["success"])

            # Step 4: Verify exact integer paise:
            # Subtotal: ₹1,000.00
            # Tax (10%): ₹100.00
            # Grand Total: ₹1,100.00
            # Shreya: ₹300 + ₹30 tax = ₹330.00
            # Rahul: ₹300 + ₹30 tax = ₹330.00
            # Priya: ₹400 + ₹40 tax = ₹440.00
            summary = calc_data["summary"]
            self.assertEqual(summary["subtotal"], 1000.0)
            self.assertEqual(summary["tax"], 100.0)
            self.assertEqual(summary["grand_total"], 1100.0)

            breakdown = calc_data["breakdown"]
            self.assertEqual(breakdown["Shreya"]["total"], 330.0)
            self.assertEqual(breakdown["Rahul"]["total"], 330.0)
            self.assertEqual(breakdown["Priya"]["total"], 440.0)
            total_sum = round(sum(b["total"] for b in breakdown.values()), 2)
            self.assertEqual(total_sum, 1100.0)


if __name__ == "__main__":
    unittest.main()


