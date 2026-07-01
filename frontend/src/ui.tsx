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

export function Weight({ w }: { w: string }) {
  return <span className={`badge ${w}`}>{w}</span>;
}

export function SourceBadge({ source }: { source: string | null }) {
  if (source === "auto") return <span className="badge src-auto">✓ auto</span>;
  if (source === "suggested") return <span className="badge src-suggested">confirm</span>;
  if (source === "human") return <span className="badge src-human">reviewed</span>;
  return <span className="badge src-manual">manual</span>;
}

export function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString();
}

export function prettyState(s: string): string {
  return s.replace(/_/g, " ");
}
