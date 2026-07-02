import { Control, TIER_CLASS } from "./api";

const W: Record<string, number> = { low: 1, medium: 2, high: 3 };
const A: Record<string, number> = { yes: 1, partial: 0.5, no: 0, unknown: 0 };
const FAIL = new Set(["no", "unknown"]);

export interface Preview {
  score: number;
  tier: number;
  koFails: string[];
  highFails: string[];
}

// Client-side preview using the SAME formula as the backend scoring engine.
// Authoritative score is always the server's (on submit).
export function computePreview(controls: Control[]): Preview {
  let tw = 0;
  let def = 0;
  const koFails: string[] = [];
  const highFails: string[] = [];
  for (const c of controls) {
    const w = W[c.weight] ?? 1;
    const a = c.answer ? A[c.answer] ?? 0 : 0; // unanswered treated as unknown
    tw += w;
    def += w * (1 - a);
    const failing = c.answer != null && FAIL.has(c.answer);
    if (c.is_ko && failing) koFails.push(c.control_key);
    else if (c.weight === "high" && failing) highFails.push(c.control_key);
  }
  const score = tw ? Math.round((1000 * def) / tw) / 10 : 0;
  let tier = score <= 20 ? 1 : score <= 40 ? 2 : score <= 60 ? 3 : 4;
  if (highFails.length) tier = Math.max(tier, 3);
  if (koFails.length) tier = 4;
  return { score, tier, koFails, highFails };
}

export function TierBadge({ tier, label }: { tier: number | null; label?: string }) {
  if (tier == null) return <span className="muted">—</span>;
  return <span className={`tier ${TIER_CLASS[tier] || ""}`}>Tier {tier}{label ? ` · ${label}` : ""}</span>;
}

const WEIGHT_TITLE: Record<string, string> = {
  low: "Low risk weight — counts 1× toward the score.",
  medium: "Medium risk weight — counts 2× toward the score.",
  high: "High risk weight — counts 3×; a No/Unknown here forces at least Tier 3.",
};

export function Weight({ w }: { w: string }) {
  return <span className={`badge ${w}`} title={WEIGHT_TITLE[w] || "risk weight"}>{w}</span>;
}

const SOURCE_TITLE: Record<string, string> = {
  auto: "Answered automatically from an objective cloud fact — accepted as-is.",
  attested: "Answered from a documented platform/vendor commitment (see the evidence link) — accepted as-is; you may still override.",
  suggested: "Suggested from the provider's documentation — confirm or override before you can submit.",
  human: "Answered or confirmed by a reviewer.",
  carried: "Carried forward from the approved precedent review (same vendor and governing terms). You may still override it.",
  manual: "No reliable cloud signal — a reviewer must answer this.",
};

export function SourceBadge({ source }: { source: string | null }) {
  const key = source || "manual";
  const t = SOURCE_TITLE[key];
  if (source === "auto") return <span className="badge src-auto" title={t}>✓ auto</span>;
  if (source === "attested") return <span className="badge src-attested" title={t}>✓ attested</span>;
  if (source === "suggested") return <span className="badge src-suggested" title={t}>confirm</span>;
  if (source === "human") return <span className="badge src-human" title={t}>reviewed</span>;
  if (source === "carried") return <span className="badge src-carried" title={t}>carried</span>;
  return <span className="badge src-manual" title={t}>manual</span>;
}

// NIST AI 600-1 Generative-AI risk categories (the coloured control tags).
export const GAI_LABELS: Record<string, string> = {
  cbrn: "CBRN — chemical/biological/radiological/nuclear information or capability uplift",
  confabulation: "Confabulation — confidently stated false or fabricated output",
  dangerous_violent_hateful: "Dangerous, violent, or hateful content",
  data_privacy: "Data privacy — leakage or misuse of personal/sensitive data",
  environmental: "Environmental impact — energy/compute footprint",
  harmful_bias: "Harmful bias & homogenization",
  human_ai_config: "Human-AI configuration — over-reliance, automation bias, unclear oversight",
  information_integrity: "Information integrity — mis/disinformation, deepfakes",
  information_security: "Information security — prompt injection, jailbreak, model/data poisoning",
  intellectual_property: "Intellectual property — infringement, copyright, trade secrets",
  obscene_abusive: "Obscene, degrading, and/or abusive content (incl. CSAM/NCII)",
  value_chain: "Value chain & component integration — opaque provenance / third-party dependencies",
};

export function gaiTitle(code: string): string {
  return GAI_LABELS[code] || "NIST AI 600-1 GenAI risk category";
}

export function BadgeLegend() {
  return (
    <details className="legend">
      <summary>What do the labels on each question mean?</summary>
      <div className="legend-row"><span className="badge">GOVERN 1.1</span><span>The NIST AI RMF control this question maps to (its full statement is shown under the question).</span></div>
      <div className="legend-row"><span className="badge high">high</span><span>Risk weight — how heavily the control counts toward the score (low 1× / medium 2× / high 3×).</span></div>
      <div className="legend-row"><span className="badge ko">KNOCK-OUT</span><span>A critical control: a No/Unknown answer forces <strong>Tier 4 (blocked)</strong> regardless of the score.</span></div>
      <div className="legend-row"><span className="badge src-auto">✓ auto</span><span>Answered from a cloud fact and accepted. <span className="badge src-attested">✓ attested</span> = answered from a documented platform/vendor commitment (evidence linked). <span className="badge src-suggested">confirm</span> = suggested from provider docs, you must confirm. <span className="badge src-manual">manual</span> = you answer it. <span className="badge src-carried">carried</span> = adopted from an approved precedent review (same vendor &amp; terms).</span></div>
      <div className="legend-row"><span className="badge">data_privacy</span><span>NIST AI 600-1 <strong>Generative-AI risk categories</strong> this control addresses (hover any tag for its meaning).</span></div>
    </details>
  );
}

export function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString();
}

export function prettyState(s: string): string {
  return s.replace(/_/g, " ");
}

// What each tier means for approval — shown next to the score so the numbers
// aren't opaque. Mirrors the server-side gating in services/approvals.py.
export const TIER_INFO: Record<number, { band: string; label: string; meaning: string }> = {
  1: { band: "score 0–20", label: "Low", meaning: "Trustworthiness evidence is complete. Any approver may approve." },
  2: { band: "score 21–40", label: "Moderate", meaning: "Approve only with compensating conditions (e.g. logging, restricted data)." },
  3: { band: "score 41–60, or any high-weight gap", label: "Elevated", meaning: "Cannot self-approve — requires a named risk owner and governance review." },
  4: { band: "score 61–100, or any knock-out failure", label: "High", meaning: "Blocked. Only an admin may approve, with a documented override reason." },
};

export function ScoreLegend() {
  return (
    <details className="legend">
      <summary>What do the score and tiers mean?</summary>
      <p className="muted">
        Each control is answered Yes/Partial/No/Unknown and weighted (low/medium/high).
        The <strong>risk score</strong> is the weighted share of unaddressed risk, 0–100
        (higher = more risk). The <strong>tier</strong> comes from the score band, but two
        gates override it: any <strong>high-weight</strong> No/Unknown forces at least Tier 3,
        and any <strong>knock-out</strong> control failure forces Tier 4.
      </p>
      {[1, 2, 3, 4].map((t) => (
        <div key={t} className="legend-row">
          <span className={`tier ${TIER_CLASS[t]}`}>Tier {t}</span>
          <span><strong>{TIER_INFO[t].label}</strong> <span className="muted">({TIER_INFO[t].band})</span> — {TIER_INFO[t].meaning}</span>
        </div>
      ))}
    </details>
  );
}
