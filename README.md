# AI Governance Review

Containerized web app to run **AI governance reviews** of AI models hosted in your
cloud providers (Azure + GCP). It discovers models on demand, **auto-answers the
machine-answerable questions from cloud facts**, runs a
**NIST AI RMF 1.0 (+ GenAI Profile, NIST AI 600-1)** questionnaire, computes a
**risk score + tier**, and routes it through an **approval gate** with sign-off and
an **immutable audit trail**.

> Status: backend core, the auto-answer engine, per-cloud residency policy, an admin
> config dashboard, framework-version tracking, and the React SPA are **built and
> tested**. Cloud **discovery is still a stub** (real Azure/GCP = M5/M6), and auth is a
> **dev header** (OIDC = M10).

## How it works

```
 discover ──▶ auto-answer ──▶ review ─────────▶ score ───────▶ approval gate
 cloud →       from cloud      reviewer confirms  0-100 + tier   approve / reject
 vendor →      facts +         suggestions &      + gates        + sign-off + audit
 model         provider docs   answers the rest
```

- **Pull-based discovery.** No background polling. When a reviewer starts a review,
  cascading dropdowns (cloud source → vendor → model) are populated on demand from
  the cloud APIs (cached). Read-only — the app never writes to any cloud.
  Azure discovery can run **live** (see [Live Azure discovery](#live-azure-discovery-m5));
  GCP is stubbed until M6.
- **Auto-answer.** When the review opens, the engine pre-answers every control it can
  from the model's cloud facts, so the reviewer only handles judgment calls. See
  [How auto-answer works](#how-auto-answer-works) below.
- **Scoring.** Per-control `weight × (1 − answer)`, rolled to a 0–100 risk score and
  four tiers. Two gate overrides: any **high-weight** No/Unknown → min **Tier 3**; any
  **knock-out** control failure → **Tier 4**.
- **Approval gate.** Server-enforced by tier. Tier 4 / KO failures are blocked unless
  an **admin overrides** with a mandatory reason (separately audited).
- **Audit.** Append-only log (a Postgres trigger blocks UPDATE/DELETE), hash-chained;
  every decision is bound to the exact score snapshot it was made against.

## How auto-answer works

The whole point of the tool: **most of the 23 NIST questions can be answered from the
cloud provider's own data** — you shouldn't hand-answer "what region is this deployed
in?" So when a review opens, the engine pre-fills what it can and leaves only the
genuine judgment calls to a human.

### Every control lands in one of four tiers

| Badge | Tier | Meaning | Reviewer action |
|-------|------|---------|-----------------|
| ✓ **auto** (green) | fact | Answered from an **objective cloud fact**. Accepted as-is. | none |
| ✓ **attested** (teal) | attested | Answered from a **documented platform/vendor commitment** — the citation ships as the control's evidence link. Accepted as-is. | none (override allowed) |
| **confirm** (amber) | suggested | A tentative answer derived from the **provider's documentation**, with an evidence link. | must confirm or override before submit |
| **manual** (grey) | manual | **No reliable cloud signal** (org policy / procurement / process). | the human answers; a guidance note says what to confirm |

For the current 23-control questionnaire on Azure OpenAI that's
**8 auto · 4 attested · 6 suggested · 5 manual**.

### Attested: the platforms document their own NIST adherence

Microsoft and Google publish standing commitments that answer several controls
**per platform**, not per model — so the engine cites the document instead of
asking a reviewer to re-confirm it on every review
(`app/services/attestations.py`, a curated registry keyed by cloud + publisher):

- **Data handling** — Azure OpenAI data-privacy note (prompts/completions never
  train Microsoft or OpenAI models; abuse-monitoring retention ≤ 30 days); Azure
  AI Foundry data-processing terms for third-party publishers; Vertex AI
  generative-AI data governance; Anthropic commercial terms.
- **Certifications & SLAs** — SOC 2 Type 2, ISO/IEC 27001 and **ISO/IEC 42001**
  (AI management system) attestations, plus each platform's published **NIST AI
  RMF crosswalk** (Microsoft Service Trust Portal / Google compliance resource
  center).
- **IP indemnity** — Microsoft Customer Copyright Commitment (Azure OpenAI /
  Microsoft models); Google generative-AI indemnified services; Anthropic
  commercial-terms indemnity.
- **Provider red-teaming** — Azure OpenAI transparency note; Google Responsible
  AI docs; Anthropic system cards + Responsible Scaling Policy.

Curation is fail-closed: only public, linkable documents; vendor-specific
entries only where the document names that publisher; a withdrawn document means
the entry is deleted and the control falls back to the suggested/manual path.
Attested answers are **not carried** by the precedent fast-track (they're
recomputed fresh, like auto facts) and a reviewer can always override one — the
override re-owns the answer as `human`.

### The 8 auto controls read these cloud facts

Each is a deterministic check against a property of the deployed resource:

| Control | Cloud fact it reads | Example answer |
|---------|---------------------|----------------|
| `data_residency` | resource **region** vs *your* approved-regions policy (per cloud) | region `switzerlandnorth` not in approved Azure set → **no (knock-out)** |
| `safety_filters` | content-safety / responsible-AI policy attached (Azure `raiPolicyName`, Vertex safety) | policy `DefaultV2` attached → **yes** |
| `access_controls` | `publicNetworkAccess` + `disableLocalAuth` (key vs identity auth) | private + identity-only → **yes**; public + keys → **no** |
| `encryption_logging` | customer-managed-key encryption + min TLS | CMK + TLS 1.2 → **yes**; TLS only → **partial** |
| `monitoring` | diagnostic settings / logging sink configured | no sink → **no** |
| `version_change_process` | version pinning (Azure `versionUpgradeOption`) | `NoAutoUpgrade` (pinned) → **yes**; auto-upgrade → **partial** |
| `categorization` | model format / modality | foundation, generative → **yes** (+ GenAI profile applies) |
| `model_card` | exact model name/version/publisher captured at discovery | identity known + provider card linked → **yes** |

### Two-tier trust (why "suggested" still needs a human)

A **region is a fact** — the engine accepts it. A **documentation link is not proof**
the doc actually covers the claim, so provider-doc controls (provenance, data handling,
red-team evidence, eval results, bias, GenAI infosec, explainability, IP/licensing,
SOC 2/ISO, environmental) are pre-filled as **suggested** with the provider's doc
attached, and the reviewer must tick them off. Submit is blocked until every suggestion
is confirmed and every manual control is answered.

### "Approved" is *your* policy, not a constant

`data_residency` compares the model's region to an **admin-editable, per-cloud** list
(Admin → *Data-residency policy*). Azure and GCP use different region names, so they're
configured in separate buckets. Resolution order: a `DiscoverySource`'s own override
(`config.approved_regions`) → otherwise the global policy. Edits apply to **new**
reviews, and the rationale cites *"your approved azure data-residency policy (N
regions)."*

### Honesty boundary

The engine **only auto-answers objective cloud facts.** Things it deliberately does
**not** auto-answer, because the cloud API can't know them:

- `vendor_vetted` — whether you have an **active contract / enterprise agreement** with
  the provider. That's procurement data → **manual**, with a guidance note.
- `intended_use`, `human_oversight`, `incident_response`, `impact_assessment` — org
  policy/process → **manual**.

### The flow, end to end

```
discovery driver → facts{region, content_filter, public_network_access, ...}
                 │
open_review ─────┤ autoanswer.collect(facts, vendor, policy, cloud)
                 │     fact collectors  → answer_source = "auto"       (accepted)
                 │     doc collectors   → answer_source = "suggested"  (needs confirm)
                 │     no collector      → manual + guidance note
                 ▼
ControlResponse rows pre-filled (answer, source, rationale, evidence_url)
                 ▼
reviewer confirms suggestions + answers the manual controls
                 ▼
submit → scoring engine → risk score + tier + gates
```

**Where it lives:** the engine is `backend/app/services/autoanswer.py` (fact + doc
collectors, `Policy`), policy resolution is `backend/app/services/policy.py`, and it's
applied in `backend/app/services/review_workflow.py::open_review`. The `facts` dict is
supplied by the discovery driver — a **stub today**; the real Azure/GCP drivers (M5/M6)
populate the same shape, so the engine is unchanged when discovery goes live.

## Precedent fast-track ("rubber stamp")

Most models from a vendor fall under the same approval process — the org-level
judgment answers (procurement vetting, oversight process, incident runbook,
doc-based confirmations) don't change between them. So once **one** model is fully
reviewed and approved, later models can be fast-tracked:

- **Standalone records:** approving a review automatically **mints a precedent
  row** (the `precedents` table) — a snapshot of the vendor, governing terms,
  questionnaire version and the human judgment answers. The fast-track matches
  against these rows, **not** against review records, so deleting a review never
  breaks the rubber stamp. Admins manage precedents on the **Admin page**:
  disable one (kill switch, reversible) or delete it; reviews that already
  adopted keep their answers.
- **Match rule:** same **vendor** + same **governing terms** (`facts.terms.id` — the
  marketplace agreement / publisher license on the resource) + an **enabled**
  precedent + the same questionnaire version. All checks are enforced
  server-side on adopt; the UI only reflects them.
- **Adopt** carries the precedent's judgment answers into the new review, marked
  `carried` (purple badge). One click, then submit → score → approve. The approval
  justification is prefilled with the precedent reference.
- **What never carries:** the 8 **auto** (cloud-fact) controls — residency,
  network, encryption, filters, version pinning — are always recomputed from
  *this* model's own facts. A model with a worse footprint still trips its own
  gates (e.g. `o3-mini` fast-tracks its answers from `gpt-4o` but its
  `brazilsouth` region still forces a residency KO → Tier 4).
- **The caveat:** a model under **different terms** gets **no fast-track**, with
  the reason shown. Example in the stub: `claude-fable-5` shares the Anthropic
  commercial ToS with `claude-opus-4-8` (fast-track ok), but `claude-mythos-5`
  is under a restricted-availability addendum → full review, explicitly explained.
- **Provenance:** `review.precedent_id`, per-control `answer_source="carried"`,
  a `review_precedent_adopted` audit entry, and the final decision's audit entry
  references the precedent. Carried answers can still be overridden (they become
  `human` again).

Where it lives: `backend/app/services/precedent.py`,
`GET/POST /api/v1/reviews/{id}/precedent|adopt-precedent`,
`GET/PATCH/DELETE /api/v1/precedents` (admin management).

## Point-in-time CSP snapshot

Every review freezes, at open time, a copy of the CSP data its machine answers
came from — the model's **cloud facts** (regions, network/auth posture,
encryption, filters, terms) and the **platform attestation documents** used
(`review.facts_snapshot`, shown as a collapsible panel on the review page).
`Model.facts` is overwritten on every re-discovery and the attestation registry
is curated code that evolves; the snapshot documents exactly what THIS review
saw, so the evidence behind a decision never drifts after the fact.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · Postgres 16 · React + Vite (TS) · Docker Compose.
Three containers: `api`, `web`, `db`.

## Quickstart (Docker)

```bash
cp .env.example .env
docker compose up --build
# Web app:  http://localhost:8080      (Dashboard, New Review, Admin)
# API docs: http://localhost:8000/docs
```

> No Compose plugin? Build/run the three containers directly with `docker build` +
> `docker run` on a shared `docker network` — the compose file documents the wiring.

## Live Azure discovery (M5)

Set two env vars on the API and the Azure dropdowns read your real subscription
instead of the stub (GCP stays stubbed until M6):

```bash
AZURE_DISCOVERY=live
AZURE_SUBSCRIPTION_ID=<subscription guid>
```

What it reads (strictly **read-only** — ARM GETs only, **Reader** role suffices):
Cognitive Services accounts of kind `OpenAI`/`AIServices`, their model
**deployments** (model name/version/format, RAI content-filter policy, version
upgrade option), account posture (public network access, local key auth, CMK
encryption), and diagnostic-settings presence. Per-region deployments of the same
model are collapsed into **one logical model** whose `regions[]` footprint feeds
residency, and whose facts merge **fail-closed** — the worst posture anywhere in
the footprint wins, so one weak regional deployment can't hide behind a hardened one.
Governing terms (`facts.terms`) are derived from the model publisher's standard
Azure terms; vendors without a known terms mapping get none, which disables the
precedent fast-track (fail closed).

**No resources required — the region catalog.** You don't have to deploy anything
to review a model. Alongside deployed models, the driver lists the models Azure
*offers* in your approved regions (`locations/{region}/models` — the same data as
`az cognitiveservices model list -l <region>`), so a governance review can start
**before** any resource is created, at zero cost. Catalog models show as
**“not deployed”** and carry `facts.deployment_status="catalog"`; a deployed model
with the same (vendor, name, version) always wins, with its real posture facts.
The catalog is scoped to the org's approved-regions policy (per-source
`config.approved_regions` override respected); `config.include_catalog: false`
turns it off for a source.

