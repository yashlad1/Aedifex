/**
 * One citation, and the click that makes it checkable.
 *
 * The three origins are rendered differently on purpose, because conflating them is how a review
 * workspace starts lying:
 *
 * - **extracted** — a value a document states about itself. Has a page and a verbatim snippet, and
 *   is the only kind that can be opened at a page.
 * - **derived** — a value the calculation layer computed. Shows the arithmetic so it can be redone
 *   by hand, and shows no page, because nobody wrote it down.
 * - **policy** — a norm a *reference* document states about other projects. Shows its clause and the
 *   authority behind it. A threshold is not a measurement.
 */

import { Link } from "react-router-dom";

import type { Evidence } from "../api";
import { humanise } from "../api";
import { Pill } from "./bits";

const ORIGIN_LABEL: Record<Evidence["origin"], string> = {
  extracted: "stated by a document",
  derived: "computed",
  policy: "governing provision",
};

export function EvidenceCard({
  item,
  projectId,
  findingId,
}: {
  item: Evidence;
  projectId: string;
  findingId?: string;
}) {
  const openable = item.document_id !== null && item.origin !== "derived";
  // A cell is a location exactly as a page is. Both carry `fact` so the panel can highlight the row
  // that was cited, and `finding` so there is a way back.
  const target = openable
    ? `/projects/${projectId}/documents/${item.document_id}?` +
      new URLSearchParams({
        ...(item.page ? { page: String(item.page) } : {}),
        ...(item.sheet_name ? { sheet: item.sheet_name } : {}),
        ...(item.cell ? { cell: item.cell } : {}),
        fact: item.fact_id,
        ...(findingId ? { finding: findingId } : {}),
      }).toString()
    : null;
  const where = item.cell ?? (item.page ? `page ${item.page}` : null);

  return (
    <div className="evidence">
      <div className="head">
        <Pill>{ORIGIN_LABEL[item.origin]}</Pill>
        <strong>{humanise(item.fact_type)}</strong>
        <span className="muted small">cited as “{item.role}”</span>
      </div>

      <div className="value" style={{ marginTop: 4 }}>
        {item.value ?? item.literal}
        {/*
          Only an extracted fact has a phrase a document reads. A derived fact's `literal` is the
          calculation that produced it and a provision's is its clause, so quoting either as
          something a document says would be a small, confident lie.
        */}
        {item.origin === "extracted" && item.value && item.value !== item.literal ? (
          <span className="muted small"> — document reads “{item.literal}”</span>
        ) : null}
        {item.origin === "derived" ? (
          <span className="muted small"> — from {item.literal}</span>
        ) : null}
      </div>

      {item.origin === "policy" ? (
        <div className="small" style={{ marginTop: 4 }}>
          Clause <strong>{item.clause}</strong> · authority{" "}
          <strong>{item.authority ?? "unstated"}</strong>
          {item.band ? <> · applies {item.band}</> : null}
        </div>
      ) : null}

      {item.expression ? <div className="expr">{item.expression}</div> : null}
      {item.snippet ? <div className="snippet">“{item.snippet}”</div> : null}

      <div className="row small" style={{ marginTop: 7 }}>
        {target ? (
          <Link to={target}>Open {where ?? "the document"} →</Link>
        ) : (
          <span className="muted">
            {item.origin === "derived"
              ? "Computed from the facts above — no page to open"
              : "No document recorded"}
          </span>
        )}
      </div>
    </div>
  );
}
