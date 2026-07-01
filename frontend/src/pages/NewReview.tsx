import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, DiscoveredModel, Review, Source, api } from "../api";

export default function NewReview() {
  const nav = useNavigate();
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [vendors, setVendors] = useState<string[]>([]);
  const [vendor, setVendor] = useState("");
  const [models, setModels] = useState<DiscoveredModel[]>([]);
  const [pick, setPick] = useState(""); // index into models
  const [error, setError] = useState<string | null>(null);
  const [dupId, setDupId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<Source[]>("/discovery/sources").then(setSources).catch((e) => setError(e.message));
  }, []);

  // Cloud -> vendors
  useEffect(() => {
    setVendors([]); setVendor(""); setModels([]); setPick("");
    if (!sourceId) return;
    api.get<string[]>(`/discovery/sources/${sourceId}/vendors`).then(setVendors).catch((e) => setError(e.message));
  }, [sourceId]);

  // Vendor -> models
  useEffect(() => {
    setModels([]); setPick("");
    if (!sourceId || !vendor) return;
    api
      .get<DiscoveredModel[]>(`/discovery/sources/${sourceId}/vendors/${vendor}/models`)
      .then(setModels)
      .catch((e) => setError(e.message));
  }, [vendor]);

  async function start() {
    setError(null); setDupId(null); setBusy(true);
    const m = models[Number(pick)];
    try {
      const review = await api.post<Review>("/reviews", {
        source_id: sourceId,
        vendor,
        resource_id: m.resource_id,
        model_version: m.model_version,
      });
      nav(`/reviews/${review.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.data?.details?.review_id) {
        setDupId(e.data.details.review_id);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Start a governance review</h1>
      <p className="muted">Pick a model discovered in your cloud. A NIST AI RMF review is opened for it.</p>

      {error && <div className="err">{error}</div>}
      {dupId && (
        <div className="err">
          An open review already exists for this model.{" "}
          <Link to={`/reviews/${dupId}`}>Go to it →</Link>
        </div>
      )}

      <div className="card">
        <label>Cloud source</label>
        <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">— select cloud —</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.display_name} ({s.cloud})</option>
          ))}
        </select>

        {sourceId && (
          <>
            <label>Model vendor</label>
            <select value={vendor} onChange={(e) => setVendor(e.target.value)}>
              <option value="">— select vendor —</option>
              {vendors.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </>
        )}

        {vendor && (
          <>
            <label>Model</label>
            <select value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">— select model —</option>
              {models.map((m, i) => (
                <option key={m.resource_id} value={i}>{m.label}</option>
              ))}
            </select>
          </>
        )}

        <div className="spacer-v" />
        <button disabled={!pick || busy} onClick={start}>
          {busy ? "Opening…" : "Start review"}
        </button>
      </div>
    </div>
  );
}
