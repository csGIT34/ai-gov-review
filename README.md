# AI Governance Review

Containerized web app to run **AI governance reviews** of AI models hosted in your
cloud providers (Azure + GCP). It discovers models on demand, runs a
**NIST AI RMF 1.0 (+ GenAI Profile, NIST AI 600-1)** questionnaire against each,
computes a **risk score + tier**, and routes it through an **approval gate** with
sign-off and an **immutable audit trail**.

> Status: **backend milestones M0–M4 complete and tested.** Discovery uses a stub
> driver (real Azure/GCP land in M5/M6); the React SPA lands in M8; OIDC auth in M10.

## How it works

```
 discover (dropdowns)      review                score            approval gate
 cloud → vendor → model → NIST questionnaire → risk score/tier → approve/reject
                          (23 controls)         + gates          + sign-off + audit
```

- **Pull-based discovery.** No background polling. When a reviewer starts a review,
  cascading dropdowns (cloud source → vendor → model) are populated on demand from
  the cloud APIs (cached). Read-only; the app never writes to any cloud.
- **Scoring.** Per-control weight × (1 − answer), rolled to a 0–100 score and four
  tiers. Two gate overrides: any **high-weight** No/Unknown → min **Tier 3**; any
  **knock-out** control fail → **Tier 4**.
- **Approval gate.** Server-enforced by tier. Tier 4 / KO failures are blocked
  unless an **admin overrides** with a mandatory reason (separately audited).
- **Audit.** Append-only log (Postgres trigger blocks UPDATE/DELETE), hash-chained;
  every decision is bound to the exact score snapshot it was made against.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · Postgres 16 · React (M8) · Docker Compose.
Three containers: `api`, `web`, `db`.

## Quickstart (Docker)

```bash
cp .env.example .env
docker compose up --build
# API + Swagger:  http://localhost:8000/docs
# Web placeholder: http://localhost:8080
```

## Quickstart (local backend, no Docker)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# Point at a local Postgres (or sqlite for a quick look):
export DATABASE_URL="postgresql+psycopg://aigov:changeme-local-only@localhost:5432/aigov"
alembic upgrade head
uvicorn app.main:app --reload
```

## Auth (dev)

v1 ships a **dev-auth** fallback (OIDC/SSO is M10). Send an `X-Dev-User` header:

| User | Roles |
|------|-------|
| `admin@dev.local` | admin (⊃ approver ⊃ reviewer) |
| `approver@dev.local` | approver |
| `reviewer@dev.local` | reviewer |

`DEV_AUTH_ENABLED=false` disables it (and, until M10, returns 401 — do this in prod).

## Example: run a review end to end

```bash
H='-H X-Dev-User:reviewer@dev.local'
SID=$(curl -s $H localhost:8000/api/v1/discovery/sources | jq -r '.[]|select(.cloud=="azure").id')
curl -s $H localhost:8000/api/v1/discovery/sources/$SID/vendors            # -> ["meta","mistral","openai"]
curl -s $H localhost:8000/api/v1/discovery/sources/$SID/vendors/openai/models
# POST /api/v1/reviews {source_id, vendor, resource_id, model_version} -> opens a review
# PATCH each control with an answer, POST /submit -> score, POST /decision -> gate
```

## Tests

```bash
cd backend && . .venv/bin/activate
pytest -q          # pure scoring unit tests + full API integration flow
```

## Layout

```
backend/
  app/
    api/v1/        routers: meta, discovery, models, reviews, approvals, audit
    auth/          dev-auth + role hierarchy (OIDC in M10)
    discovery/     driver interface + TTL cache + stub (Azure/GCP in M5/M6)
    models/        SQLAlchemy entities + enums
    schemas/       pydantic request/response models
    services/      scoring (pure), questionnaire, review_workflow, approvals, audit
    data/          questionnaire_v1.yaml (23 NIST controls)
  alembic/         migrations (baseline + audit append-only trigger)
  tests/
frontend/          web placeholder (React SPA in M8)
docker-compose.yml
```

## Security posture

Read-only, least-privilege cloud access (keyless in prod); no secrets in the image
or git; immutable, hash-chained audit; decisions bound to a frozen score + frozen
questionnaire snapshot; non-root containers; pinned dependencies.

## Roadmap

M5 Azure discovery · M6 GCP discovery · M7 (n/a — pull-based) · M8 React SPA ·
M9 approval UI + audit viewer · M10 OIDC auth · M11 hardening + prod IaC.
