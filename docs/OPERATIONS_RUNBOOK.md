# Operations Runbook

## CI/CD

GitHub Actions runs backend unit tests, Alembic head checks, frontend typecheck/build/audit, and Playwright smoke tests.

## Monitoring

`GET /api/system/status` exposes a safe operations summary. Admins can read detailed counters through `GET /api/system/admin/metrics`.

## Backups

For local SQLite deployments, admins can trigger `POST /api/system/admin/backup`. Production PostgreSQL should use managed snapshots and point-in-time recovery.

## Blue/Green And Canary

Use `DEPLOYMENT_COLOR`, `RELEASE_CHANNEL`, and `CANARY_PERCENT` to label each deployment. The release checker validates that canary percentage stays between `0` and `100`.

## Payments

`POST /api/payments/checkout` creates an order. Payment gateways should call `POST /api/payments/webhook` with `X-Payment-Signature = HMAC_SHA256(raw_body, PAYMENT_WEBHOOK_SECRET)`. Only a verified paid webhook opens the user plan.
