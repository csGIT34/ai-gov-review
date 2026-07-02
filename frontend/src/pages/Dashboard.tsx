import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ModelOut, Review } from "../api";
import { TierBadge, fmtDate, prettyState } from "../ui";

const DECIDED = new Set(["approved", "approved_with_conditions", "rejected"]);

export default function Dashboard() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [models, setModels] = useState<Record<string, ModelOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmDel, setConfirmDel] = useState<string | null>(null); // review id armed for delete

  useEffect(() => {
    Promise.all([api.get<Review[]>("/reviews"), api.get<ModelOut[]>("/models")])
      .then(([rv, ms]) => {
        setReviews(rv);
        setModels(Object.fromEntries(ms.map((m) => [m.id, m])));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function remove(r: Review) {
    if (confirmDel !== r.id) {
      setConfirmDel(r.id); // first click arms; second click deletes
      return;
    }
    setConfirmDel(null);
    try {
      await api.del(`/reviews/${r.id}`);
      setReviews((prev) => prev.filter((x) => x.id !== r.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const counts = reviews.reduce<Record<string, number>>((acc, r) => {
    acc[r.state] = (acc[r.state] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Reviews</h1>
        <Link to="/new"><button>+ New review</button></Link>
      </div>

      {error && <div className="err">{error}</div>}

      <div className="card row" style={{ gap: "1.5rem" }}>
        {Object.keys(counts).length === 0 && <span className="muted">No reviews yet.</span>}
        {Object.entries(counts).map(([s, n]) => (
          <span key={s}>
            <strong>{n}</strong> <span className="muted">{prettyState(s)}</span>
          </span>
        ))}
      </div>

      <div className="card">
        {loading ? (
          <span className="muted">Loading…</span>
        ) : reviews.length === 0 ? (
          <span className="muted">
            Nothing to review yet. <Link to="/new">Start a review</Link>.
          </span>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Cloud / Vendor</th>
                <th>State</th>
                <th>Tier</th>
                <th>Score</th>
                <th>Opened</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((r) => {
                const m = models[r.model_id];
                return (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/reviews/${r.id}`}>
                        {m ? `${m.model_name}${m.model_version ? ` v${m.model_version}` : ""}` : r.model_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="muted">{m ? `${m.cloud} / ${m.vendor}` : "—"}</td>
                    <td className="state">{prettyState(r.state)}</td>
                    <td><TierBadge tier={m?.latest_tier ?? null} /></td>
                    <td>{m?.latest_score ?? "—"}</td>
                    <td className="muted">{fmtDate(r.opened_at)}</td>
                    <td>
                      {!DECIDED.has(r.state) && (
                        <button
                          className={confirmDel === r.id ? "danger row-del" : "secondary row-del"}
                          title={confirmDel === r.id ? "Click again to permanently delete this open review" : "Delete this open review"}
                          onMouseLeave={() => confirmDel === r.id && setConfirmDel(null)}
                          onClick={() => remove(r)}
                        >
                          {confirmDel === r.id ? "confirm ✕" : "✕"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
