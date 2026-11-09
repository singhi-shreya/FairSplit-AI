"""
FairSplit AI - Natural-Language Item & Bill Understanding Service

Uses Google's Gemini API to interpret natural-language descriptions.

Capabilities:
1. Complete AI Bill Entry: Extracts members, dishes, prices in INR, and participant assignments
   directly from an ordinary sentence (e.g. "Rahul ate pizza which was 600 rupees, Priya and I shared 400 rupees pasta, and we all shared Coke worth 180 rupees.").
2. Item Assignment (Existing Mode): Maps descriptions to existing bill items.

CRITICAL DESIGN RULES:
- Fast REST execution using requests with gemini-3.5-flash-lite.
- Strict post-validation on backend.
- Purely natural-language interpretation: NO financial calculations (Python calculation engine remains authoritative).
- Ambiguity and missing price detection.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Load variables from .env file if present
load_dotenv()


class MissingApiKeyError(Exception):
    """Raised when the Gemini API key is not found in the environment."""
    pass


class AiServiceError(Exception):
    """Raised when an error occurs during AI processing."""
    pass


SYSTEM_INSTRUCTION_ASSIGN = """
You are the AI Assistant for FairSplit AI, a group expense-splitting web app.
Your only job is to understand who ordered or shared which dishes from a natural-language description.

You are given:
1. VALID GROUP MEMBERS: A list of existing members.
2. VALID BILL ITEMS: A list of existing bill item names and their prices.
3. USER'S DESCRIPTION: Natural language text explaining who ordered what.

STRICT INSTRUCTIONS:
1. ONLY assign people who are in the VALID GROUP MEMBERS list to items in the VALID BILL ITEMS list.
2. DO NOT calculate prices, tax, tips, or subtotals. Only assign participants.
3. HANDLE AMBIGUITY STRICTLY:
   - If the description uses "we" or "they" without clearly defining who is included, flag it as an ambiguity.
   - If the description says "Priya and I shared the pizza", determine if "I" is unambiguous by elimination. If ambiguous, flag in 'ambiguities'.
   - If a person is mentioned who is NOT in the VALID GROUP MEMBERS list, add their name to 'unrecognized_members'.
   - If a dish is mentioned that is NOT in the VALID BILL ITEMS list, add it to 'unrecognized_items'.
   - If any bill items from the VALID BILL ITEMS list are not mentioned in the description, add their names to 'unmentioned_items'.
4. Do NOT guess or invent participants for uncertain items.
5. If there are ANY ambiguities, unrecognized members, unrecognized items, or contradictions, set 'needs_clarification' to true and formulate specific questions in 'clarifications'.

RESPONSE FORMAT (JSON ONLY):
{
  "assignments": [
    {
      "item": "exact item name from bill",
      "participants": ["exact member name 1", "exact member name 2"]
    }
  ],
  "ambiguities": ["description of any ambiguous pronoun or conflicting statement"],
  "unrecognized_members": ["person name mentioned in text but not in group"],
  "unrecognized_items": ["item name mentioned in text but not on bill"],
  "unmentioned_items": ["bill item not mentioned in user text"],
  "needs_clarification": boolean,
  "clarifications": ["specific questions to ask the user to clarify ambiguity"]
}
"""

SYSTEM_INSTRUCTION_COMPLETE_BILL = """
You are the AI Restaurant Bill Parser for FairSplit AI.
Your job is to read an ordinary natural-language description of a restaurant meal and extract:
1. The group members sharing the bill.
2. The food items/dishes ordered and their prices in Indian Rupees (INR).
3. Which members ate or shared each dish.

Speaker hint (the person who is speaking/writing, e.g. 'I' or 'me'):
"{speaker_name}"

Known members hint (if any):
{members_hint}

STRICT EXTRACTION RULES:
1. MEMBERS:
   - Extract all person names mentioned in the text (e.g. "Rahul", "Priya").
   - If the text uses "I", "me", "my", or "myself":
     - If the speaker hint is provided and not empty, use that name.
     - If no speaker hint is provided, label this member as "I (Speaker)" and add a clarification in 'clarifications' asking: "Please tell us who 'I' refers to."
   - Do NOT invent fictional members.
