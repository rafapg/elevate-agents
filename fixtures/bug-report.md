---
id: BUG-204
reported_at: 2026-08-08T09:12:00Z
service: checkout
owner: Payments
deployment: 2026.08.1
severity: high
---

# Checkout returns 500 for some Safari customers after 2026.08.1

Support observed a conversion drop shortly after deploy `2026.08.1`. A small
subset of customers using Safari see a generic 500 page after returning from
payment. The problem is intermittent: retrying checkout sometimes succeeds.

Known boundaries:

- The report contains no payment details or customer identifiers.
- No patch, feature-flag change, issue publication, or external call is
  authorized by this investigation.
- The initial owner is `Payments`; route there if the evidence gate cannot be
  met.

Safari is the first sensor, not a confirmed cause.
