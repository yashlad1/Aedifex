/**
 * Surfaces 5, 6 and 7 — one finding, its evidence, and its review history.
 *
 * The primary product surface, and it answers six questions in this order, because that is the order
 * a reviewer asks them:
 *
 * 1. what was checked — the rule, named and versioned;
 * 2. what values were compared — expected against observed, verbatim;
 * 3. what happened — the outcome, and never a score;
 * 4. why it matters — the rule's own summary sentence;
 * 5. what evidence supports it — every citation, by kind, each openable at its page;
 * 6. what to inspect next — for INCONCLUSIVE, the evidence that was missing.
 *
 * An INCONCLUSIVE finding is deliberately not styled as a failure. It means the rule could not
 * source what it needed, which is a gap in the corpus and not a defect in the document.
 */

import { Link, useParams } from "react-router-dom";

import type { Finding, Knowledge } from "../api";
import { formatWhen, humanise, useApi } from "../api";
import { ErrorBox, Loading, Pill } from "../components/bits";
import { EvidenceCard } from "../components/EvidenceCard";
import { ReviewForm, ReviewHistory } from "../components/ReviewPanel";

export function FindingPage() {
  const { projectId = "", findingId = "" } = useParams();
  const finding = useApi<Finding>(`/v1/findings/${findingId}`);
  const knowledge = useApi<Knowledge>("/v1/knowledge");

  if (finding.loading) return <Loading what="the finding" />;
  if (finding.error) return <ErrorBox error={finding.error} />;
  if (!finding.data) return null;

  const row = finding.data;
  const rule = knowledge.data?.rule_types.find((item) => item.rule_id === row.rule_id);
  const notSourced = row.expected === "NOT SOURCED";
  const facts = row.evidence.filter((item) => item.origin === "extracted");
  const derived = row.evidence.filter((item) => item.origin === "derived");
  const policy = row.evidence.filter((item) => item.origin === "policy");

  return (
    <>
      <div className="crumbs">
        <Link to="/">Projects</Link> / <Link to={`/projects/${projectId}`}>project</Link> / finding
      </div>

      <div className="row">
        <Pill tone={row.outcome}>{row.outcome.toUpperCase()}</Pill>
        <h1 style={{ marginBottom: 0 }}>{humanise(row.rule_id)}</h1>
      </div>
      <p className="muted small">
        <span className="mono">
          {row.rule_id} v{row.rule_version}
        </span>{" "}
        · evaluated {formatWhen(row.evaluated_at)}
      </p>

      <h2>What was checked</h2>
      <div className="panel">
        <p style={{ marginTop: 0 }}>{rule?.description ?? "This rule publishes no description."}</p>
        <p style={{ marginBottom: 0 }}>{row.summary}</p>
      </div>

      <h2>What was compared</h2>
      <div className="compare">
        <div className="cell">
          <div className="k">Expected</div>
          <div className="v">{notSourced ? "not sourced" : row.expected}</div>
        </div>
        <div className="cell">
          <div className="k">Observed</div>
          <div className="v">{row.observed}</div>
        </div>
        {Object.entries(row.detail).map(([key, value]) => (
          <div className="cell" key={key}>
            <div className="k">{humanise(key)}</div>
            <div className="v">{value}</div>
          </div>
        ))}
      </div>

      {row.outcome === "inconclusive" ? (
        <div className="warnbox">
          <strong>Not a failure.</strong> The rule could not be applied — something it needed was
          missing, and{" "}
          {notSourced
            ? "no threshold was sourced from any document we hold"
            : "a value it needed was absent"}
          . Nothing about this document has been judged. The summary above says what was missing;
          supplying that document is what closes it.
        </div>
      ) : null}

      <h2>Evidence</h2>
      {row.evidence.length === 0 ? (
        <p className="muted">
          This finding cites nothing, which is only legitimate for an inconclusive result: there was
          no value to cite.
        </p>
      ) : null}

      {facts.length > 0 ? (
        <>
          <p className="small muted">Stated by a document — openable at the page.</p>
          {facts.map((item) => (
            <EvidenceCard
              key={`${item.role}-${item.fact_id}`}
              item={item}
              projectId={projectId}
              findingId={row.finding_id}
            />
          ))}
        </>
      ) : null}

      {derived.length > 0 ? (
        <>
          <p className="small muted">
            Computed. The arithmetic is shown so it can be redone by hand.
          </p>
          {derived.map((item) => (
            <EvidenceCard
              key={`${item.role}-${item.fact_id}`}
              item={item}
              projectId={projectId}
              findingId={row.finding_id}
            />
          ))}
        </>
      ) : null}

      {policy.length > 0 ? (
        <>
          <p className="small muted">
            The governing provision — a norm a reference document states about projects like this
            one, not a measurement of this one.
          </p>
          {policy.map((item) => (
            <EvidenceCard
              key={`${item.role}-${item.fact_id}`}
              item={item}
              projectId={projectId}
              findingId={row.finding_id}
            />
          ))}
        </>
      ) : null}

      <h2>Human review</h2>
      <div className="panel">
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="muted small">Current state:</span>
          {row.review_state === "unreviewed" ? (
            <Pill>unreviewed</Pill>
          ) : (
            <Pill tone={row.review_state}>{humanise(row.review_state)}</Pill>
          )}
        </div>
        <ReviewHistory reviews={row.reviews} />
      </div>
      <ReviewForm
        findingId={row.finding_id}
        knowledge={knowledge.data}
        onRecorded={finding.reload}
      />
    </>
  );
}