2. ITEMS & PRICES:
   - Extract every dish or drink mentioned.
   - Extract its price as a positive number in Indian Rupees. Understand Indian English and rupee notation:
     '600 rupees', '600rs', 'Rs. 400', '₹120', 'coke worth 180', 'costing 250', 'for 50', etc.
   - If a dish is mentioned WITHOUT any price (e.g. "Rahul also had dessert"), set price to 0.0 and add a clarification in 'clarifications': "Price for '<dish name>' was not mentioned. Please enter its price."
3. ASSIGNMENTS:
   - Identify who ate or shared each item.
   - "we all", "all of us", "all three of us", "everyone": assign to ALL extracted members.
   - If someone shared a dish (e.g. "Priya and I shared pasta"), assign both.
   - If it is ambiguous who "we" refers to, list the ambiguity in 'ambiguities' and 'clarifications'.
4. CONTRADICTIONS:
   - If the description has contradictory statements (e.g. "Rahul had the pizza alone" and later "Priya also ate pizza"), flag in 'ambiguities'.

RESPONSE FORMAT (JSON ONLY):
{
  "members": ["Rahul", "Priya", "Sneha"],
  "items": [
    {
      "name": "Pizza",
      "price": 600.0,
      "shared_by": ["Rahul"]
    }
  ],
  "ambiguities": [],
  "needs_clarification": false,
  "clarifications": []
}
"""

SYSTEM_INSTRUCTION_RECEIPT_SCAN = """
You are the Expert Receipt & Dining Bill OCR Intelligence for FairSplit AI.
Your job is to examine an image of a restaurant bill, food invoice, or dining receipt and extract all relevant billing details into a structured JSON response.

EXTRACTION INSTRUCTIONS:
1. VALIDITY & READABILITY:
   - Determine if the image is a dining/restaurant receipt, food invoice, or restaurant bill.
   - Set "is_receipt": true if it is a dining bill or food receipt; false if it is unrelated (e.g. a random photo, pet, screenshot, non-receipt document).
   - Set "is_readable": true if the text, dishes, and amounts are clear enough to read; false if the image is too blurry, dark, cutoff, or heavily degraded.
   - If not a receipt or not readable, explain in "clarifications" and return empty items.

2. RESTAURANT & HEADER:
   - Extract "restaurant_name" (string, or null if not found/unclear).

3. ITEMS, QUANTITIES & PRICES:
   - Extract each purchased food or beverage item.
   - "name": Clean item description (e.g., "Margherita Pizza", "Cold Coffee", "Garlic Bread").
   - "quantity": Integer quantity ordered (default 1 if not explicitly printed or unclear).
   - "unit_price": Individual item unit price in Indian Rupees (INR) as a float (e.g., 250.0). If unit price is not printed, set to total_price / quantity.
   - "total_price": Total line price in INR as a float (e.g. 2 x 250 = 500.0).
   - "has_uncertain_price": true if the price is smudged, torn, or ambiguous; otherwise false.
   - "has_uncertain_name": true if the name is cut off or barely legible; otherwise false.
   - If a line item does not have a readable price, set "total_price": 0.0 and "has_uncertain_price": true.
   - DO NOT automatically assign people/participants. Leave participants empty.

4. TOTALS, TAXES & CHARGES:
   - "subtotal": Subtotal amount before taxes/tips (float, or null if missing).
   - "tax_amount": Total tax amount (GST, CGST, SGST, VAT) in INR as float (0.0 if not listed).
   - "tax_percentage": Tax percentage if printed (e.g. 5.0 for 5% GST, 18.0 for 18% GST; or null if not stated).
   - "tip_amount": Service charge or tip in INR as float (0.0 if none).
   - "tip_percentage": Tip or service charge percentage if stated (e.g. 10.0, or null).
   - "grand_total": Final bill amount in INR as float (or null if missing).

5. ACCURACY & CAUTION:
   - NEVER invent or hallucinate items, prices, or taxes.
   - If any values are missing, uncertain, or if the sum of line items does not equal the printed subtotal or grand total, note this in "clarifications".

