---
department: engineering
allowed_roles: engineering, admin
sensitivity: restricted
---
# April 2026 Portal Incident Postmortem

On April 9, an incompatible cache configuration caused intermittent sign-in failures for a portion of portal users. The incident lasted 38 minutes before the on-call engineer reverted the configuration.

No customer records were lost or exposed. The corrective actions are to add a configuration compatibility check to continuous delivery, provide a staged rollout switch, and rehearse the sign-in rollback procedure quarterly.

The incident commander closed the event after error rates returned to the normal operating range and all monitoring alerts cleared.
