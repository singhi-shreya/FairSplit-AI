import os
import json
import base64
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import ai_service
from bill_store import bill_store
from paypal_service import (
    paypal_service,
    PayPalError,
    PayPalAuthError,
    PayPalCaptureError,
    CurrencyConversionError,
)

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload limit


@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "success": False,
        "error": "The uploaded receipt image is too large (maximum allowed size is 10 MB). Please upload a smaller photo."
    }), 413


def to_paise(amount) -> int:
    """
    Converts a rupee amount (float/int/string) to integer paise safely using Decimal.
    Guarantees protection against IEEE 754 binary floating-point representation artifacts
    (e.g., 1.15 * 100 becoming 114.99999999999999).
    """
    try:
        dec = Decimal(str(amount).strip())
        return int((dec * Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except Exception:
        return int(round(float(amount) * 100))


def to_rupees(paise: int) -> float:
    """Converts integer paise back to rupees float rounded to 2 decimal places."""
    return round(paise / 100.0, 2)


def format_rupees(paise: int) -> str:
    """Formats integer paise as a standard 2-decimal-place INR string (e.g. '₹1,430.00')."""
    rupees = paise / 100.0
    return f"₹{rupees:,.2f}"


def distribute_proportionally(total_amount_paise: int, member_subtotals: dict, total_subtotal_paise: int, members: list) -> dict:
    """
    Distributes an amount (such as tax or tip in paise) proportionally across members
    based on their pre-tax subtotal using the Largest Remainder Method (Hamilton method).
    
    Guarantees that:
    1. Every person's share is proportional to their subtotal.
    2. Sum of individual shares equals total_amount_paise exactly to the nearest paise.
    3. No paise are created or lost due to rounding.
    4. Uses pure integer division and integer modulo with zero floating-point inaccuracies.
    """
    if total_amount_paise == 0 or total_subtotal_paise == 0:
        return {m: 0 for m in members}

    allocations = {}
    remainders = []
    allocated_sum = 0

    for idx, m in enumerate(members):
        sub = member_subtotals[m]
        # Exact integer quotient and integer remainder numerator:
        # (total_amount_paise * sub) / total_subtotal_paise
        prod = total_amount_paise * sub
        floor_share = prod // total_subtotal_paise
        rem = prod % total_subtotal_paise

        allocations[m] = floor_share
        allocated_sum += floor_share
        # Store (integer remainder, member_index, member_name) for deterministic sorting
        remainders.append((rem, idx, m))

    leftover_paise = total_amount_paise - allocated_sum
    # Sort descending by remainder; for ties, preserve the group's original member order
    remainders.sort(key=lambda x: (-x[0], x[1]))

    for k in range(leftover_paise):
        m = remainders[k][2]
        allocations[m] += 1

    return allocations


def calculate_bill_split(members: list, items: list, tax_percentage: float = 0.0, tip_percentage: float = 0.0) -> dict:
    """
    Core calculation engine for FairSplit AI.
    
    Uses integer paise arithmetic throughout to guarantee reliable, exact financial calculations.
    
    Rounding & Allocation Policy:
    - Shared item prices in paise are divided by the number of participants.
      Any remainder paise (e.g. 1001 paise shared by 3 = 333 each + 2 remainder) are assigned
      to the first participants in the item's list, ensuring sum(shares) == item price.
    - Tax and tips are calculated on the pre-tax subtotal and distributed proportionally
      to each person's subtotal using the Largest Remainder Method (Hamilton method).
    - Sum of all individual totals is mathematically guaranteed to equal grand total.
    """
    # 1. Validate members
    if not isinstance(members, list) or len(members) == 0:
        raise ValueError("Please add at least one group member.")

    cleaned_members = []
    seen_lower = set()
    for m in members:
        if not isinstance(m, str):
            raise ValueError("Member names must be text.")
        trimmed = m.strip()
        if not trimmed:
            raise ValueError("Member names cannot be empty or blank spaces.")
        lower_name = trimmed.lower()
        if lower_name in seen_lower:
            raise ValueError(f"Duplicate group member name: '{trimmed}'.")
        seen_lower.add(lower_name)
        cleaned_members.append(trimmed)

    # 2. Validate items
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError("Please add at least one bill item.")

    # 3. Validate tax and tip percentages
    try:
        tax_pct = float(tax_percentage or 0.0)
    except (ValueError, TypeError):
        raise ValueError("Tax percentage must be a valid number.")

    try:
        tip_pct = float(tip_percentage or 0.0)
    except (ValueError, TypeError):
        raise ValueError("Tip percentage must be a valid number.")

    if tax_pct < 0:
        raise ValueError("Tax percentage cannot be negative.")
    if tip_pct < 0:
        raise ValueError("Tip percentage cannot be negative.")

    # Data structures for per-member calculations (in integer paise)
    member_subtotals = {m: 0 for m in cleaned_members}
    member_items = {m: [] for m in cleaned_members}
    total_subtotal_paise = 0

    member_set = set(cleaned_members)

    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item #{idx} is invalid.")

        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Item #{idx} must have a valid description.")

        raw_price = item.get("price")
        try:
            price_float = float(raw_price)
        except (ValueError, TypeError):
            raise ValueError(f"Price for item '{name}' must be a valid number.")

        if price_float <= 0:
            raise ValueError(f"Price for item '{name}' must be greater than ₹0.00.")

        item_paise = to_paise(price_float)

        raw_shared_by = item.get("shared_by", [])
        if not isinstance(raw_shared_by, list):
            raise ValueError(f"Participants for item '{name}' must be a list.")

        # Clean participant names and check against existing members
        shared_by = [p.strip() for p in raw_shared_by if isinstance(p, str) and p.strip()]
        if not shared_by:
            raise ValueError(f"Item '{name}' must have at least one person selected.")

        invalid_people = [p for p in shared_by if p not in member_set]
        if invalid_people:
            raise ValueError(
                f"Item '{name}' contains participants who are not in the group: {', '.join(invalid_people)}."
            )

        num_participants = len(shared_by)
        base_share = item_paise // num_participants
        remainder_paise = item_paise % num_participants

        total_subtotal_paise += item_paise

        # Deterministic allocation of item cost and remainder paise
        for i, person in enumerate(shared_by):
            # Extra paise distributed to the first remainder_paise participants
            individual_share_paise = base_share + (1 if i < remainder_paise else 0)
            member_subtotals[person] += individual_share_paise
            member_items[person].append({
                "name": name,
                "full_price": to_rupees(item_paise),
                "full_price_paise": item_paise,
                "full_price_formatted": format_rupees(item_paise),
                "split_between": num_participants,
                "individual_share": to_rupees(individual_share_paise),
                "individual_share_paise": individual_share_paise,
                "individual_share_formatted": format_rupees(individual_share_paise)
            })

    # 4. Calculate total tax and tip on pre-tax subtotal (in integer paise using Decimal)
    tax_dec = Decimal(str(tax_pct))
    tip_dec = Decimal(str(tip_pct))
    total_tax_paise = int((Decimal(total_subtotal_paise) * tax_dec / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    total_tip_paise = int((Decimal(total_subtotal_paise) * tip_dec / Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    grand_total_paise = total_subtotal_paise + total_tax_paise + total_tip_paise

    # 5. Distribute tax and tip proportionally using Largest Remainder Method (Hamilton method)
    member_taxes = distribute_proportionally(
        total_tax_paise, member_subtotals, total_subtotal_paise, cleaned_members
    )
    member_tips = distribute_proportionally(
        total_tip_paise, member_subtotals, total_subtotal_paise, cleaned_members
    )

    # 6. Assemble final breakdown per member
    breakdown = {}
    for m in cleaned_members:
        sub_p = member_subtotals[m]
        tax_p = member_taxes[m]
        tip_p = member_tips[m]
        tot_p = sub_p + tax_p + tip_p

        breakdown[m] = {
            "name": m,
            "subtotal": to_rupees(sub_p),
            "subtotal_paise": sub_p,
            "subtotal_formatted": format_rupees(sub_p),
            "tax": to_rupees(tax_p),
            "tax_paise": tax_p,
            "tax_formatted": format_rupees(tax_p),
            "tip": to_rupees(tip_p),
            "tip_paise": tip_p,
            "tip_formatted": format_rupees(tip_p),
            "total": to_rupees(tot_p),
            "total_paise": tot_p,
            "total_formatted": format_rupees(tot_p),
            "items": member_items[m]
        }

    # 7. Invariant Verification: Mathematical guarantee that sum of individual totals equals grand total
    sum_of_member_totals_paise = sum(b["total_paise"] for b in breakdown.values())
    if sum_of_member_totals_paise != grand_total_paise:
        raise ValueError(
            f"Mathematical discrepancy: Member sum ({sum_of_member_totals_paise} paise) "
            f"does not match Grand Total ({grand_total_paise} paise)."
        )

    return {
        "success": True,
        "breakdown": breakdown,
        "summary": {
            "subtotal": to_rupees(total_subtotal_paise),
            "subtotal_paise": total_subtotal_paise,
            "subtotal_formatted": format_rupees(total_subtotal_paise),
            "tax": to_rupees(total_tax_paise),
            "tax_paise": total_tax_paise,
            "tax_formatted": format_rupees(total_tax_paise),
            "tax_percentage": tax_pct,
            "tip": to_rupees(total_tip_paise),
            "tip_paise": total_tip_paise,
            "tip_formatted": format_rupees(total_tip_paise),
            "tip_percentage": tip_pct,
            "grand_total": to_rupees(grand_total_paise),
            "grand_total_paise": grand_total_paise,
            "grand_total_formatted": format_rupees(grand_total_paise),
            "currency": "INR",
            "currency_symbol": "₹"
        }
    }


@app.route("/")
def index():
    """Renders the main page of FairSplit AI."""
    return render_template("index.html")


@app.route("/api/calculate", methods=["POST"])
def calculate_bill():
    """
    HTTP API endpoint for bill calculations.
    Validates payload and delegates to calculate_bill_split().
    Saves calculated bill to persistent server store for PayPal individual checkout.
    """
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "error": "No valid JSON data provided."}), 400

        members = data.get("members", [])
        items = data.get("items", [])
        tax_pct = data.get("tax_percentage", 0.0)
        tip_pct = data.get("tip_percentage", 0.0)

        result = calculate_bill_split(
            members=members,
            items=items,
            tax_percentage=tax_pct,
            tip_percentage=tip_pct
        )

        # Persist bill to server database for tamper-proof individual payments
        title = (data.get("title") or "Restaurant Dining Split").strip()
        bill_id = (data.get("bill_id") or "").strip()
        if not bill_id:
            bill_id = f"bill_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        bill_store.save_bill(bill_id, title, result["summary"], result["breakdown"])
        result["bill_id"] = bill_id
        result["title"] = title
        result["settlement"] = bill_store.get_settlement_summary(bill_id)

        return jsonify(result), 200

    except ValueError as val_err:
        return jsonify({"success": False, "error": str(val_err)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/paypal/config", methods=["GET"])
def paypal_config():
    """Returns public PayPal configuration (client_id, currency, inr_to_usd_rate)."""
    return jsonify(paypal_service.get_public_config()), 200


@app.route("/api/paypal/create-order", methods=["POST"])
def paypal_create_order():
    """
    Creates an individual PayPal order for a single member's share.
    Strictly calculates the amount server-side from persistent bill records.
    Never trusts amounts sent by frontend JavaScript.
    """
    try:
        data = request.get_json(silent=True) or {}
        bill_id = (data.get("bill_id") or "").strip()
        member_name = (data.get("member_name") or "").strip()

        if not bill_id or not member_name:
            return jsonify({"success": False, "error": "Both bill_id and member_name are required."}), 400

        if not paypal_service.is_configured():
            return jsonify({
                "success": False,
                "error": "PayPal checkout is not configured. Please ensure PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are set."
            }), 400

        # 1. Fetch server-side member share (tamper-proof)
        member = bill_store.get_member(bill_id, member_name)
        if not member:
            return jsonify({
                "success": False,
                "error": f"Member '{member_name}' not found for bill '{bill_id}'."
            }), 404

        # 2. Duplicate payment prevention: already paid members cannot pay again
        if member["status"] == "paid":
            return jsonify({
                "success": False,
                "error": f"{member_name} has already paid their share."
            }), 400

        amount_inr = member["share_inr"]
        if amount_inr <= 0:
            return jsonify({
                "success": False,
                "error": f"{member_name}'s calculated share is ₹0.00. No payment required."
            }), 400

        # 3. Server-side currency conversion
        amount_usd, usd_str = paypal_service.convert_inr_to_usd(amount_inr)

        # 4. Fetch bill title
        bill = bill_store.get_bill(bill_id)
        title = bill["title"] if bill else "Restaurant Dining Split"

        # 5. Create PayPal Order with CAPTURE intent
        order_data = paypal_service.create_individual_order(
            amount_usd=amount_usd,
            member_name=member["member_name"],
            bill_title=title,
            bill_id=bill_id
        )

        # 6. Bind order strictly to (bill_id, member_name, amount) in server store
        bill_store.record_paypal_order(
            order_id=order_data["order_id"],
            bill_id=bill_id,
            member_name=member["member_name"],
            amount_inr=amount_inr,
            amount_usd=amount_usd,
            currency="USD"
        )

        return jsonify({
            "success": True,
            "orderID": order_data["order_id"],
            "bill_id": bill_id,
            "member_name": member["member_name"],
            "amount_usd": amount_usd,
            "amount_usd_formatted": f"${amount_usd:.2f}",
            "amount_inr": amount_inr,
            "amount_inr_formatted": f"₹{amount_inr:,.2f}",
            "currency": "USD"
        }), 200

    except CurrencyConversionError as conv_err:
        return jsonify({"success": False, "error": str(conv_err)}), 400
    except PayPalAuthError as auth_err:
        return jsonify({"success": False, "error": str(auth_err)}), 401
    except PayPalError as pay_err:
        return jsonify({"success": False, "error": str(pay_err)}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/paypal/capture-order", methods=["POST"])
def paypal_capture_order():
    """
    Captures an approved PayPal order for an individual member.
    Verifies order_id against the server's record, checks that the captured amount matches,
    and updates only that member's status to 'paid'.
    """
    try:
        data = request.get_json(silent=True) or {}
        order_id = (data.get("order_id") or "").strip()
        bill_id = (data.get("bill_id") or "").strip()
        member_name = (data.get("member_name") or "").strip()

        if not order_id or not bill_id or not member_name:
            return jsonify({
                "success": False,
                "error": "order_id, bill_id, and member_name are all required."
            }), 400

        # 1. Lookup server-side recorded order
        order_record = bill_store.get_paypal_order(order_id)
        if not order_record:
            return jsonify({
                "success": False,
                "error": "Unrecognized PayPal order ID. Order was not initiated by FairSplit AI."
            }), 400

        # 2. Strict tampering check: order must match bill_id and member_name
        if order_record["bill_id"] != bill_id or order_record["member_name"].lower() != member_name.lower():
            return jsonify({
                "success": False,
                "error": "Verification mismatch: PayPal order does not match this bill or member."
            }), 400

        # 3. Duplicate capture check
        if order_record["status"] == "COMPLETED":
            return jsonify({
                "success": False,
                "error": "This PayPal order has already been completed."
            }), 400

        # 4. Check if member is already marked paid
        member = bill_store.get_member(bill_id, member_name)
        if not member:
            return jsonify({"success": False, "error": "Member not found on this bill."}), 404

        if member["status"] == "paid":
            return jsonify({
                "success": False,
                "error": f"{member_name} is already marked as paid."
            }), 400

        # 5. Capture the order via PayPal Orders API & verify amount/currency
        expected_usd = order_record["amount_usd"]
        capture_result = paypal_service.capture_order(order_id, expected_amount_usd=expected_usd)

        # 6. Mark member as paid in the persistent database
        bill_store.mark_member_paid(
            bill_id=bill_id,
            member_name=member["member_name"],
            order_id=order_id,
            capture_id=capture_result["capture_id"],
            amount_usd=capture_result["amount_usd"],
            payer_email=capture_result.get("payer_email")
        )

        # 7. Get updated settlement summary (total collected, total outstanding, progress)
        settlement = bill_store.get_settlement_summary(bill_id)

        return jsonify({
            "success": True,
            "status": "COMPLETED",
            "bill_id": bill_id,
            "member_name": member["member_name"],
            "amount_usd": capture_result["amount_usd"],
            "amount_usd_formatted": f"${capture_result['amount_usd']:.2f}",
            "capture_id": capture_result["capture_id"],
            "payer_email": capture_result.get("payer_email"),
            "payer_name": capture_result.get("payer_name"),
            "settlement": settlement
        }), 200

    except PayPalCaptureError as cap_err:
        return jsonify({"success": False, "error": str(cap_err)}), 400
    except PayPalAuthError as auth_err:
        return jsonify({"success": False, "error": str(auth_err)}), 401
    except PayPalError as pay_err:
        return jsonify({"success": False, "error": str(pay_err)}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/bills/<bill_id>", methods=["GET"])
def get_bill_status(bill_id):
    """Retrieves latest server-side bill data and settlement status."""
    bill = bill_store.get_bill(bill_id)
    if not bill:
        return jsonify({"success": False, "error": "Bill not found."}), 404
    settlement = bill_store.get_settlement_summary(bill_id)
    return jsonify({"success": True, "bill": bill, "settlement": settlement}), 200


@app.route("/api/bills/<bill_id>/settle-offline", methods=["POST"])
def settle_member_offline(bill_id):
    """
    HTTP API endpoint to record an offline payment (Cash, UPI, Direct Transfer)
    for an individual member without initiating a PayPal transaction.
    """
    try:
        data = request.get_json(silent=True) or {}
        member_name = (data.get("member_name") or "").strip()

        if not bill_id or not member_name:
            return jsonify({
                "success": False,
                "error": "bill_id and member_name are required."
            }), 400

        member = bill_store.get_member(bill_id, member_name)
        if not member:
            return jsonify({"success": False, "error": f"Member '{member_name}' not found on this bill."}), 404

        if member["status"] == "paid":
            return jsonify({
                "success": False,
                "error": f"{member_name} is already marked as paid."
            }), 400

        success = bill_store.mark_member_offline_paid(bill_id, member["member_name"])
        if not success:
            return jsonify({"success": False, "error": "Failed to record offline payment."}), 500

        settlement = bill_store.get_settlement_summary(bill_id)
        return jsonify({
            "success": True,
            "bill_id": bill_id,
            "member_name": member["member_name"],
            "status": "paid",
            "payment_method": "offline",
            "settlement": settlement
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/bills/<bill_id>/revert-offline", methods=["POST"])
def revert_member_offline(bill_id):
    """
    HTTP API endpoint to revert an accidental offline payment back to pending.
    Strictly verifies payment_method == 'offline'. Reverting PayPal captures via this endpoint is prohibited.
    """
    try:
        data = request.get_json(silent=True) or {}
        member_name = (data.get("member_name") or "").strip()

        if not bill_id or not member_name:
            return jsonify({
                "success": False,
                "error": "bill_id and member_name are required."
            }), 400

        member = bill_store.get_member(bill_id, member_name)
        if not member:
            return jsonify({"success": False, "error": f"Member '{member_name}' not found on this bill."}), 404

        if member["status"] != "paid":
            return jsonify({
                "success": False,
                "error": f"{member_name} is not currently marked as paid."
            }), 400

        # Disallow reverting PayPal payments through offline endpoint
        if member.get("payment_method") == "paypal" or member.get("paypal_order_id") or member.get("paypal_capture_id"):
            return jsonify({
                "success": False,
                "error": "Cannot revert a payment completed through PayPal."
            }), 400

        if member.get("payment_method") != "offline":
            return jsonify({
                "success": False,
                "error": "Only offline/cash payments can be reverted here."
            }), 400

        success = bill_store.revert_member_offline(bill_id, member["member_name"])
        if not success:
            return jsonify({"success": False, "error": "Failed to revert offline payment."}), 500

        settlement = bill_store.get_settlement_summary(bill_id)
        return jsonify({
            "success": True,
            "bill_id": bill_id,
            "member_name": member["member_name"],
            "status": "pending",
            "payment_method": None,
            "settlement": settlement
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500



@app.route("/api/ai/assign", methods=["POST"])
def ai_assign():
    """
    HTTP API endpoint for AI-powered natural-language item assignment.
    Calls Gemini API to match plain text descriptions to existing items and members.
    Strictly performs natural-language understanding; NO calculations.
    """
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "error": "No valid JSON data provided."}), 400

        members = data.get("members", [])
        items = data.get("items", [])
        description = data.get("description", "")

        result = ai_service.parse_bill_description(
            members=members,
            items=items,
            description=description
        )
        return jsonify(result), 200

    except ai_service.MissingApiKeyError as key_err:
        return jsonify({
            "success": False,
            "error": str(key_err),
            "is_missing_api_key": True
        }), 400
    except ValueError as val_err:
        return jsonify({"success": False, "error": str(val_err)}), 400
    except ai_service.AiServiceError as ai_err:
        return jsonify({"success": False, "error": str(ai_err)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/ai/parse-bill", methods=["POST"])
def ai_parse_bill():
    """
    HTTP API endpoint for one-sentence AI bill creation.
    Extracts dishes, prices in INR, and participants directly from natural language.
    """
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "error": "No valid JSON data provided."}), 400

        description = (data.get("description") or "").strip()
        speaker_name = (data.get("speaker_name") or "").strip()
        members = data.get("members", [])

        if not description:
            return jsonify({"success": False, "error": "Please enter a description of your bill."}), 400

        result = ai_service.parse_complete_bill(
            description=description,
            speaker_name=speaker_name,
            members=members
        )
        return jsonify(result), 200

    except ai_service.MissingApiKeyError as key_err:
        return jsonify({
            "success": False,
            "error": str(key_err),
            "is_missing_api_key": True
        }), 400
    except ValueError as val_err:
        return jsonify({"success": False, "error": str(val_err)}), 400
    except ai_service.AiServiceError as ai_err:
        return jsonify({"success": False, "error": str(ai_err)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


@app.route("/api/ai/scan-receipt", methods=["POST"])
def ai_scan_receipt():
    """
    HTTP API endpoint for Gemini-powered receipt scanning.
    Accepts:
    - multipart/form-data with 'receipt' or 'file' (and optional 'members')
    - OR JSON with 'image' (base64 string), 'mime_type', and optional 'members'
    """
    try:
        image_bytes = None
        mime_type = "image/jpeg"
        members = []

        if request.content_type and "multipart/form-data" in request.content_type:
            if "receipt" not in request.files and "file" not in request.files:
                return jsonify({"success": False, "error": "No receipt image uploaded. Please choose a file."}), 400

            file = request.files.get("receipt") or request.files.get("file")
            if not file or file.filename == "":
                return jsonify({"success": False, "error": "No receipt file selected."}), 400

            filename = file.filename.lower()
            allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
            ext = os.path.splitext(filename)[1]
            if ext not in allowed_exts:
                return jsonify({
                    "success": False,
                    "error": f"Unsupported file type '{ext}'. Please upload a JPG, JPEG, or PNG receipt image."
                }), 400

            mime_type = file.mimetype or "image/jpeg"
            if mime_type == "application/octet-stream":
                if ext in [".jpg", ".jpeg"]:
                    mime_type = "image/jpeg"
                elif ext == ".png":
                    mime_type = "image/png"
                elif ext == ".webp":
                    mime_type = "image/webp"

            image_bytes = file.read()
            raw_members = request.form.get("members", "")
            if raw_members:
                if raw_members.startswith("["):
                    try:
                        members = json.loads(raw_members)
                    except Exception:
                        members = [m.strip() for m in raw_members.split(",") if m.strip()]
                else:
                    members = [m.strip() for m in raw_members.split(",") if m.strip()]

        elif request.is_json:
            data = request.get_json(silent=True) or {}
            b64_str = data.get("image") or data.get("file")
            if not b64_str:
                return jsonify({"success": False, "error": "No image data provided in JSON request."}), 400

            if "," in b64_str:
                header, b64_str = b64_str.split(",", 1)
                if "image/png" in header:
                    mime_type = "image/png"
                elif "image/webp" in header:
                    mime_type = "image/webp"
                else:
                    mime_type = "image/jpeg"
            else:
                mime_type = data.get("mime_type", "image/jpeg")

            try:
                image_bytes = base64.b64decode(b64_str)
            except Exception:
                return jsonify({"success": False, "error": "Invalid base64 image data."}), 400

            raw_members = data.get("members", [])
            if isinstance(raw_members, str):
                members = [m.strip() for m in raw_members.split(",") if m.strip()]
            elif isinstance(raw_members, list):
                members = raw_members
        else:
            return jsonify({"success": False, "error": "Expected multipart/form-data or application/json request."}), 400

        if not image_bytes or len(image_bytes) < 100:
            return jsonify({"success": False, "error": "The uploaded receipt file is empty or corrupted."}), 400

        if len(image_bytes) > 10 * 1024 * 1024:
            return jsonify({
                "success": False,
                "error": "The receipt image is too large (maximum allowed size is 10 MB). Please upload a smaller photo."
            }), 400

        result = ai_service.scan_receipt_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            members=members
        )
        return jsonify(result), 200

    except ai_service.MissingApiKeyError as key_err:
        return jsonify({
            "success": False,
            "error": str(key_err),
            "is_missing_api_key": True
        }), 400
    except ValueError as val_err:
        return jsonify({"success": False, "error": str(val_err)}), 400
    except ai_service.AiServiceError as ai_err:
        return jsonify({"success": False, "error": str(ai_err)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500


if __name__ == "__main__":
    # Runs the development server locally on port 5001 (avoids macOS AirPlay port 5000 collision)
    app.run(debug=True, host="127.0.0.1", port=5001)