RESPONSE FORMAT (JSON ONLY):
{
  "is_receipt": boolean,
  "is_readable": boolean,
  "restaurant_name": string or null,
  "items": [
    {
      "name": "Item Description",
      "quantity": 1,
      "unit_price": 250.0,
      "total_price": 250.0,
      "has_uncertain_price": false,
      "has_uncertain_name": false
    }
  ],
  "subtotal": 500.0,
  "tax_amount": 25.0,
  "tax_percentage": 5.0,
  "tip_amount": 0.0,
  "tip_percentage": 0.0,
  "grand_total": 525.0,
  "clarifications": []
}
"""


def _find_canonical_item(name: str, valid_items: List[Dict[str, Any]]) -> Optional[str]:
    """Matches a parsed item name to a canonical bill item name (case-insensitive & substring)."""
    clean_target = name.strip().lower()
    
    # 1. Exact match (case-insensitive)
    for it in valid_items:
        it_name = it["name"].strip()
        if it_name.lower() == clean_target:
            return it_name
            
    # 2. Substring / contains match
    for it in valid_items:
        it_name = it["name"].strip()
        if clean_target in it_name.lower() or it_name.lower() in clean_target:
            return it_name
            
    return None


def _find_canonical_member(name: str, valid_members: List[str]) -> Optional[str]:
    """Matches a parsed member name to a canonical group member (case-insensitive)."""
    clean_target = name.strip().lower()
    for m in valid_members:
        if m.strip().lower() == clean_target:
            return m.strip()
    return None


def _call_gemini_json(prompt: str, system_instruction: str, client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Executes a structured JSON query to Gemini.
    - If client is injected (tests/mocking): uses client.models.generate_content.
    - If client is None: uses direct REST requests on gemini-3.5-flash-lite.
    """
    # Test / Mock Client Path
    if client is not None:
        try:
            from google.genai import types
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            response_text = response.text.strip()
            clean_text = re.sub(r"^```(json)?\s*", "", response_text, flags=re.MULTILINE)
            clean_text = re.sub(r"```\s*$", "", clean_text, flags=re.MULTILINE).strip()
            return json.loads(clean_text)
        except json.JSONDecodeError:
            raise AiServiceError(f"Gemini returned an invalid non-JSON response: {response_text[:120]}")
        except Exception as e:
            if isinstance(e, (AiServiceError, MissingApiKeyError)):
                raise
            raise AiServiceError(f"Gemini API request failed: {str(e)}")

    # Real Fast REST Path
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        raise MissingApiKeyError(
            "Gemini API key is not configured. Please add your GEMINI_API_KEY to the .env file. "
            "Manual entry is still available."
        )

    import requests

    candidate_models = [
        "gemini-3-flash-preview",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest"
    ]

    last_error = None
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                clean_text = re.sub(r"^```(json)?\s*", "", text, flags=re.MULTILINE)
                clean_text = re.sub(r"```\s*$", "", clean_text, flags=re.MULTILINE).strip()
                return json.loads(clean_text)
            else:
                last_error = f"Status {r.status_code}: {r.text[:120]}"
        except json.JSONDecodeError:
            last_error = f"Invalid JSON returned from model {model_name}"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    raise AiServiceError(f"Gemini API request failed: {last_error}")


