"""
FairSplit AI - Persistent Bill and Payment Store
Thread-safe SQLite storage for bills, individual member shares, and PayPal payments.
Prevents duplicate payments and guarantees server-side payment verification.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Default database location in the workspace
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fairsplit_payments.db")

_lock = threading.Lock()


class BillStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
        """Context manager that guarantees the SQLite connection is closed."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()

                    # Table 1: Bills
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS bills (
                            bill_id TEXT PRIMARY KEY,
                            title TEXT,
                            subtotal_paise INTEGER NOT NULL,
                            tax_paise INTEGER NOT NULL,
                            tip_paise INTEGER NOT NULL,
                            grand_total_paise INTEGER NOT NULL,
                            currency TEXT DEFAULT 'INR',
                            created_at TEXT NOT NULL
                        )
                    """)

                    # Table 2: Bill Members (Individual Shares and Payment Status)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS bill_members (
                            bill_id TEXT NOT NULL,
                            member_name TEXT NOT NULL,
                            share_paise INTEGER NOT NULL,
                            status TEXT DEFAULT 'pending',
                            payment_method TEXT DEFAULT NULL,
                            paid_at TEXT,
                            paypal_order_id TEXT,
                            paypal_capture_id TEXT,
                            amount_paid_usd REAL,
                            payer_email TEXT,
                            PRIMARY KEY (bill_id, member_name),
                            FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
                        )
                    """)

                    # Migration for existing databases
                    try:
                        cursor.execute("ALTER TABLE bill_members ADD COLUMN payment_method TEXT DEFAULT NULL")
                    except Exception:
                        pass

                    # Table 3: PayPal Orders (Server-side tracking to prevent tampering)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS paypal_orders (
                            order_id TEXT PRIMARY KEY,
                            bill_id TEXT NOT NULL,
                            member_name TEXT NOT NULL,
                            amount_inr REAL NOT NULL,
                            amount_usd REAL NOT NULL,
                            currency TEXT NOT NULL,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            capture_id TEXT,
                            FOREIGN KEY (bill_id) REFERENCES bills(bill_id)
                        )
                    """)

    def save_bill(self, bill_id: str, title: str, summary: Dict[str, Any], breakdown: Dict[str, Any]) -> str:
        """
        Saves or updates a calculated bill and its individual member shares in integer paise.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()

                    def _extract_paise(d: dict, paise_key: str, rupee_key: str) -> int:
                        if paise_key in d and d[paise_key] is not None:
                            return int(d[paise_key])
                        if rupee_key in d and d[rupee_key] is not None:
                            return int(round(float(d[rupee_key]) * 100))
                        return 0

                    subtotal_paise = _extract_paise(summary, "subtotal_paise", "subtotal")
                    tax_paise = _extract_paise(summary, "tax_paise", "tax")
                    tip_paise = _extract_paise(summary, "tip_paise", "tip")
                    grand_total_paise = _extract_paise(summary, "grand_total_paise", "grand_total")
                    currency = str(summary.get("currency", "INR"))

                    cursor.execute("""
                        INSERT INTO bills (bill_id, title, subtotal_paise, tax_paise, tip_paise, grand_total_paise, currency, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(bill_id) DO UPDATE SET
                            title = excluded.title,
                            subtotal_paise = excluded.subtotal_paise,
                            tax_paise = excluded.tax_paise,
                            tip_paise = excluded.tip_paise,
                            grand_total_paise = excluded.grand_total_paise
                    """, (bill_id, title or "Restaurant Dining Split", subtotal_paise, tax_paise, tip_paise, grand_total_paise, currency, now_str))

                    # Save individual member shares
                    for member_name, info in breakdown.items():
                        share_paise = _extract_paise(info, "total_paise", "total")
                        # Preserve existing payment status if already paid
                        cursor.execute("""
                            INSERT INTO bill_members (bill_id, member_name, share_paise, status)
                            VALUES (?, ?, ?, 'pending')
                            ON CONFLICT(bill_id, member_name) DO UPDATE SET
                                share_paise = excluded.share_paise
                        """, (bill_id, member_name, share_paise))

        return bill_id

    def get_bill(self, bill_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves bill details and all members' current settlement statuses."""
        with _lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,))
                bill_row = cursor.fetchone()
                if not bill_row:
                    return None

                cursor.execute("SELECT * FROM bill_members WHERE bill_id = ?", (bill_id,))
                member_rows = cursor.fetchall()

                members = []
                for m in member_rows:
                    members.append({
                        "member_name": m["member_name"],
                        "share_paise": m["share_paise"],
                        "share_inr": round(m["share_paise"] / 100.0, 2),
                        "status": m["status"],
                        "payment_method": m["payment_method"] if "payment_method" in m.keys() else ("paypal" if m["paypal_order_id"] else ("offline" if m["status"] == "paid" else None)),
                        "paid_at": m["paid_at"],
                        "paypal_order_id": m["paypal_order_id"],
                        "paypal_capture_id": m["paypal_capture_id"],
                        "amount_paid_usd": m["amount_paid_usd"],
                        "payer_email": m["payer_email"]
                    })

                return {
                    "bill_id": bill_row["bill_id"],
                    "title": bill_row["title"],
                    "subtotal_paise": bill_row["subtotal_paise"],
                    "subtotal_inr": round(bill_row["subtotal_paise"] / 100.0, 2),
                    "tax_paise": bill_row["tax_paise"],
                    "tax_inr": round(bill_row["tax_paise"] / 100.0, 2),
                    "tip_paise": bill_row["tip_paise"],
                    "tip_inr": round(bill_row["tip_paise"] / 100.0, 2),
                    "grand_total_paise": bill_row["grand_total_paise"],
                    "grand_total_inr": round(bill_row["grand_total_paise"] / 100.0, 2),
                    "currency": bill_row["currency"],
                    "created_at": bill_row["created_at"],
                    "members": members
                }

    def get_member(self, bill_id: str, member_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single member record from a bill."""
        with _lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM bill_members WHERE bill_id = ? AND LOWER(member_name) = LOWER(?)",
                    (bill_id, member_name.strip())
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "bill_id": row["bill_id"],
                    "member_name": row["member_name"],
                    "share_paise": row["share_paise"],
                    "share_inr": round(row["share_paise"] / 100.0, 2),
                    "status": row["status"],
                    "payment_method": row["payment_method"] if "payment_method" in row.keys() else ("paypal" if row["paypal_order_id"] else ("offline" if row["status"] == "paid" else None)),
                    "paid_at": row["paid_at"],
                    "paypal_order_id": row["paypal_order_id"],
                    "paypal_capture_id": row["paypal_capture_id"],
                    "amount_paid_usd": row["amount_paid_usd"],
                    "payer_email": row["payer_email"]
                }

    def record_paypal_order(
        self,
        order_id: str,
        bill_id: str,
        member_name: str,
        amount_inr: float,
        amount_usd: float,
        currency: str = "USD"
    ):
        """
        Records a newly created PayPal order on the server.
        Binds order_id strictly to (bill_id, member_name, expected amount).
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO paypal_orders (order_id, bill_id, member_name, amount_inr, amount_usd, currency, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'CREATED', ?)
                    """, (order_id, bill_id, member_name, amount_inr, amount_usd, currency, now_str))

    def get_paypal_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a recorded PayPal order."""
        with _lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM paypal_orders WHERE order_id = ?", (order_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "order_id": row["order_id"],
                    "bill_id": row["bill_id"],
                    "member_name": row["member_name"],
                    "amount_inr": row["amount_inr"],
                    "amount_usd": row["amount_usd"],
                    "currency": row["currency"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "capture_id": row["capture_id"]
                }

    def mark_member_paid(
        self,
        bill_id: str,
        member_name: str,
        order_id: str = "",
        capture_id: str = "",
        amount_usd: float = 0.0,
        payer_email: Optional[str] = None,
        payment_method: str = "paypal",
        paypal_order_id: Optional[str] = None,
        paypal_capture_id: Optional[str] = None,
        amount_paid_usd: Optional[float] = None
    ) -> bool:
        """
        Marks an individual member as paid after server verification of PayPal capture.
        Guarantees other members remain untouched.
        """
        eff_order_id = order_id or paypal_order_id or ""
        eff_capture_id = capture_id or paypal_capture_id or ""
        eff_amount_usd = amount_usd if amount_usd > 0.0 else (amount_paid_usd or 0.0)

        now_str = datetime.now(timezone.utc).isoformat()
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()

                    # Update member status
                    cursor.execute("""
                        UPDATE bill_members
                        SET status = 'paid',
                            payment_method = ?,
                            paid_at = ?,
                            paypal_order_id = ?,
                            paypal_capture_id = ?,
                            amount_paid_usd = ?,
                            payer_email = ?
                        WHERE bill_id = ? AND LOWER(member_name) = LOWER(?)
                    """, (payment_method, now_str, eff_order_id, eff_capture_id, eff_amount_usd, payer_email or "", bill_id, member_name.strip()))

                    # Update order status if order_id is present
                    if eff_order_id:
                        cursor.execute("""
                            UPDATE paypal_orders
                            SET status = 'COMPLETED',
                                capture_id = ?
                            WHERE order_id = ?
                        """, (eff_capture_id, eff_order_id))

                    return cursor.rowcount > 0

    def mark_member_offline_paid(self, bill_id: str, member_name: str) -> bool:
        """
        Marks an individual member as paid via Cash/Offline outside PayPal.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE bill_members
                        SET status = 'paid',
                            payment_method = 'offline',
                            paid_at = ?,
                            paypal_order_id = NULL,
                            paypal_capture_id = NULL,
                            amount_paid_usd = NULL,
                            payer_email = NULL
                        WHERE bill_id = ? AND LOWER(member_name) = LOWER(?)
                    """, (now_str, bill_id, member_name.strip()))
                    return cursor.rowcount > 0

    def revert_member_offline(self, bill_id: str, member_name: str) -> bool:
        """
        Reverts an accidental offline payment record back to pending.
        Safety invariant: ONLY permits reverting if payment_method == 'offline'.
        Verified PayPal transactions cannot be reverted through offline rollback.
        """
        with _lock:
            with self._connection() as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE bill_members
                        SET status = 'pending',
                            payment_method = NULL,
                            paid_at = NULL
                        WHERE bill_id = ? AND LOWER(member_name) = LOWER(?) AND payment_method = 'offline'
                    """, (bill_id, member_name.strip()))
                    return cursor.rowcount > 0

    def get_settlement_summary(self, bill_id: str) -> Dict[str, Any]:
        """
        Calculates settlement statistics for a bill:
        total collected (INR), paypal collected, offline collected, total outstanding (INR),
        paid member count, and settlement progress %.
        """
        bill = self.get_bill(bill_id)
        if not bill:
            return {
                "total_members": 0,
                "paid_members": 0,
                "pending_members": 0,
                "paypal_paid_count": 0,
                "offline_paid_count": 0,
                "total_collected_inr": 0.0,
                "collected_amount_inr": 0.0,
                "paypal_collected_inr": 0.0,
                "offline_collected_inr": 0.0,
                "total_outstanding_inr": 0.0,
                "outstanding_amount_inr": 0.0,
                "progress_percentage": 0,
                "all_settled": True
            }

        total_members = len(bill["members"])
        paid_members = 0
        paypal_paid_count = 0
        offline_paid_count = 0
        total_collected_paise = 0
        paypal_collected_paise = 0
        offline_collected_paise = 0
        total_outstanding_paise = 0

        for m in bill["members"]:
            if m["status"] == "paid":
                paid_members += 1
                total_collected_paise += m["share_paise"]
                method = m.get("payment_method") or ("paypal" if m.get("paypal_order_id") else "offline")
                if method == "paypal":
                    paypal_paid_count += 1
                    paypal_collected_paise += m["share_paise"]
                else:
                    offline_paid_count += 1
                    offline_collected_paise += m["share_paise"]
            else:
                total_outstanding_paise += m["share_paise"]

        progress_pct = round((paid_members / total_members * 100)) if total_members > 0 else 0

        return {
            "bill_id": bill_id,
            "total_members": total_members,
            "paid_members": paid_members,
            "pending_members": total_members - paid_members,
            "paypal_paid_count": paypal_paid_count,
            "offline_paid_count": offline_paid_count,
            "total_collected_paise": total_collected_paise,
            "total_collected_inr": round(total_collected_paise / 100.0, 2),
            "collected_amount_inr": round(total_collected_paise / 100.0, 2),
            "paypal_collected_paise": paypal_collected_paise,
            "paypal_collected_inr": round(paypal_collected_paise / 100.0, 2),
            "offline_collected_paise": offline_collected_paise,
            "offline_collected_inr": round(offline_collected_paise / 100.0, 2),
            "total_outstanding_paise": total_outstanding_paise,
            "total_outstanding_inr": round(total_outstanding_paise / 100.0, 2),
            "outstanding_amount_inr": round(total_outstanding_paise / 100.0, 2),
            "progress_percentage": progress_pct,
            "all_settled": (paid_members == total_members and total_members > 0),
            "members": bill["members"]
        }


# Global store instance
bill_store = BillStore()
