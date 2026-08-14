"""Pure helpers for bulk partial refunds (no Stripe/DB imports)."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def parse_money(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError("Invalid amount") from e
    if amount < 0:
        raise ValueError("Amount must be non-negative")
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def proposed_refund(
    mode: str,
    amount: Decimal,
    original: Decimal,
    already_refunded: Decimal,
) -> tuple[Decimal | None, str | None]:
    """Return (proposed_amount, skip_reason).

    Skip when the requested refund exceeds the refundable balance rather
    than silently capping — admins need to see those rows flagged.
    """
    original = original.quantize(CENTS, rounding=ROUND_HALF_UP)
    already = already_refunded.quantize(CENTS, rounding=ROUND_HALF_UP)
    refundable = original - already

    if refundable <= ZERO:
        return None, "already fully refunded"

    if mode == "percent":
        if amount > Decimal("100"):
            return None, "percentage cannot exceed 100"
        proposed = (original * amount / Decimal("100")).quantize(CENTS, rounding=ROUND_HALF_UP)
    else:
        proposed = amount.quantize(CENTS, rounding=ROUND_HALF_UP)

    if proposed <= ZERO:
        return None, "refund amount is zero"
    if proposed > refundable:
        return None, f"refund ${proposed} exceeds refundable balance ${refundable}"
    return proposed, None


def evaluate_transaction(
    *,
    txn_id: str,
    status: str | None,
    original: Decimal,
    already_refunded: Decimal,
    mode: str,
    amount: Decimal,
    customer_name: str | None = None,
    customer_email: str | None = None,
    description: str | None = None,
) -> dict:
    """Classify a cached Stripe transaction as eligible or skipped."""
    base = {
        "id": txn_id,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "description": description,
        "amount": str(original.quantize(CENTS)),
        "amount_refunded": str(already_refunded.quantize(CENTS)),
        "refundable": str(max(ZERO, original - already_refunded).quantize(CENTS)),
    }
    if not txn_id:
        return {**base, "eligible": False, "proposed": None, "skip_reason": "missing Stripe id"}
    if (status or "").lower() != "succeeded":
        return {
            **base,
            "eligible": False,
            "proposed": None,
            "skip_reason": f"not a successful charge (status={status or 'unknown'})",
        }

    proposed, reason = proposed_refund(mode, amount, original, already_refunded)
    if reason:
        return {**base, "eligible": False, "proposed": None, "skip_reason": reason}
    return {**base, "eligible": True, "proposed": str(proposed), "skip_reason": None}


def refund_idempotency_key(txn_id: str, cents: int) -> str:
    """Stable key so retrying a success does not create a second refund."""
    return f"bulk-refund:{txn_id}:{cents}"[:255]


SOURCE_RANK = {"charge": 0, "payment_intent": 1, "checkout_session": 2}


def transaction_group_key(
    *,
    txn_id: str,
    source: str | None,
    payment_intent_id: str | None,
    customer_email: str | None,
    amount,
    created,
) -> str:
    """Group Charge + PaymentIntent + Checkout Session for the same payment."""
    email = (customer_email or "").strip().lower()
    ts = None
    if created is not None:
        ts = created.timestamp() if hasattr(created, "timestamp") else None
        if ts is None:
            try:
                ts = float(created)
            except (TypeError, ValueError):
                ts = None
    if email and ts is not None:
        return f"fp:{email}:{amount}:{int(ts // 120)}"
    pi = (payment_intent_id or "").strip()
    if not pi and (txn_id or "").startswith("pi_"):
        pi = txn_id
    if pi:
        return f"pi:{pi}"
    return f"id:{txn_id}"


def dedupe_stripe_rows(rows: list[dict]) -> list[dict]:
    """Keep one row per underlying payment, preferring Charge over PI over Session."""
    best: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        created = row.get("created")
        if isinstance(created, str):
            try:
                from datetime import datetime as _dt
                created = _dt.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created = None
        key = transaction_group_key(
            txn_id=row.get("id") or "",
            source=row.get("source"),
            payment_intent_id=row.get("payment_intent_id"),
            customer_email=row.get("customer_email") or (row.get("metadata") or {}).get("student_email") or (row.get("metadata") or {}).get("email"),
            amount=row.get("amount"),
            created=created,
        )
        prev = best.get(key)
        rank = SOURCE_RANK.get(row.get("source") or "", 9)
        if prev is None:
            best[key] = row
            order.append(key)
        elif rank < SOURCE_RANK.get(prev.get("source") or "", 9):
            best[key] = row
    return [best[k] for k in order]
