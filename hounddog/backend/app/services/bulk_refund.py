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