Because a catalog model has no resource, there is **no posture to measure** — and
answering *No/Unknown* would auto-reject every not-yet-deployed model through the
KO gates. So the six posture controls (residency, safety filters, access controls,
encryption, monitoring, version pinning) arrive as **suggested "partial"**
pre-deployment plans the reviewer confirms ("confirm a content-filter policy will
be required at deployment", …). Being *suggested*, they're carryable by the
precedent fast-track. Deploy later and re-review: the same `resource_id` picks up
the real facts, and the auto-answers recompute from measured posture.

**Credentials (keyless, in order):**

1. `AZURE_ACCESS_TOKEN` — a short-lived bearer for containerized dev:
   `-e AZURE_ACCESS_TOKEN="$(az account get-access-token --query accessToken -o tsv)"`
   (expires in ~1h; restart with a fresh one — never bake it into an image).
2. `DefaultAzureCredential` — `az login` when running the backend locally;
   **managed identity / workload identity** in production. No secrets in git or images.

## Quickstart (local backend, no Docker)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://aigov:changeme-local-only@localhost:5432/aigov"
alembic upgrade head
uvicorn app.main:app --reload
```

## Auth (dev)

v1 ships a **dev-auth** fallback (OIDC/SSO is M10). Send an `X-Dev-User` header (the SPA
has a role switcher, top-right):

| User | Roles |
|------|-------|
| `admin@dev.local` | admin (⊃ approver ⊃ reviewer) |
| `approver@dev.local` | approver |
| `reviewer@dev.local` | reviewer |

`DEV_AUTH_ENABLED=false` disables it (and, until M10, returns 401 — do this in prod).

## Using it

In the browser (http://localhost:8080): **New Review** → pick cloud → vendor → model →
the workspace opens with controls pre-answered → confirm the amber *suggested* ones and
answer the grey *manual* ones (score updates live) → **Submit** → switch to
Approver/Admin → the **approval gate** enforces the tier. **Admin** manages the
data-residency policy, discovery sources, and framework-version review.

Or drive the API directly:

```bash
H='-H X-Dev-User:reviewer@dev.local'
SID=$(curl -s $H localhost:8000/api/v1/discovery/sources | jq -r '.[]|select(.cloud=="azure").id')
curl -s $H localhost:8000/api/v1/discovery/sources/$SID/vendors/openai/models
# POST /api/v1/reviews {source_id, vendor, resource_id, model_version}  -> opens a pre-filled review
# GET  /api/v1/reviews/{id}/controls                                    -> see answer_source per control
# PATCH .../controls/{cid} {answer}  (confirm suggestions / answer manual)
# POST .../submit  -> score   ·   POST .../decision -> approval gate
# admin: GET/PUT /api/v1/policy   ·   GET /api/v1/framework, POST /api/v1/framework/reviewed
```

## Tests

```bash
cd backend && . .venv/bin/activate
pytest -q     # pure scoring units, auto-answer engine, per-cloud policy, framework, full API flow
```

## Layout

```
backend/
  app/
    api/v1/        routers: meta, discovery, models, reviews, approvals, audit, policy, framework
    auth/          dev-auth + role hierarchy (OIDC in M10)
    discovery/     driver interface + TTL cache + stub (real Azure/GCP in M5/M6)
    services/
      autoanswer.py    fact + doc collectors, Policy  ← the auto-answer engine
      policy.py        per-cloud residency policy: get / update / resolve
      scoring.py       pure NIST scoring (weights, gates, tiers)
      review_workflow.py  open (auto-fills controls) / answer / submit / score
      approvals.py     tier-gated decisions + admin override
      questionnaire.py / audit.py / models.py
    nist.py        NIST AI RMF category statements (control notation)
    models/        SQLAlchemy entities + enums
    data/          questionnaire_v1.yaml  ← single source of truth for the 23 controls
  alembic/         migrations (baseline + audit trigger + auto-answer/policy/framework cols)
  tests/
frontend/          React/Vite SPA: Dashboard, New Review, Review workspace, Admin
docker-compose.yml
```

## Security posture

Read-only, least-privilege cloud access (keyless in prod); no secrets in the image or
git; immutable, hash-chained audit; decisions bound to a frozen score + frozen
questionnaire snapshot; the engine only auto-accepts objective cloud facts (never
procurement/contract status); non-root containers; pinned dependencies.

## Keeping the questionnaire current

`backend/app/data/questionnaire_v1.yaml` is the single source of truth for the controls
and the NIST framework version. The **Admin → Governance framework** card shows the
version the questions implement (NIST AI 100-1 + 600-1), the control count, and a
**last-reviewed / next-due** record with an **overdue** flag — mark it reviewed when you
confirm the questions still match the current NIST release.

## Roadmap

**Done:** core (M0–M4) · auto-answer engine · per-cloud policy + admin dashboard ·
framework tracking · React SPA (M8).
**Next:** M5 real Azure discovery · M6 GCP discovery · M9 audit-log viewer · M10 OIDC
auth · M11 hardening + prod IaC.
