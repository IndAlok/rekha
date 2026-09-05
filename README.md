# Rekha

Bounded recovery. Every rupee explained.

<p align="center">
  <a href="https://youtu.be/ZUb4OaI-YNc" title="Watch Rekha on YouTube">
    <img src="https://img.youtube.com/vi/ZUb4OaI-YNc/maxresdefault.jpg" alt="Rekha, bounded recovery, Razorpay test-mode" width="720" />
  </a>
</p>

<p align="center">
  <a href="https://youtu.be/ZUb4OaI-YNc">
    <img src="https://img.shields.io/badge/YouTube-Watch_the_desk-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube" />
  </a>
</p>

The model never moves money. On live cases Groq may write a reason if it agrees with the playbook. YAML policy says ALLOW, DENY, DEFER, or REQUIRE_APPROVAL. A scheduler runs each action once. A hash chain stores why. Eval runs with the model off.

Built for the [Razorpay AI Buildathon](https://razorpay.com/buildathon/). Test-mode only. No live payment keys. No real customer data.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd apps/web && npm ci && cd ../..
make test
make serve
```

API on :8080. Desk on :3000. `make eval` writes `artifacts/eval/report.md`. Docker is `make compose`. Postgres is `make compose-full`. Razorpay blocks ngrok, use zrok.

Seed 42, 99 vs 100. Treatment ₹1,22,139, control ₹1,00,028, incremental ₹22,111. Rate lift +40.8pp, Newcombe [+27.3pp, +52.1pp]. Rupee BCa includes zero. A future `send_after` is scheduled, not recovered, unless the persona pays that day.

## Env

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | sqlite in the process temp dir | inbox, audit, jobs, ledger |
| `REKHA_ENV` | `dev` | anything else fails closed |
| `OPS_TOKEN` | empty | required outside dev on every POST except the Razorpay webhook |
| `RAZORPAY_WEBHOOK_SECRET` | empty | HMAC required outside dev |
| `PAYMENTS_ADAPTER` | `sandbox` | `razorpay_test` needs `rzp_test_` keys |
| `OPENAI_API_KEY` | empty | optional live advisor. names stay OPENAI_* because the HTTP dialect is OpenAI-shaped. Groq is the host. eval never calls it |
| `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` | Groq chat completions |
| `OPENAI_MODEL` | `llama-3.3-70b-versatile` | if Groq rejects JSON mode or the model, Rekha drops `response_format`, then tries `llama-3.1-8b-instant`, then keeps the playbook |
| `CORS_ORIGINS` | `*` | set this to the desk origin in prod |
| `AUTO_EVAL_ON_BOOT` | `true` | first boot builds the report |

SMS, WhatsApp, and email stay FileInbox. Copy never names s.138, IBC, or MSME filings. Clocks live in `packages/policy/constants.yaml`.

## Advisor

Live webhooks and `/cases/run` only. `/status` shows provider and model, never the key. The 200-case batch, `rekha eval`, and CI stay off even when the key is in `.env`.

Groq may write a reason when it picks the same tool the playbook already picked. It cannot pick a different tool, change the channel, change the amount, set `send_after`, send a message, retry a card, or open an approval.

Fail closed to the playbook on 401, 429, 5xx, an 8 second timeout, a connect error, or junk JSON. A 400 drops JSON mode, then the 8b model, then silence.

Set the three `OPENAI_*` vars on the API host (Railway). Do not put them on Vercel.

## Deploy

Desk is at https://rekha-one.vercel.app. API image is `infra/Dockerfile.api`. Point `API_UPSTREAM` at the API origin. Set `REKHA_ENV`, `OPS_TOKEN`, `RAZORPAY_WEBHOOK_SECRET`, and `CORS_ORIGINS` before you expose it. Optional advisor vars go on the API host only, never on Vercel.

MIT.
