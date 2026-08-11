"""Synthetic checkout completion handler used only by Aula 12 fixtures."""


def complete_checkout(payment_return: dict[str, object]) -> dict[str, str]:
    """Resume the checkout session after a payment provider redirect.

    This implementation intentionally represents the regression introduced in
    deploy 2026.08.1: a missing `session_id` is dereferenced instead of being
    handled as a recoverable, client-visible state.
    """

    session_id = payment_return.get("session_id")
    return {"redirect": f"/checkout/confirmation/{session_id.upper()}"}
