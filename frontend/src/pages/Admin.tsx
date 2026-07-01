import { useEffect, useState } from "react";
import { ApiError, FrameworkStatus, Policy, Source, api } from "../api";

const CLOUDS = ["azure", "gcp"] as const;

function fmt(d: string | null): string {
  return d ? new Date(d).toLocaleDateString() : "—";
}

export default function Admin({ isAdmin }: { isAdmin: boolean }) {
  const [regions, setRegions] = useState<Record<string, string[]>>({ azure: [], gcp: [] });
  const [draft, setDraft] = useState<Record<string, string>>({ azure: "", gcp: "" });
  const [sources, setSources] = useState<Source[]>([]);
  const [src, setSrc] = useState({ cloud: "azure", display_name: "", scope: "" });
  const [fw, setFw] = useState<FrameworkStatus | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function loadFramework() {
    api.get<FrameworkStatus>("/framework").then(setFw).catch(() => {});
  }

  useEffect(() => {
    api.get<Policy>("/policy")
      .then((p) => setRegions({ azure: p.approved_regions.azure || [], gcp: p.approved_regions.gcp || [] }))
      .catch((e) => setError(e.message));
    api.get<Source[]>("/discovery/sources").then(setSources).catch(() => {});
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

  async function addSource() {
    setError(null); setMsg(null);
    try {
      await api.post<Source>("/discovery/sources", src);
      setSrc({ cloud: "azure", display_name: "", scope: "" });
      setSources(await api.get<Source[]>("/discovery/sources"));
      setMsg("Discovery source added.");
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
            {fw.overdue && <span className="badge ko">REVIEW OVERDUE</span>}
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

      <div className="card">
        <h2>Discovery sources</h2>
        <p className="muted">Cloud scopes queried to populate the review dropdowns.</p>
        <table>
          <thead>
            <tr><th>Cloud</th><th>Name</th><th>Scope</th><th>Enabled</th></tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td>{s.cloud}</td>
                <td>{s.display_name}</td>
                <td className="muted" style={{ fontSize: "0.8rem" }}>{s.scope}</td>
                <td>{s.enabled ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: "0.75rem" }}>
          <select value={src.cloud} onChange={(e) => setSrc({ ...src, cloud: e.target.value })}>
            <option value="azure">azure</option>
            <option value="gcp">gcp</option>
          </select>
          <input placeholder="display name" value={src.display_name} onChange={(e) => setSrc({ ...src, display_name: e.target.value })} />
          <input placeholder="scope (subscription / org id)" value={src.scope} onChange={(e) => setSrc({ ...src, scope: e.target.value })} />
          <button onClick={addSource} disabled={!src.display_name || !src.scope}>Add source</button>
        </div>
      </div>
    </div>
  );
}
