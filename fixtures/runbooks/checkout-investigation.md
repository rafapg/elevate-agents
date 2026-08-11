---
id: RUNBOOK-checkout-investigation
updated_at: 2026-07-20T12:00:00Z
owner: Payments
---

# Checkout investigation runbook

1. Preserve the deploy identifier, route, error code, and feature flag.
2. Compare an error event with a successful event from the same route.
3. Inspect the smallest recent diff that touches the failing path.
4. Treat browser family as a segment until another source establishes cause.
5. If CI is incomplete, retry once using the recorded checkpoint; do not infer
   a product root cause from a timeout.
6. Before proposing an external action, require two independent sources and an
   explicit limitation. Otherwise escalate a read-only summary to `Payments`.

This runbook authorizes investigation and draft preparation only. Publishing a
ticket, changing a flag, or deploying a patch requires separate approval.
