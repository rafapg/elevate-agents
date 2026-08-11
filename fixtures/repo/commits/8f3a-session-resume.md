---
id: 8f3a
committed_at: 2026-08-08T08:41:00Z
author: payments-maintainer
deployment: 2026.08.1
paths:
  - src/checkout/complete.py
---

# 8f3a: simplify payment-return session resume

The following compact diff is synthetic. It removes the guard that converted a
missing `session_id` in a payment return into a recoverable checkout response.

```diff
diff --git a/src/checkout/complete.py b/src/checkout/complete.py
@@ def complete_checkout(payment_return):
-    session_id = payment_return.get("session_id")
-    if not session_id:
-        return {"redirect": "/checkout/resume", "reason": "missing_session"}
+    session_id = payment_return.get("session_id")
     return {"redirect": f"/checkout/confirmation/{session_id.upper()}"}
```

The commit message says this removed a branch believed unreachable after a
provider migration. It does not mention Safari.
