"""
FairSplit AI - PayPal Sandbox Checkout Service
Integrates with PayPal Orders v2 API with CAPTURE intent.
Supports individual member share payments with server-side validation and currency conversion.
"""

import os
import time
from typing import Any, Dict, Optional, Tuple
import requests
from dotenv import load_dotenv

load_dotenv()


class PayPalError(Exception):
    """Base error for PayPal service issues."""
    pass


class PayPalAuthError(PayPalError):
    """Raised when authentication against PayPal fails."""
    pass


class PayPalCaptureError(PayPalError):
    """Raised when an order capture fails or verification detects mismatch."""
    pass


class CurrencyConversionError(PayPalError):
    """Raised when currency conversion rate is invalid or missing."""
    pass


def convert_inr_to_usd(amount_inr: float, rate: Optional[float] = None) -> float:
    """
    Module-level helper to convert INR to USD.
    Validates rate > 0 and amount > 0.
    """
    if rate is not None:
        try:
            eff_rate = float(rate)
        except (ValueError, TypeError):
            raise CurrencyConversionError(f"Invalid exchange rate: {rate}")
        if eff_rate <= 0:
            raise CurrencyConversionError(f"Exchange rate must be positive: {rate}")
    else:
        raw_rate = os.getenv("INR_TO_USD_RATE", "0.012")
        try:
            eff_rate = float(raw_rate)
        except (ValueError, TypeError):
            eff_rate = 0.0
        if eff_rate <= 0:
            raise CurrencyConversionError("Missing or non-positive INR_TO_USD_RATE.")

    if amount_inr is None or not isinstance(amount_inr, (int, float)) or amount_inr <= 0:
        raise CurrencyConversionError(f"Invalid INR amount: {amount_inr}")

    val = round(float(amount_inr) * eff_rate, 2)
    return max(0.01, val)


