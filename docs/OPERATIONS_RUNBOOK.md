# Operations Runbook

## CI/CD

GitHub Actions runs backend unit tests, Alembic head checks, frontend typecheck/build/audit, and Playwright smoke tests.

## Monitoring

`GET /api/system/status` exposes a safe operations summary. Admins can read detailed counters through `GET /api/system/admin/metrics`.

For production, configure active alert delivery:

- `ALERT_NOTIFY_ENABLED=true`
- `ALERT_WEBHOOK_URL=<your alert gateway>`
- `ALERT_WEBHOOK_TOKEN=<secret token>`
- `ALERT_MIN_SEVERITY=critical`
- `ALERT_DEDUPE_MINUTES=60`

Admins can send the current alert snapshot from `/admin/system`, or call `POST /api/system/admin/alerts/notify`. Alert notification records store only alert keys, severity, destination host, send status, and short error text.

## Redis And Qdrant

Production must use external services, not embedded/local-only fallback:

- `TASK_QUEUE_BACKEND=redis_rq`
- `TASK_REDIS_URL=redis://...`
- `TASK_ALLOW_LOCAL_FALLBACK=false`
- `VECTOR_STORE_BACKEND=qdrant`
- `QDRANT_URL=http(s)://...`
- `EMBEDDING_PROVIDER=openai_compatible` or a real BGE-M3 service
- `QDRANT_VECTOR_SIZE=1024`

After deployment, run `alembic upgrade head`, import the interview bank, and trigger resume reindexing from `/admin/system`.

## Quality Feedback Loop

User feedback with low scores or negative labels automatically creates `quality_eval_candidates`. Admins review candidates in `/admin/system`, mark accepted samples as `added_to_eval`, and then convert them into `backend/quality/ats_eval_cases.json` regression cases. Do not copy full resumes, JDs, phone numbers, emails, or API keys into eval cases.

## Backups

For local SQLite deployments, admins can trigger `POST /api/system/admin/backup`. Production PostgreSQL should use managed snapshots and point-in-time recovery.

## Blue/Green And Canary

Use `DEPLOYMENT_COLOR`, `RELEASE_CHANNEL`, and `CANARY_PERCENT` to label each deployment. The release checker validates that canary percentage stays between `0` and `100`.

## Payments

`POST /api/payments/checkout` creates an order. Payment gateways should call `POST /api/payments/webhook` with `X-Payment-Signature = HMAC_SHA256(raw_body, PAYMENT_WEBHOOK_SECRET)`. Only a verified paid webhook opens the user plan.
