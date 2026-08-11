---
id: ISSUE-91
opened_at: 2025-11-14T15:10:00Z
status: closed
labels: [checkout, safari, historical]
---

# Safari checkout returned to cart after a third-party cookie change

This historical issue predates the `payment_return_v2` feature flag and deploy
`2026.08.1`. It concerned a cookie restriction that sent customers back to the
cart with HTTP 302; it did not involve 500 responses or a missing session ID.

Resolution: update cookie attributes for the old embedded checkout flow.

Use this as contextual evidence only. Similar browser wording is not proof of
the present failure mechanism.