def _call_gemini_vision_json(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    system_instruction: str,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Executes a multimodal structured JSON query to Gemini with an image.
    - If client is injected (tests/mocking): uses client.models.generate_content.
    - If client is None: uses direct REST requests with inlineData base64 payload.
    """
    # Test / Mock Client Path
    if client is not None:
        try:
            from google.genai import types
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[image_part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            response_text = response.text.strip()
            clean_text = re.sub(r"^```(json)?\s*", "", response_text, flags=re.MULTILINE)
            clean_text = re.sub(r"```\s*$", "", clean_text, flags=re.MULTILINE).strip()
            return json.loads(clean_text)
        except json.JSONDecodeError:
            raise AiServiceError(f"Gemini returned an invalid non-JSON response: {response_text[:120]}")
        except Exception as e:
            if isinstance(e, (AiServiceError, MissingApiKeyError)):
                raise
            raise AiServiceError(f"Gemini API request failed: {str(e)}")

    # Real Fast REST Path
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        raise MissingApiKeyError(
            "Gemini API key is not configured. Please add your GEMINI_API_KEY to the .env file. "
            "Manual entry is still available."
        )

    import base64
    import requests

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    candidate_models = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-flash-latest"
    ]

    last_error = None
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64_image
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                clean_text = re.sub(r"^```(json)?\s*", "", text, flags=re.MULTILINE)
                clean_text = re.sub(r"```\s*$", "", clean_text, flags=re.MULTILINE).strip()
                return json.loads(clean_text)
            else:
                last_error = f"Status {r.status_code}: {r.text[:120]}"
        except json.JSONDecodeError:
            last_error = f"Invalid JSON returned from model {model_name}"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    raise AiServiceError(f"Gemini Vision API request failed: {last_error}")


def validate_and_sanitize_ai_response(
    raw_response: Dict[str, Any],
    valid_members: List[str],
    valid_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Deterministic backend validation of Gemini's response when matching existing items.
    """
    if not isinstance(raw_response, dict):
        raise AiServiceError("AI response was not a valid structured dictionary.")

    raw_assignments = raw_response.get("assignments", [])
    if not isinstance(raw_assignments, list):
        raw_assignments = []

    ambiguities = [str(a) for a in raw_response.get("ambiguities", []) if a]
    unrecognized_members = [str(m) for m in raw_response.get("unrecognized_members", []) if m]
    unrecognized_items = [str(i) for i in raw_response.get("unrecognized_items", []) if i]
    unmentioned_items = [str(u) for u in raw_response.get("unmentioned_items", []) if u]
    clarifications = [str(c) for c in raw_response.get("clarifications", []) if c]
    needs_clarification = bool(raw_response.get("needs_clarification", False))

    sanitized_assignments = []
    assigned_item_names = set()

    for entry in raw_assignments:
        if not isinstance(entry, dict):
            continue

        raw_item_name = str(entry.get("item", "")).strip()
        canonical_item = _find_canonical_item(raw_item_name, valid_items)
        if not canonical_item:
            if raw_item_name and raw_item_name not in unrecognized_items:
                unrecognized_items.append(raw_item_name)
                clarifications.append(f"Dish '{raw_item_name}' was mentioned but is not in your bill items.")
            continue

        raw_participants = entry.get("participants", [])
        if not isinstance(raw_participants, list):
            raw_participants = []

        canonical_participants = []
        for p in raw_participants:
            c_mem = _find_canonical_member(str(p), valid_members)
            if c_mem:
                if c_mem not in canonical_participants:
                    canonical_participants.append(c_mem)
            else:
                unrec_name = str(p).strip()
                if unrec_name and unrec_name.lower() not in ["i", "we", "they"]:
                    if unrec_name not in unrecognized_members:
                        unrecognized_members.append(unrec_name)
                        clarifications.append(f"Person '{unrec_name}' was mentioned but is not in your group.")

        if canonical_participants:
            sanitized_assignments.append({
                "item": canonical_item,
                "participants": canonical_participants
            })
            assigned_item_names.add(canonical_item.lower())

    for it in valid_items:
        it_name = it["name"].strip()
        if it_name.lower() not in assigned_item_names:
            if it_name not in unmentioned_items:
                unmentioned_items.append(it_name)

    if ambiguities or unrecognized_members or unrecognized_items:
        needs_clarification = True

    if ambiguities and not any("ambiguous" in c.lower() for c in clarifications):
        for amb in ambiguities:
            clarifications.append(f"Ambiguity detected: {amb}")

    deduped_clarifications = []
    for c in clarifications:
        if c not in deduped_clarifications:
            deduped_clarifications.append(c)

    return {
        "success": True,
        "assignments": sanitized_assignments,
        "ambiguities": ambiguities,
        "unrecognized_members": unrecognized_members,
        "unrecognized_items": unrecognized_items,
        "unmentioned_items": unmentioned_items,
        "needs_clarification": needs_clarification or (len(deduped_clarifications) > 0),
        "clarifications": deduped_clarifications
    }


def parse_bill_description(
    members: List[str],
    items: List[Dict[str, Any]],
    description: str,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Parses natural-language description and matches against EXISTING bill items.
    """
    if not members or not isinstance(members, list):
        raise ValueError("Please add group members first.")

    clean_members = [m.strip() for m in members if isinstance(m, str) and m.strip()]
    if not clean_members:
        raise ValueError("Please add at least one group member.")

    if not items or not isinstance(items, list):
        raise ValueError("Please add bill items first.")

    clean_items = []
    for it in items:
        if isinstance(it, dict) and it.get("name"):
            clean_items.append({
                "name": str(it["name"]).strip(),
                "price": float(it.get("price", 0.0))
            })

    if not clean_items:
        raise ValueError("Please add at least one bill item.")

    clean_desc = (description or "").strip()
    if not clean_desc:
        raise ValueError("Please enter a description of who ordered what.")

    user_prompt = f"""
VALID GROUP MEMBERS:
{json.dumps(clean_members, indent=2)}

VALID BILL ITEMS:
{json.dumps([{"name": it["name"], "price": it["price"]} for it in clean_items], indent=2)}

USER DESCRIPTION:
"{clean_desc}"

Interpret this description according to the system instructions and return ONLY the JSON object.
"""

    parsed_json = _call_gemini_json(user_prompt, SYSTEM_INSTRUCTION_ASSIGN, client=client)
    return validate_and_sanitize_ai_response(parsed_json, clean_members, clean_items)


def parse_complete_bill(
    description: str,
    speaker_name: str = "",
    members: Optional[List[str]] = None,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    MODE 2: AI-Powered Full Bill Entry.
    Extracts members, items, prices in INR, and participants from a single natural-language description.
    
    Example input:
    "Rahul ate pizza which was 600 rupees, Priya and I shared 400 rupees pasta, and we all shared Coke worth 180 rupees."
    """
    clean_desc = (description or "").strip()
    if not clean_desc:
        raise ValueError("Please enter a description of your bill.")

    clean_speaker = (speaker_name or "").strip()
    clean_members = [m.strip() for m in (members or []) if isinstance(m, str) and m.strip()]

    system_instruction = SYSTEM_INSTRUCTION_COMPLETE_BILL.replace(
        '"{speaker_name}"', json.dumps(clean_speaker)
    ).replace(
        "{members_hint}", json.dumps(clean_members)
    )

    user_prompt = f"""
USER DESCRIPTION:
"{clean_desc}"

Extract the group members, food dishes with their INR prices, and who shared each dish.
Return ONLY valid JSON matching the schema.
"""

    raw_response = _call_gemini_json(user_prompt, system_instruction, client=client)

    if not isinstance(raw_response, dict):
        raise AiServiceError("AI response was not a valid structured dictionary.")

    # 1. Process Extracted Members
    raw_members = raw_response.get("members", [])
    if not isinstance(raw_members, list):
        raw_members = []

    extracted_members = []
    seen_members = set()

    for m in raw_members:
        clean_m = str(m).strip()
        if clean_m and clean_m.lower() not in seen_members:
            extracted_members.append(clean_m)
            seen_members.add(clean_m.lower())

    # If speaker name was provided, ensure it's in the members list
    if clean_speaker and clean_speaker.lower() not in seen_members:
        extracted_members.append(clean_speaker)
        seen_members.add(clean_speaker.lower())

    # 2. Process Items & Prices
    raw_items = raw_response.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    ambiguities = [str(a) for a in raw_response.get("ambiguities", []) if a]
    clarifications = [str(c) for c in raw_response.get("clarifications", []) if c]
    needs_clarification = bool(raw_response.get("needs_clarification", False))

    sanitized_items = []
    subtotal = 0.0

    for idx, it in enumerate(raw_items, start=1):
        if not isinstance(it, dict):
            continue

        raw_name = str(it.get("name", f"Item #{idx}")).strip() or f"Item #{idx}"
        dish_name = raw_name.title()

        # Parse Price
        raw_price = it.get("price")
        price_val = 0.0
        has_missing_price = False

        try:
            if raw_price is not None and float(raw_price) > 0:
                price_val = round(float(raw_price), 2)
            else:
                has_missing_price = True
        except (ValueError, TypeError):
            has_missing_price = True

        if has_missing_price:
            if not any(dish_name.lower() in c.lower() for c in clarifications):
                clarifications.append(f"Price for '{dish_name}' is missing. Please enter its price.")
            needs_clarification = True

        # Parse Participants
        raw_shared = it.get("shared_by", [])
        if not isinstance(raw_shared, list):
            raw_shared = []

        canonical_participants = []
        for p in raw_shared:
            p_str = str(p).strip()
            # Check against members
            match = None
            for mem in extracted_members:
                if mem.lower() == p_str.lower():
                    match = mem
                    break
            if match:
                if match not in canonical_participants:
                    canonical_participants.append(match)
            else:
                # Add to extracted members if it's a genuine name
                if p_str and p_str.lower() not in ["i", "we", "they", "everyone", "all"]:
                    extracted_members.append(p_str)
                    seen_members.add(p_str.lower())
                    canonical_participants.append(p_str)

        # Handle "all" or "everyone"
        if not canonical_participants and any(w in clean_desc.lower() for w in ["all", "everyone"]):
            canonical_participants = list(extracted_members)

        if not canonical_participants:
            clarifications.append(f"Who shared the {dish_name}? Please assign at least one member.")
            needs_clarification = True

        sanitized_items.append({
            "name": dish_name,
            "price": price_val,
            "has_missing_price": has_missing_price,
            "shared_by": canonical_participants
        })
        subtotal += price_val

    # If "I" was used without speaker name
    if any(m.lower() in ["i", "i (speaker)", "me"] for m in extracted_members) and not clean_speaker:
        if not any("who 'i' refers to" in c.lower() for c in clarifications):
            clarifications.append("Who does 'I' refer to? You can edit the member name or enter your name.")
            needs_clarification = True

    # Deduplicate clarifications (case-insensitive & quote-normalized)
    deduped_clarifications = []
    seen_clarif_keys = set()
    for c in clarifications:
        norm = re.sub(r"['\"]", "", c.lower().strip())
        if norm not in seen_clarif_keys:
            seen_clarif_keys.add(norm)
            deduped_clarifications.append(c)

    return {
        "success": True,
        "members": extracted_members,
        "items": sanitized_items,
        "subtotal": round(subtotal, 2),
        "ambiguities": ambiguities,
        "needs_clarification": needs_clarification or (len(deduped_clarifications) > 0),
        "clarifications": deduped_clarifications
    }


def scan_receipt_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    members: Optional[List[str]] = None,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Scans a dining/restaurant receipt image using Gemini Vision AI.
    Extracts:
    - Restaurant name (if visible)
    - Item names, quantities, unit prices, total line prices
    - Subtotal, Tax percentage, Tip percentage, Grand Total
    - Flags uncertain or missing values and total discrepancies
    - Leaves participant assignment empty (user chooses participants in review)
    """
    if not image_bytes:
        raise ValueError("No receipt image provided. Please upload a receipt file.")

    if len(image_bytes) > 10 * 1024 * 1024:
        raise ValueError("Receipt image exceeds maximum size of 10 MB. Please upload a smaller photo.")

    clean_mime = (mime_type or "image/jpeg").lower().strip()
    if clean_mime not in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
        raise ValueError("Unsupported file format. Please upload a JPG, JPEG, or PNG receipt image.")

    user_prompt = """Analyze this restaurant bill or dining receipt image.
Extract the restaurant name, list of ordered items, item quantities, unit prices, line item total prices, subtotal, tax, tip/service charge, and grand total in INR.
Return ONLY valid JSON matching the schema."""

    raw_response = _call_gemini_vision_json(
        image_bytes=image_bytes,
        mime_type=clean_mime,
        prompt=user_prompt,
        system_instruction=SYSTEM_INSTRUCTION_RECEIPT_SCAN,
        client=client
    )

    if not isinstance(raw_response, dict):
        raise AiServiceError("AI vision response was not a valid structured dictionary.")

    # 1. Check validity: is it a receipt?
    is_receipt = raw_response.get("is_receipt")
    if is_receipt is False:
        raise ValueError(
            "The uploaded image does not appear to be a dining or restaurant receipt. "
            "Please upload a clear photo of your food bill."
        )

    # 2. Check readability
    is_readable = raw_response.get("is_readable", True)
    clarifications = [str(c).strip() for c in raw_response.get("clarifications", []) if c and str(c).strip()]

    if is_readable is False and not any("readable" in c.lower() or "blurry" in c.lower() for c in clarifications):
        clarifications.append("The receipt image is blurry or difficult to read. Please verify all extracted items and prices.")

    # 3. Restaurant name
    raw_restaurant = raw_response.get("restaurant_name")
    restaurant_name = str(raw_restaurant).strip() if raw_restaurant else ""

    # 4. Process Items
    raw_items = raw_response.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    sanitized_items = []
    calculated_subtotal = 0.0

    for idx, it in enumerate(raw_items, start=1):
        if not isinstance(it, dict):
            continue

        raw_name = str(it.get("name", "")).strip()
        dish_name = raw_name.title() if raw_name else f"Item #{idx}"

        # Quantity (default 1)
        raw_qty = it.get("quantity", 1)
        try:
            qty = max(1, int(raw_qty))
        except (ValueError, TypeError):
            qty = 1

        # Prices
        raw_total_price = it.get("total_price")
        raw_unit_price = it.get("unit_price")

        price_val = 0.0
        unit_val = 0.0
        has_missing_price = False

        try:
            if raw_total_price is not None and float(raw_total_price) > 0:
                price_val = round(float(raw_total_price), 2)
                unit_val = round(price_val / qty, 2)
            elif raw_unit_price is not None and float(raw_unit_price) > 0:
                unit_val = round(float(raw_unit_price), 2)
                price_val = round(unit_val * qty, 2)
            else:
                has_missing_price = True
        except (ValueError, TypeError):
            has_missing_price = True

        if has_missing_price:
            if not any(dish_name.lower() in c.lower() for c in clarifications):
                clarifications.append(f"Price for '{dish_name}' is missing or unreadable. Please enter its price.")

        sanitized_items.append({
            "name": dish_name,
            "quantity": qty,
            "unit_price": unit_val,
            "price": price_val,
            "has_missing_price": has_missing_price,
            "shared_by": []  # Empty: user assigns participants
        })
        calculated_subtotal += price_val

    # 5. Process Tax & Tip
    calculated_subtotal = round(calculated_subtotal, 2)

    raw_tax_pct = raw_response.get("tax_percentage")
    raw_tax_amt = raw_response.get("tax_amount")
    tax_percentage = 0.0

    try:
        if raw_tax_pct is not None and float(raw_tax_pct) > 0:
            tax_percentage = round(float(raw_tax_pct), 1)
        elif raw_tax_amt is not None and float(raw_tax_amt) > 0 and calculated_subtotal > 0:
            tax_percentage = round((float(raw_tax_amt) / calculated_subtotal) * 100, 1)
    except (ValueError, TypeError):
        tax_percentage = 0.0

    raw_tip_pct = raw_response.get("tip_percentage")
    raw_tip_amt = raw_response.get("tip_amount")
    tip_percentage = 0.0

    try:
        if raw_tip_pct is not None and float(raw_tip_pct) > 0:
            tip_percentage = round(float(raw_tip_pct), 1)
        elif raw_tip_amt is not None and float(raw_tip_amt) > 0 and calculated_subtotal > 0:
            tip_percentage = round((float(raw_tip_amt) / calculated_subtotal) * 100, 1)
    except (ValueError, TypeError):
        tip_percentage = 0.0

    # 6. Verify Printed Subtotal & Grand Total for discrepancies
    printed_subtotal = None
    try:
        raw_sub = raw_response.get("subtotal")
        if raw_sub is not None and float(raw_sub) > 0:
            printed_subtotal = round(float(raw_sub), 2)
    except (ValueError, TypeError):
        printed_subtotal = None

    printed_grand_total = None
    try:
        raw_gt = raw_response.get("grand_total")
        if raw_gt is not None and float(raw_gt) > 0:
            printed_grand_total = round(float(raw_gt), 2)
    except (ValueError, TypeError):
        printed_grand_total = None

    if printed_subtotal and abs(calculated_subtotal - printed_subtotal) > 1.0:
        clarifications.append(
            f"Calculated items sum (₹{calculated_subtotal:,.2f}) differs from printed receipt subtotal (₹{printed_subtotal:,.2f}). Please review prices."
        )

    # 7. Clean and prepare members
    clean_members = []
    seen_m = set()
    for m in (members or []):
        if isinstance(m, str) and m.strip():
            cm = m.strip()
            if cm.lower() not in seen_m:
                clean_members.append(cm)
                seen_m.add(cm.lower())

    # Deduplicate clarifications
    deduped_clarifications = []
    seen_keys = set()
    for c in clarifications:
        norm = re.sub(r"['\"]", "", c.lower().strip())
        if norm not in seen_keys:
            seen_keys.add(norm)
            deduped_clarifications.append(c)

    return {
        "success": True,
        "mode": "receipt_scan",
        "restaurant_name": restaurant_name,
        "members": clean_members,
        "items": sanitized_items,
        "subtotal": calculated_subtotal,
        "tax_percentage": tax_percentage,
        "tip_percentage": tip_percentage,
        "printed_subtotal": printed_subtotal,
        "printed_grand_total": printed_grand_total,
        "needs_clarification": len(deduped_clarifications) > 0,
        "clarifications": deduped_clarifications
    }


# Backwards compatibility alias
def parse_natural_language_bill(
    members: List[str],
    description: str,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """Compatibility wrapper calling parse_complete_bill."""
    return parse_complete_bill(description=description, speaker_name="", members=members, client=client)