class PayPalService:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        mode: Optional[str] = None,
        inr_to_usd_rate: Optional[float] = None
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._mode = mode
        self._inr_to_usd_rate = inr_to_usd_rate

        # Token caching
        self._cached_token = None
        self._token_expires_at = 0

    @property
    def mode(self) -> str:
        if self._mode is not None:
            return self._mode.strip().lower()
        return os.getenv("PAYPAL_MODE", "sandbox").strip().lower()

    @property
    def client_id(self) -> str:
        if self._client_id is not None:
            return self._client_id.strip()
        return os.getenv("PAYPAL_CLIENT_ID", "").strip()

    @property
    def client_secret(self) -> str:
        if self._client_secret is not None:
            return self._client_secret.strip()
        return os.getenv("PAYPAL_CLIENT_SECRET", "").strip()

    @property
    def inr_to_usd_rate(self) -> float:
        if self._inr_to_usd_rate is not None:
            return self._inr_to_usd_rate
        raw_rate = os.getenv("INR_TO_USD_RATE", "0.012").strip()
        try:
            return float(raw_rate)
        except (ValueError, TypeError):
            return 0.0

    @property
    def base_url(self) -> str:
        if self.mode == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    def is_configured(self) -> bool:
        """Returns True if client credentials and exchange rate are set."""
        return bool(
            self.client_id and
            self.client_secret and
            self.client_id not in ["your_actual_client_id", "your_paypal_client_id", ""] and
            self.inr_to_usd_rate > 0
        )

    def get_public_config(self) -> Dict[str, Any]:
        """
        Returns public PayPal configuration for the frontend SDK.
        NEVER exposes the client secret.
        """
        return {
            "client_id": self.client_id if self.is_configured() else "",
            "currency": "USD",
            "inr_to_usd_rate": self.inr_to_usd_rate,
            "mode": self.mode,
            "is_enabled": self.is_configured(),
            "currency_disclosure": f"1 INR = ${self.inr_to_usd_rate:.4f} USD"
        }

    def convert_inr_to_usd(self, amount_inr: float) -> Tuple[float, str]:
        """
        Converts an INR rupee amount to USD using the configured exchange rate.
        Enforces rate > 0 and returns (float_usd, formatted_usd_str).
        """
        if self.inr_to_usd_rate <= 0:
            raise CurrencyConversionError(
                "Invalid or missing INR-to-USD conversion rate. PayPal checkout is temporarily unavailable."
            )

        if amount_inr is None or amount_inr < 0:
            raise ValueError(f"Invalid INR amount: {amount_inr}")

        raw_usd = amount_inr * self.inr_to_usd_rate
        rounded_usd = round(raw_usd, 2)
        # Ensure at least $0.01 for any positive INR amount
        if amount_inr > 0 and rounded_usd <= 0.0:
            rounded_usd = 0.01

        return rounded_usd, f"{rounded_usd:.2f}"

    def get_access_token(self, session: Optional[Any] = None) -> str:
        """
        Retrieves or refreshes an OAuth2 Bearer token from PayPal Sandbox.
        """
        now = time.time()
        if self._cached_token and now < self._token_expires_at - 60:
            return self._cached_token

        if not self.is_configured():
            raise PayPalAuthError(
                "PayPal Sandbox credentials are not configured. Please set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env"
            )

        token_url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US"
        }
        data = {"grant_type": "client_credentials"}

        http = session or requests
        try:
            r = http.post(
                token_url,
                auth=(self.client_id, self.client_secret),
                data=data,
                headers=headers,
                timeout=15
            )
            if r.status_code != 200:
                raise PayPalAuthError(
                    f"PayPal authentication failed (Status {r.status_code}): {r.text[:150]}"
                )

            res = r.json()
            token = res.get("access_token")
            expires_in = int(res.get("expires_in", 3600))

            if not token:
                raise PayPalAuthError("No access_token returned by PayPal.")

            self._cached_token = token
            self._token_expires_at = now + expires_in
            return token

        except requests.exceptions.RequestException as e:
            raise PayPalAuthError(f"Network error while authenticating with PayPal Sandbox: {str(e)}")

    def create_individual_order(
        self,
        amount_usd: float,
        member_name: str,
        bill_title: str,
        bill_id: str,
        session: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Creates a separate PayPal order for an individual member's share.
        Uses PayPal Orders v2 API with intent: CAPTURE.
        """
        token = self.get_access_token(session=session)
        orders_url = f"{self.base_url}/v2/checkout/orders"

        clean_title = (bill_title or "Restaurant Bill").strip()[:50]
        clean_member = member_name.strip()

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"{bill_id}:{clean_member}",
                    "description": f"FairSplit: {clean_member}'s share for {clean_title}",
                    "custom_id": f"{bill_id}|{clean_member}",
                    "amount": {
                        "currency_code": "USD",
                        "value": f"{amount_usd:.2f}"
                    }
                }
            ],
            "application_context": {
                "brand_name": "FairSplit AI",
                "landing_page": "NO_PREFERENCE",
                "user_action": "PAY_NOW"
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        http = session or requests
        try:
            r = http.post(orders_url, json=payload, headers=headers, timeout=15)
            if r.status_code not in [200, 201]:
                raise PayPalError(f"Failed to create PayPal order (Status {r.status_code}): {r.text[:200]}")

            data = r.json()
            order_id = data.get("id")
            if not order_id:
                raise PayPalError("PayPal did not return an order id.")

            return {
                "order_id": order_id,
                "status": data.get("status", "CREATED"),
                "amount_usd": amount_usd,
                "currency": "USD"
            }

        except requests.exceptions.RequestException as e:
            raise PayPalError(f"Network error while creating PayPal order: {str(e)}")

    def capture_order(
        self,
        order_id: str,
        expected_amount_usd: float,
        session: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Captures an approved PayPal order and verifies that the captured amount and currency
        match the server's expected amount.
        """
        token = self.get_access_token(session=session)
        capture_url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        http = session or requests
        try:
            r = http.post(capture_url, headers=headers, timeout=15)
            if r.status_code not in [200, 201]:
                raise PayPalCaptureError(
                    f"PayPal capture request failed (Status {r.status_code}): {r.text[:200]}"
                )

            data = r.json()
            order_status = data.get("status")

            if order_status != "COMPLETED":
                raise PayPalCaptureError(
                    f"Payment capture incomplete. PayPal order status is '{order_status}'."
                )

            # Verification of captured unit
            purchase_units = data.get("purchase_units", [])
            if not purchase_units:
                raise PayPalCaptureError("Missing purchase_units in PayPal capture response.")

            unit = purchase_units[0]
            payments = unit.get("payments", {})
            captures = payments.get("captures", [])

            if not captures:
                raise PayPalCaptureError("No capture record returned by PayPal.")

            capture = captures[0]
            capture_id = capture.get("id")
            capture_status = capture.get("status")

            if capture_status != "COMPLETED":
                raise PayPalCaptureError(f"Capture status is '{capture_status}', expected 'COMPLETED'.")

            # Verify currency and captured amount
            amt_info = capture.get("amount", {})
            captured_currency = amt_info.get("currency_code")
            captured_val_str = amt_info.get("value")

            try:
                captured_val = float(captured_val_str)
            except (ValueError, TypeError):
                captured_val = 0.0

            if captured_currency != "USD":
                raise PayPalCaptureError(
                    f"Currency mismatch: expected 'USD', PayPal returned '{captured_currency}'."
                )

            # Allow 1 cent tolerance for rounding if any
            if abs(captured_val - expected_amount_usd) > 0.02:
                raise PayPalCaptureError(
                    f"Captured amount mismatch: expected ${expected_amount_usd:.2f}, PayPal captured ${captured_val:.2f}."
                )

            payer = data.get("payer", {})
            payer_email = payer.get("email_address", "")
            payer_name = ""
            if "name" in payer:
                given = payer["name"].get("given_name", "")
                surname = payer["name"].get("surname", "")
                payer_name = f"{given} {surname}".strip()

            return {
                "success": True,
                "order_id": order_id,
                "capture_id": capture_id,
                "status": "COMPLETED",
                "amount_usd": captured_val,
                "currency": captured_currency,
                "payer_email": payer_email,
                "payer_name": payer_name
            }

        except requests.exceptions.RequestException as e:
            raise PayPalCaptureError(f"Network error while capturing PayPal order: {str(e)}")


# Global service instance and aliases
paypal_service = PayPalService()
paypal_client = paypal_service
PayPalClient = PayPalService
