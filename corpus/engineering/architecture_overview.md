---
department: engineering
allowed_roles: engineering, admin
sensitivity: restricted
---
# Platform Architecture Overview

The customer portal is a web client backed by a stateless API service. Requests are authenticated at the gateway, and application services read operational data through versioned internal interfaces.

Production workloads run across two availability zones. Service owners maintain health checks, dashboards, and rollback instructions. Secrets are stored in the managed secret service and must never be committed to source control.

Engineering changes require peer review and a successful automated test run before deployment. Architecture decisions are recorded as short decision records in the engineering repository.
