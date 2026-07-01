import { useEffect, useState } from "react";
import { ApiError, FrameworkStatus, Policy, UpdateCheck, api } from "../api";

const CLOUDS = ["azure", "gcp"] as const;

function fmt(d: string | null): string {
  return d ? new Date(d).toLocaleDateString() : "—";
}

export default function Admin({ isAdmin }: { isAdmin: boolean }) {
  const [regions, setRegions] = useState<Record<string, string[]>>({ azure: [], gcp: [] });
  const [draft, setDraft] = useState<Record<string, string>>({ azure: "", gcp: "" });
  const [fw, setFw] = useState<FrameworkStatus | null>(null);
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function loadFramework() {
    api.get<FrameworkStatus>("/framework").then(setFw).catch(() => {});
  }

  function checkForUpdates() {
    api.get<UpdateCheck>("/framework/check-updates").then(setCheck).catch((e) => setError(e.message));
  }

  useEffect(() => {
    api.get<Policy>("/policy")
      .then((p) => setRegions({ azure: p.approved_regions.azure || [], gcp: p.approved_regions.gcp || [] }))
      .catch((e) => setError(e.message));
    loadFramework();
  }, []);

  async function markReviewed() {
    setError(null); setMsg(null);
    try {
      const f = await api.post<FrameworkStatus>("/framework/reviewed", { notes: reviewNotes || null });
      setFw(f);
      setReviewNotes("");
      setMsg("Framework review recorded.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  function addRegion(cloud: string) {
    const r = draft[cloud].trim();
    if (r && !regions[cloud].includes(r)) {
      setRegions({ ...regions, [cloud]: [...regions[cloud], r].sort() });
    }
    setDraft({ ...draft, [cloud]: "" });
  }

  function removeRegion(cloud: string, r: string) {
    setRegions({ ...regions, [cloud]: regions[cloud].filter((x) => x !== r) });
  }

  async function savePolicy() {
    setError(null); setMsg(null);
    try {
      const p = await api.put<Policy>("/policy", { approved_regions: regions });
      setRegions({ azure: p.approved_regions.azure || [], gcp: p.approved_regions.gcp || [] });
      setMsg("Data-residency policy saved. New reviews will use it.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (!isAdmin) {
    return <div className="err">Admin role required. Switch to Admin (top-right).</div>;
  }

  return (
    <div>
      <h1>Configuration</h1>
      {error && <div className="err">{error}</div>}
      {msg && <div className="ok">{msg}</div>}

      {fw && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>Governance framework</h2>
            <div className="row">
              {fw.update_available ? (
                <span className="badge src-suggested" title={`A newer NIST release (${fw.latest_known_version}) is known than the version the questionnaire implements.`}>UPDATE AVAILABLE</span>
              ) : (
                <span className="badge src-auto" title="The questionnaire implements the latest known NIST release.">up to date</span>
              )}
              {fw.overdue && <span className="badge ko">REVIEW OVERDUE</span>}
            </div>
          </div>
          <p style={{ marginBottom: "0.4rem" }}>
            <strong>{fw.name}</strong>
          </p>
          <div className="row" style={{ gap: "1.5rem", fontSize: "0.85rem" }}>
            <span><span className="muted">RMF version</span> {fw.rmf_version || "—"}</span>
            <span><span className="muted">questionnaire</span> v{fw.questionnaire_version}</span>
            <span><span className="muted">controls</span> {fw.control_count}</span>
            <span><span className="muted">effective</span> {fw.effective_date || "—"}</span>
          </div>
          <div className="row" style={{ gap: "1rem", marginTop: "0.5rem", fontSize: "0.85rem" }}>
            {fw.references.map((r) => (
              <a key={r.doc || r.url || ""} href={r.url || "#"} target="_blank" rel="noreferrer">
                {r.doc} · {r.label} ↗
              </a>
            ))}
          </div>
          <div className="row" style={{ marginTop: "0.6rem" }}>
            <button className="secondary" onClick={checkForUpdates}>Check for updates</button>
            {check && (
              <span className="muted" style={{ fontSize: "0.82rem" }}>
                {check.up_to_date
                  ? `Up to date — implementing ${check.implemented_version}, latest known ${check.latest_known_version}.`
                  : `Update available — NIST ${check.latest_label} (${check.latest_published}), you implement ${check.implemented_version}.`}{" "}
                <a href={check.latest_url} target="_blank" rel="noreferrer">NIST ↗</a>
              </span>
            )}
          </div>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "0.9rem 0" }} />
          <div className="row" style={{ gap: "1.5rem", fontSize: "0.85rem" }}>
            <span><span className="muted">last reviewed</span> {fw.last_reviewed_at ? fmt(fw.last_reviewed_at) : "never"}</span>
            {fw.reviewed_by && <span><span className="muted">by</span> {fw.reviewed_by}</span>}
            <span><span className="muted">next due</span> {fmt(fw.next_review_due)} ({fw.review_interval_days}d cadence)</span>
          </div>
          {fw.notes && <p className="muted" style={{ fontSize: "0.85rem" }}>Note: {fw.notes}</p>}
          <div className="row" style={{ marginTop: "0.6rem" }}>
            <input
              style={{ flex: 1 }}
              placeholder="review note (e.g. confirmed against current NIST release)"
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
            />
            <button onClick={markReviewed}>Mark reviewed</button>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Data-residency policy</h2>
        <p className="muted">
          Approved regions <strong>per cloud</strong>. The auto-answer engine flags any model whose
          region is outside its cloud's set as a residency knock-out. This is <strong>your</strong>{" "}
          policy — Azure and GCP use different region names, so they're configured separately.
        </p>
        {CLOUDS.map((cloud) => (
          <div key={cloud} style={{ marginTop: "1rem" }}>
            <h3>{cloud} regions</h3>
            <div className="chips">
              {regions[cloud].map((r) => (
                <span className="chip" key={r}>
                  {r}
                  <button className="chip-x" title="remove" onClick={() => removeRegion(cloud, r)}>×</button>
                </span>
              ))}
              {regions[cloud].length === 0 && (
                <span className="muted">No approved {cloud} regions — every {cloud} deployment will fail residency.</span>
              )}
            </div>
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <input
                placeholder={cloud === "azure" ? "add region (e.g. eastus)" : "add region (e.g. us-central1)"}
                value={draft[cloud]}
                onChange={(e) => setDraft({ ...draft, [cloud]: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && addRegion(cloud)}
              />
              <button className="secondary" onClick={() => addRegion(cloud)}>Add</button>
            </div>
          </div>
        ))}
        <div className="row" style={{ marginTop: "1rem" }}>
          <button onClick={savePolicy}>Save policy</button>
        </div>
      </div>
    </div>
  );
}
