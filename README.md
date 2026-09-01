# Rekha

Bounded recovery. Every rupee explained.

The model never moves money. It writes one tool from a closed list. YAML policy says ALLOW, DENY, DEFER, or REQUIRE_APPROVAL. A scheduler runs each action once. A hash chain stores why.

Built for the [Razorpay AI Buildathon](https://razorpay.com/buildathon/). Test-mode only. No live keys. No real customer data.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd apps/web && npm ci && cd ../..
make test
make serve
```

API on :8080. Desk on :3000. `make eval` writes `artifacts/eval/report.md`. Docker is `make compose`. Postgres is `make compose-full`. Razorpay blocks ngrok, use zrok.

Seed 42, 99 vs 100. Treatment ₹1,20,947, control ₹1,00,028, incremental ₹20,919. Rate lift +32.7pp, Newcombe [+18.9pp, +44.7pp]. Rupee BCa includes zero. A future `send_after` is scheduled, not recovered, unless the persona pays that day.

## Env

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | sqlite in the process temp dir | inbox, audit, jobs, ledger |
| `REKHA_ENV` | `dev` | anything else fails closed |
| `OPS_TOKEN` | empty | required outside dev on every POST except the Razorpay webhook |
| `RAZORPAY_WEBHOOK_SECRET` | empty | HMAC required outside dev |
| `PAYMENTS_ADAPTER` | `sandbox` | `razorpay_test` needs `rzp_test_` keys |
| `OPENAI_API_KEY` | empty | optional advisor. eval stays green without it |
| `CORS_ORIGINS` | `*` | set this to the desk origin in prod |
| `AUTO_EVAL_ON_BOOT` | `true` | first boot builds the report |

SMS, WhatsApp, and email stay FileInbox. Copy never names s.138, IBC, or MSME filings. Clocks live in `packages/policy/constants.yaml`.

## Deploy

Desk is at https://rekha-one.vercel.app. API image is `infra/Dockerfile.api`. Point `API_UPSTREAM` at the API origin. Set `REKHA_ENV`, `OPS_TOKEN`, `RAZORPAY_WEBHOOK_SECRET`, and `CORS_ORIGINS` before you expose it.

MIT.
