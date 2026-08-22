/**
 * Human review: the last stage of the pipeline, and the only place judgement enters.
 *
 * Three properties of the backend model have to survive into the UI, or the record stops meaning
 * what it says:
 *
 * 1. **Append-only.** A new review never replaces an old one. The history is shown in full,
 *    oldest first, because a senior reviewer disagreeing with a junior one is the thing an audit
 *    trail is for.
 * 2. **Staleness is visible.** A review decides a *verdict*. If the rule was revised or
 *    re-evaluation changed the outcome, the earlier decision no longer speaks for this finding, and
 *    rendering it as current would present an accepted FAIL as an accepted PASS.
 * 3. **A reason is mandatory.** The server refuses a blank note; so does this form, so the refusal
 *    is not a round trip.
 */

import { useState } from "react";

import type { Knowledge, Review } from "../api";
import { formatWhen, humanise, postJson } from "../api";
import { ErrorBox, Pill } from "./bits";

export function ReviewHistory({ reviews }: { reviews: Review[] }) {
  if (reviews.length === 0) return <p className="muted small">Nobody has reviewed this yet.</p>;

  // Three states, not two. `stale` comes from the server and means "this review decided a verdict
  // the finding no longer has". Among the reviews that are *not* stale, only the newest speaks for
  // the finding — the earlier ones were superseded by a colleague, which is different from being
  // stale and has to read differently. The list arrives oldest-first, so the current one is the last
  // that is not stale; this mirrors `Finding.current_review` rather than re-deciding anything, and
  // the server's own `review_state` agrees with it.
  let currentIndex = -1;
  reviews.forEach((review, index) => {
    if (!review.stale) currentIndex = index;
  });

  return (
    <div>
      {reviews.map((review, index) => (
        <div key={review.review_id} className="evidence">
          <div className="head">
            <Pill tone={review.stale ? undefined : review.decision}>
              {humanise(review.decision)}
            </Pill>
            <strong>{review.reviewer}</strong>
            <span className="muted small">{formatWhen(review.reviewed_at)}</span>
            {review.stale ? (
              <Pill tone="review">stale</Pill>
            ) : index === currentIndex ? (
              <Pill tone="pass">current</Pill>
            ) : (
              <Pill>superseded by a later review</Pill>
            )}
          </div>
          <div className={review.stale ? "stale" : ""} style={{ marginTop: 5 }}>
            {review.note}
          </div>
          {review.stale ? (
            <div className="small muted" style={{ marginTop: 5 }}>
              Recorded against outcome <span className="mono">{review.reviewed_outcome}</span> of
              rule version <span className="mono">{review.reviewed_rule_version}</span>, which is no
              longer what this finding says. It is kept, and it does not decide anything.
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function ReviewForm({
  findingId,
  knowledge,
  onRecorded,
}: {
  findingId: string;
  knowledge: Knowledge | undefined;
  onRecorded: () => void;
}) {
  const decisions = knowledge?.review_decisions ?? [];
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const chosen = decisions.find((item) => item.decision === decision);
  const ready = decision !== "" && note.trim() !== "" && reviewer.trim() !== "";

  async function submit() {
    setBusy(true);
    setError(undefined);
    try {
      await postJson(`/v1/findings/${findingId}/reviews`, { decision, note, reviewer });
      setNote("");
      setDecision("");
      onRecorded();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>Record a review</h3>
      <label htmlFor="decision">Decision</label>
      <select
        id="decision"
        value={decision}
        onChange={(event) => setDecision(event.target.value)}
      >
        <option value="">Choose…</option>
        {decisions.map((item) => (
          <option key={item.decision} value={item.decision}>
            {humanise(item.decision)}
          </option>
        ))}
      </select>
      {chosen ? (
        <p className="small muted" style={{ marginTop: 5 }}>
          {chosen.description}
        </p>
      ) : null}

      <label htmlFor="note">Reason (required)</label>
      <textarea
        id="note"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="What you checked, and what you concluded. A decision with no reason is indistinguishable from a mis-click."
      />

      <label htmlFor="reviewer">Reviewer</label>
      <input
        id="reviewer"
        type="text"
        value={reviewer}
        onChange={(event) => setReviewer(event.target.value)}
        placeholder="qs.reviewer"
      />

      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={!ready || busy} onClick={submit}>
          {busy ? "Recording…" : "Record review"}
        </button>
        <span className="small muted">
          Appends. Earlier reviews stay on the record.
        </span>
      </div>
      {error ? (
        <div style={{ marginTop: 8 }}>
          <ErrorBox error={error} />
        </div>
      ) : null}
    </div>
  );
}
