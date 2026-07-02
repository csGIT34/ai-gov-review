import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AdoptResult, ApiError, Control, Decision, Me, Precedent, ReviewDetail as RD, RiskScore, api } from "../api";
import {
  BadgeLegend,
  ScoreLegend,
  SourceBadge,
  TIER_INFO,
  TierBadge,
  Weight,
  computePreview,
  fmtDate,
  gaiTitle,
  prettyState,
} from "../ui";

const FN_ORDER = ["GOVERN", "MAP", "MEASURE", "MANAGE"];
const ANSWERS = ["yes", "partial", "no", "unknown"];
const TERMINAL = ["approved", "approved_with_conditions", "rejected"];

export default function ReviewDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [d, setD] = useState<RD | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [prec, setPrec] = useState<Precedent | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // approval form
  const [justification, setJustification] = useState("");
  const [conditions, setConditions] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [iAmOwner, setIAmOwner] = useState(false);

  // delete: first click arms, second click deletes; decided reviews need a reason
  const [delArmed, setDelArmed] = useState(false);
  const [delReason, setDelReason] = useState("");

  // isStale guards the fire-and-forget fetches: navigating to another review
  // re-runs the [id] effect without unmounting, so a slow response for the OLD
  // id must not land on the NEW review's state.
  async function reload(isStale: () => boolean = () => false) {
    const detail = await api.get<RD>(`/reviews/${id}`);
    if (isStale()) return;
    setD(detail);
    api.get<Precedent>(`/reviews/${id}/precedent`)
      .then((p) => { if (!isStale()) setPrec(p); })
      .catch(() => {});
    if (TERMINAL.includes(detail.state)) {
      api.get<Decision>(`/reviews/${id}/decision`)
        .then((dec) => { if (!isStale()) setDecision(dec); })
        .catch(() => {});
    }
  }
  useEffect(() => {
    let stale = false;
    setError(null); setMsg(null);
    setD(null); setPrec(null); setDecision(null);
    setJustification(""); setConditions(""); setOverrideReason(""); setIAmOwner(false);
    setDelArmed(false); setDelReason("");
    reload(() => stale).catch((e) => { if (!stale) setError(e.message); });
    api.get<Me>("/me").then(setMe).catch(() => {});
    return () => { stale = true; };
  }, [id]);

  // Rubber-stamp helper: when a fast-tracked review reaches the approval gate,
  // prefill the justification with the precedent reference (approver may edit).
  // Must stay above the early returns below — hooks run on every render.
  useEffect(() => {
    if (d?.state === "scored" && d.precedent_id && prec?.precedent) {
      const p = prec.precedent;
      setJustification((j) =>
        j ||
        `Approved per precedent: ${p.model_name}${p.model_version ? ` v${p.model_version}` : ""} ` +
        `(precedent ${p.id.slice(0, 8)}, ${p.decision_state.replace(/_/g, " ")}` +
        `${p.tier ? `, Tier ${p.tier}` : ""}) under identical governing terms` +
        `${p.terms?.label ? ` (${p.terms.label})` : ""}. ` +
        `Cloud-fact controls were re-evaluated fresh for this model.`
      );
    }
  }, [d?.state, d?.precedent_id, prec]);

  if (error && !d) return <div className="err">{error}</div>;
  if (!d) return <div className="muted">Loading…</div>;

  const editable = d.state === "pending_review" || d.state === "in_review";
  const total = d.controls.length;
  const unanswered = d.controls.filter((c) => !c.answer);
  const toConfirm = d.controls.filter((c) => c.answer && c.answer_source === "suggested");
  const settled = total - unanswered.length - toConfirm.length;
  const canSubmit = editable && unanswered.length === 0 && toConfirm.length === 0;
  const preview = computePreview(d.controls);
  const score = d.current_score;
  const isApprover = me?.roles.some((r) => r === "approver" || r === "admin");
  const isAdmin = me?.roles.includes("admin");
  const isDecided = TERMINAL.includes(d.state);

  async function removeReview() {
    if (!delArmed) {
      setDelArmed(true);
      return;
    }
    setBusy(true); setError(null);
    try {
      const q = isDecided ? `?reason=${encodeURIComponent(delReason.trim())}` : "";
      await api.del(`/reviews/${id}${q}`);
      nav("/");
    } catch (e) {
      setDelArmed(false);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function patchLocal(cid: string, patch: Partial<Control>) {
    setD((prev) => (prev ? { ...prev, controls: prev.controls.map((c) => (c.id === cid ? { ...c, ...patch } : c)) } : prev));
  }

  async function setAnswer(c: Control, answer: string) {
    patchLocal(c.id, { answer });
    try {
      await api.patch(`/reviews/${id}/controls/${c.id}`, {
        answer,
        evidence_url: c.evidence_url || null,
        evidence_note: c.evidence_note || null,
      });
      if (d && d.state === "pending_review") setD({ ...d, state: "in_review" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function saveEvidence(c: Control) {
    if (!c.answer) return;
    try {
      await api.patch(`/reviews/${id}/controls/${c.id}`, {
        answer: c.answer,
        evidence_url: c.evidence_url || null,
        evidence_note: c.evidence_note || null,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function adoptPrecedent() {
    setBusy(true); setError(null); setMsg(null);
    try {
      const res = await api.post<AdoptResult>(`/reviews/${id}/adopt-precedent`);
      await reload();
      setMsg(`Adopted ${res.carried_count} judgment answers from the precedent review. Cloud-fact checks stay computed fresh for this model — review the score and submit.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true); setError(null); setMsg(null);
    try {
      await api.post(`/reviews/${id}/submit`);
      await reload();
      setMsg("Submitted and scored.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function decide(dec: string) {
    setBusy(true); setError(null); setMsg(null);
    try {
      await api.post(`/reviews/${id}/decision`, {
        decision: dec,
        justification,
        conditions: conditions || null,
        risk_owner_id: iAmOwner && me ? me.id : null,
        override_reason: overrideReason || null,
      });
      await reload();
      setMsg(`Decision recorded: ${dec.replace(/_/g, " ")}.`);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
      else setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Two teams answer this questionnaire: the infrastructure team owns the
  // model/platform facts (mostly machine-settled), the developer team building
  // on the model owns the use-case judgments.
  const ownerSections = [
    {
      key: "platform",
      title: "Infrastructure team",
      subtitle: "model & platform controls",
      blurb:
        "Owned by the infrastructure / cloud-governance team: facts about the model itself and the cloud platform hosting it (residency, network, encryption, filters, terms, certifications). Most settle automatically from cloud facts and documented platform commitments.",
      items: d.controls.filter((c) => c.owner !== "use_case"),
    },
    {
      key: "use_case",
      title: "Developer team",
      subtitle: "use-case controls",
      blurb:
        "Owned by the developer team building on the model: judgments about THIS specific use (intended use, evaluation for the task, bias for affected users, oversight, incident runbook, impact).",
      items: d.controls.filter((c) => c.owner === "use_case"),
    },
  ].map((s) => ({
    ...s,
    needsAction: s.items.filter((c) => !c.answer || c.answer_source === "suggested").length,
    groups: FN_ORDER.map((fn) => ({ fn, items: s.items.filter((c) => c.nist_function === fn) })).filter(
      (g) => g.items.length > 0
    ),
  }));

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>{d.model.model_name}{d.model.model_version ? ` v${d.model.model_version}` : ""}</h1>
        <span className="state">{prettyState(d.state)}</span>
      </div>
      <div className="card row" style={{ gap: "1.5rem", fontSize: "0.85rem" }}>
        <span><span className="muted">cloud</span> {d.model.cloud}</span>
        <span><span className="muted">vendor</span> {d.model.vendor}</span>
        <span>
          <span className="muted">regions ({d.model.regions.length})</span>{" "}
          {d.model.regions.length ? d.model.regions.join(", ") : "—"}
        </span>
        <span className="muted" style={{ fontSize: "0.75rem" }}>{d.model.resource_id}</span>
        {d.precedent_id && (
          <span>
            <span className="badge src-carried" data-tip="Judgment answers were adopted from a stored precedent (see Admin → Precedents).">fast-tracked</span>
            {prec?.precedent?.source_review_id && (
              <> <Link to={`/reviews/${prec.precedent.source_review_id}`}>source review ↗</Link></>
            )}
          </span>
        )}
      </div>

      {error && <div className="err">{error}</div>}
      {msg && <div className="ok">{msg}</div>}

      {editable && !d.precedent_id && prec?.available && prec.precedent && (
        <div className="card precedent">
          <h3>⚡ Fast-track available — same vendor, same terms</h3>
          <div>
            <strong>{prec.precedent.model_name}{prec.precedent.model_version ? ` v${prec.precedent.model_version}` : ""}</strong>{" "}
            was {prec.precedent.decision_state.replace(/_/g, " ")}
            {prec.precedent.tier ? <> at <strong>Tier {prec.precedent.tier}</strong></> : null}
            {prec.precedent.decided_at ? ` on ${fmtDate(prec.precedent.decided_at)}` : ""} under the same
            governing terms{prec.model_terms?.label ? <> (<em>{prec.model_terms.label}</em>)</> : null}.
          </div>
          <p className="why">
            Adopting carries its <strong>{prec.carryable_count} judgment answers</strong> into this review
            (marked <span className="badge src-carried">carried</span> — you can still override any of them).
            The cloud-fact checks (residency, network, encryption, filters…) are <strong>always re-computed
            fresh for this model</strong> and can still block approval.
          </p>
          <button disabled={busy} onClick={adoptPrecedent}>
            Adopt precedent answers ({prec.carryable_count})
          </button>
        </div>
      )}

      {editable && !d.precedent_id && prec && !prec.available && prec.reasons.length > 0 && (
        <div className="card precedent blocked">
          <h3>Full review required — no usable precedent</h3>
          {prec.reasons.map((r, i) => (
            <p className="why" key={i}>{r}</p>
          ))}
        </div>
      )}

      <div className="grid">
        <div>
          <BadgeLegend />
          {ownerSections.map((s) => (
            <details key={s.key} className={`owner-section ${s.key}`} open>
              <summary className="owner-head">
                <h2>{s.title}</h2>
                <span className="muted owner-subtitle">{s.subtitle} · {s.items.length}</span>
                <span className={`badge ${s.needsAction === 0 ? "src-auto" : "src-suggested"}`}>
                  {s.needsAction === 0
                    ? "✓ nothing left to answer"
                    : `${s.needsAction} need${s.needsAction === 1 ? "s" : ""} attention`}
                </span>
              </summary>
              <p className="muted owner-blurb">{s.blurb}</p>
              {s.groups.map(({ fn, items }) => (
            <div key={fn}>
              <h3>{fn}</h3>
              {items.map((c) => (
                <div className="control" key={c.id}>
                  <div className="q">{c.question_text}</div>
                  <div className="nist">
                    <strong>{c.control_id}</strong>
                    {c.nist_control ? ` — ${c.nist_control.replace(/^[A-Z]+ [\d.]+ — /, "")}` : ""}
                    {c.nist_url && (
                      <a href={c.nist_url} target="_blank" rel="noreferrer"> · NIST Playbook ↗</a>
                    )}
                  </div>
                  {c.evidence_needed && (
                    <div className="evidence-hint">Evidence to look for: {c.evidence_needed}</div>
                  )}
                  <div className="meta">
                    <span className="badge" data-tip={c.nist_control || "NIST AI RMF control"}>{c.control_id}</span>
                    <Weight w={c.weight} />
                    {c.is_ko && (
                      <span className="badge ko" data-tip="Knock-out control: a No/Unknown answer forces Tier 4 (blocked), regardless of score.">KNOCK-OUT</span>
                    )}
                    <SourceBadge source={c.answer_source} />
                    {c.gai_categories.map((g) => (
                      <span key={g} className="badge" style={{ fontSize: "0.66rem" }} data-tip={gaiTitle(g)}>{g}</span>
                    ))}
                  </div>
                  <div className="answers">
                    {ANSWERS.map((a) => (
                      <button
                        key={a}
                        disabled={!editable}
                        className={c.answer === a ? `sel-${a}` : ""}
                        onClick={() => setAnswer(c, a)}
                      >
                        {a}
                      </button>
                    ))}
                    {editable && c.answer_source === "suggested" && c.auto_answer && (
                      <button className="accept" onClick={() => setAnswer(c, c.auto_answer!)}>
                        ✓ Accept "{c.auto_answer}"
                      </button>
                    )}
                  </div>
                  {c.auto_rationale && (
                    <div className="rationale">
                      <strong>
                        {c.answer_source === "auto"
                          ? "Auto: "
                          : c.answer_source === "attested"
                          ? "Attested: "
                          : c.answer_source === "suggested"
                          ? "Suggested: "
                          : "Guidance: "}
                      </strong>
                      {c.auto_rationale}
                      {c.evidence_url && (
                        <a href={c.evidence_url} target="_blank" rel="noreferrer">evidence ↗</a>
                      )}
                    </div>
                  )}
                  {c.answer && (
                    <details className="evidence">
                      <summary>
                        Evidence & notes
                        {(c.evidence_note || c.evidence_url) && (
                          <span className="badge src-human" style={{ marginLeft: "0.5rem" }}>●</span>
                        )}
                      </summary>
                      <textarea
                        placeholder="What did you check, where, and what did you find? (optional — saved automatically)"
                        rows={4}
                        disabled={!editable}
                        value={c.evidence_note || ""}
                        onChange={(e) => patchLocal(c.id, { evidence_note: e.target.value })}
                        onBlur={() => saveEvidence(c)}
                      />
                      <input
                        style={{ width: "100%", marginTop: "0.35rem" }}
                        placeholder="supporting link (optional)"
                        disabled={!editable}
                        value={c.evidence_url || ""}
                        onChange={(e) => patchLocal(c.id, { evidence_url: e.target.value })}
                        onBlur={() => saveEvidence(c)}
                      />
                    </details>
                  )}
                </div>
              ))}
            </div>
              ))}
            </details>
          ))}
        </div>

        <div className="scorepanel">
          <div className="card">
            {score ? (
              <>
                <div className="muted">Risk score</div>
                <div className="big-score">{score.overall_score}</div>
                <div className="muted" style={{ fontSize: "0.72rem" }}>0–100 · higher = more unaddressed risk</div>
                <div style={{ margin: "0.5rem 0" }}>
                  <TierBadge tier={score.tier} label={score.tier_label} />
                </div>
                <div className="muted" style={{ fontSize: "0.82rem" }}>{TIER_INFO[score.tier]?.meaning}</div>
                {score.triggered_gates.map((g, i) => (
                  <div className="gate" key={i}>{g.reason}</div>
                ))}
                <h3>Function deficits</h3>
                {Object.entries(score.function_deficits).map(([fn, v]) => (
                  <div key={fn}>
                    <div className="deficit-row"><span>{fn}</span><span>{Math.round(v * 100)}%</span></div>
                    <div className="bar"><div style={{ width: `${v * 100}%` }} /></div>
                  </div>
                ))}
              </>
            ) : (
              <>
                <div className="muted">Preview score <span style={{ fontSize: "0.7rem" }}>(updates as you answer)</span></div>
                <div className="big-score">{preview.score}</div>
                <div className="muted" style={{ fontSize: "0.72rem" }}>0–100 · higher = more unaddressed risk</div>
                <div style={{ margin: "0.5rem 0" }}><TierBadge tier={preview.tier} /></div>
                <div className="muted" style={{ fontSize: "0.82rem" }}>{TIER_INFO[preview.tier]?.meaning}</div>
                {preview.koFails.length > 0 && <div className="gate">Knock-out failures: {preview.koFails.join(", ")}</div>}
                {preview.highFails.length > 0 && <div className="gate">High-weight failures: {preview.highFails.join(", ")}</div>}
                <div className="muted" style={{ marginTop: "0.5rem" }}>
                  {settled}/{total} settled
                  {toConfirm.length > 0 && ` · ${toConfirm.length} to confirm`}
                  {unanswered.length > 0 && ` · ${unanswered.length} to answer`}
                </div>
              </>
            )}
            <ScoreLegend />
          </div>

          {editable && (
            <button disabled={!canSubmit || busy} onClick={submit} style={{ width: "100%" }}>
              {unanswered.length > 0
                ? `${unanswered.length} control${unanswered.length > 1 ? "s" : ""} to answer`
                : toConfirm.length > 0
                ? `${toConfirm.length} suggestion${toConfirm.length > 1 ? "s" : ""} to confirm`
                : busy
                ? "Submitting…"
                : "Submit for scoring"}
            </button>
          )}

          {d.state === "scored" && score && (
            <div className="card">
              <h3>Approval gate</h3>
              {!isApprover && <div className="muted">Switch to Approver/Admin (top-right) to decide.</div>}
              <TierHint tier={score.tier} />
              <label>Justification (required)</label>
              <textarea value={justification} onChange={(e) => setJustification(e.target.value)} />
              {score.tier === 2 && (
                <>
                  <label>Compensating conditions (required for Tier 2)</label>
                  <textarea value={conditions} onChange={(e) => setConditions(e.target.value)} />
                </>
              )}
              {score.tier === 3 && (
                <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={iAmOwner} onChange={(e) => setIAmOwner(e.target.checked)} />
                  I am the named risk owner (required for Tier 3)
                </label>
              )}
              {score.tier === 4 && (
                <>
                  <label>Override reason (admin only — required to approve Tier 4)</label>
                  <textarea value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} />
                </>
              )}
              <div className="row" style={{ marginTop: "0.6rem" }}>
                <button disabled={busy || !isApprover} onClick={() => decide(score.tier === 2 ? "approve_with_conditions" : "approve")}>
                  {score.tier === 2 ? "Approve w/ conditions" : "Approve"}
                </button>
                <button className="danger" disabled={busy || !isApprover} onClick={() => decide("reject")}>Reject</button>
              </div>
            </div>
          )}

          {decision && (
            <div className="card">
              <h3>Decision</h3>
              <div><strong>{decision.decision.replace(/_/g, " ")}</strong></div>
              {decision.overridden_tier && <div className="gate">Override of Tier {decision.overridden_tier}: {decision.override_reason}</div>}
              {decision.conditions && <div className="muted">Conditions: {decision.conditions}</div>}
              <div className="muted" style={{ marginTop: "0.4rem" }}>{decision.justification}</div>
              <div className="muted" style={{ fontSize: "0.75rem", marginTop: "0.3rem" }}>{fmtDate(decision.decided_at)}</div>
            </div>
          )}

          {d.facts_snapshot && (
            <div className="card">
              <details>
                <summary style={{ cursor: "pointer", color: "var(--accent)", fontWeight: 600 }}>
                  Point-in-time CSP snapshot
                </summary>
                <p className="muted" style={{ fontSize: "0.78rem" }}>
                  The cloud facts and platform attestation documents this review's machine answers
                  were derived from, frozen at {fmtDate(d.facts_snapshot.captured_at)}. Live model
                  facts may change on re-discovery; this record doesn't.
                </p>
                <pre className="snapshot">{JSON.stringify(d.facts_snapshot, null, 2)}</pre>
              </details>
            </div>
          )}

          {(!isDecided || isAdmin) && (
            <div className="card danger-zone">
              <h3>Danger zone</h3>
              {isDecided ? (
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  This review is a decided governance record. Only an admin may delete it,
                  a reason is required, and the deletion is audited. A review other reviews
                  used as their fast-track precedent cannot be deleted.
                </p>
              ) : (
                <p className="muted" style={{ fontSize: "0.8rem" }}>
                  Deletes this open review and its answers (audited). The model itself is unaffected.
                </p>
              )}
              {isDecided && (
                <>
                  <label>Reason (required)</label>
                  <textarea value={delReason} onChange={(e) => setDelReason(e.target.value)} />
                </>
              )}
              <button
                className={delArmed ? "danger" : "secondary"}
                disabled={busy || (isDecided && !delReason.trim())}
                onClick={removeReview}
              >
                {delArmed ? "Click again to permanently delete" : "Delete review"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TierHint({ tier }: { tier: number }) {
  const hints: Record<number, string> = {
    1: "Tier 1 — any approver may approve.",
    2: "Tier 2 — approval requires compensating conditions.",
    3: "Tier 3 — approval requires a named risk owner.",
    4: "Tier 4 / knock-out — blocked. Only an admin may approve, with an override reason.",
  };
  return <div className="muted" style={{ marginBottom: "0.4rem" }}>{hints[tier]}</div>;
}
