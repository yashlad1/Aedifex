/**
 * Surface 4 — the document viewer. The original artifact on the left, what we read from it on the
 * right.
 *
 * The left pane is an iframe over `/v1/documents/{id}/content`, which serves the stored bytes with
 * their digest re-verified. It is **not** a re-rendering: an HTML reconstruction of a document is our
 * interpretation of it, and interpreting the evidence is exactly what the reader is here to check.
 * Page navigation uses the `#page=` fragment that the browser's own PDF viewer understands, so
 * nothing here parses a PDF.
 *
 * Formats a browser will not render — a spreadsheet, a JSON API response — show their cell or row
 * reference and a download, because the honest answer is "here is where it says that, and here are
 * the bytes" rather than a table we drew ourselves.
 */

import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import type { Fact, Finding, Knowledge, ProjectDocument } from "../api";
import { contentUrl, formatBytes, humanise, postJson, useApi } from "../api";
import { ErrorBox, Loading, Pill } from "../components/bits";
import { FindingRow } from "./ProjectPage";

const INLINE_FORMATS = new Set(["pdf", "png", "jpeg"]);
const FACTS_SHOWN = 60;

export function DocumentPage() {
  const { projectId = "", documentId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const inventory = useApi<{ documents: ProjectDocument[] }>(
    `/v1/projects/${projectId}/documents`,
  );
  const facts = useApi<{ returned: number; facts: Fact[] }>(`/v1/documents/${documentId}/facts`);
  const findings = useApi<{ returned: number; findings: Finding[] }>(
    `/v1/documents/${documentId}/findings`,
  );
  const knowledge = useApi<Knowledge>("/v1/knowledge");
  const [filter, setFilter] = useState("");

  const page = Number(params.get("page") ?? "1") || 1;
  const highlighted = params.get("fact");
  const fromFinding = params.get("finding");

  const document = inventory.data?.documents.find((row) => row.document_id === documentId);
  const shown = useMemo(() => {
    const all = facts.data?.facts ?? [];
    const needle = filter.trim().toLowerCase();
    const matching = needle
      ? all.filter(
          (fact) =>
            fact.fact_type.toLowerCase().includes(needle) ||
            fact.literal.toLowerCase().includes(needle) ||
            fact.snippet.toLowerCase().includes(needle),
        )
      : all;
    // Whatever was clicked comes first, then the newest reading of each value, then whatever is
    // nearest the page on screen. The extractor-version ordering is presentation, not selection:
    // the API serves every version because older findings were computed from them, and the rules
    // decide which one governs. This only stops the newest sitting below the oldest.
    return [...matching].sort((a, b) => {
      if (a.fact_id === highlighted) return -1;
      if (b.fact_id === highlighted) return 1;
      const byVersion = b.extractor_version.localeCompare(a.extractor_version, undefined, {
        numeric: true,
      });
      if (byVersion !== 0) return byVersion;
      return Math.abs(a.page - page) - Math.abs(b.page - page);
    });
  }, [facts.data, filter, highlighted, page]);

  if (inventory.loading) return <Loading what="the document" />;
  if (inventory.error) return <ErrorBox error={inventory.error} />;
  if (!document) {
    return (
      <ErrorBox error="This document is not attached to this project. Open it from the project it belongs to." />
    );
  }

  const inline = INLINE_FORMATS.has(document.file_format);

  return (
    <>
      <div className="crumbs">
        <Link to="/">Projects</Link> / <Link to={`/projects/${projectId}`}>project</Link> /{" "}
        {document.filename}
        {fromFinding ? (
          <>
            {" — "}
            <Link to={`/projects/${projectId}/findings/${fromFinding}`}>
              back to the finding
            </Link>
          </>
        ) : null}
      </div>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1 style={{ marginBottom: 2 }}>{document.filename}</h1>
          <div className="small muted">
            {humanise(document.document_type)} ({humanise(document.type_authority)}) ·{" "}
            {document.file_format.toUpperCase()} · {formatBytes(document.size_bytes)} ·{" "}
            {document.origin} from <span className="mono">{document.source_id}</span>
          </div>
          <div className="small muted mono" title="Content identity">
            sha256 {document.sha256.slice(0, 24)}…
          </div>
        </div>
        <Pill tone={document.status}>{humanise(document.status)}</Pill>
      </div>

      {document.classification_disputed ? (
        <Classification
          projectId={projectId}
          document={document}
          knowledge={knowledge.data}
          onConfirmed={() => {
            inventory.reload();
          }}
        />
      ) : null}

      <div className="split" style={{ marginTop: 14 }}>
        <div className="viewer">
          <div className="bar">
            <strong className="small">Original artifact</strong>
            {inline ? (
              <>
                <button
                  onClick={() => {
                    params.set("page", String(Math.max(1, page - 1)));
                    setParams(params, { replace: true });
                  }}
                  disabled={page <= 1}
                >
                  ‹ prev
                </button>
                <span className="small mono">page {page}</span>
                <button
                  onClick={() => {
                    params.set("page", String(page + 1));
                    setParams(params, { replace: true });
                  }}
                >
                  next ›
                </button>
              </>
            ) : null}
            <a
              className="small"
              style={{ marginLeft: "auto" }}
              href={contentUrl(documentId)}
              target="_blank"
              rel="noreferrer"
            >
              open / download
            </a>
          </div>
          {inline ? (
            // `key` forces a reload when the page changes: a fragment change alone does not move an
            // already-loaded PDF viewer.
            <iframe
              key={`${documentId}-${page}`}
              title={document.filename ?? "artifact"}
              src={contentUrl(documentId, page)}
            />
          ) : (
            <div className="fallback">
              <p>
                <strong>{document.file_format.toUpperCase()}</strong> is not rendered in the browser.
                The evidence panel shows the cell or row each value came from, and the original bytes
                are one click away.
              </p>
              <p className="small">
                A spreadsheet view would mean re-rendering the document, and a re-rendering is our
                interpretation of the evidence rather than the evidence.
              </p>
            </div>
          )}
        </div>

        <div className="scroll">
          <h2 style={{ marginTop: 0 }}>Findings on this document</h2>
          {findings.data?.findings.length === 0 ? (
            <p className="muted small">None.</p>
          ) : (
            findings.data?.findings.map((finding) => (
              <FindingRow key={finding.finding_id} projectId={projectId} finding={finding} />
            ))
          )}

          <h2>Extracted values</h2>
          <div className="row small">
            <input
              type="text"
              value={filter}
              placeholder={`Filter ${facts.data?.returned ?? 0} values…`}
              onChange={(event) => setFilter(event.target.value)}
            />
          </div>
          <p className="small muted">
            A document can appear here twice for the same value: every extractor version is kept,
            because findings computed from an earlier reading have to stay explainable. The extractor
            and version are shown on each row, newest first, and the rules use the newest.
          </p>
          {facts.loading ? <Loading what="values" /> : null}
          {shown.slice(0, FACTS_SHOWN).map((fact) => (
            <div
              className="evidence"
              key={fact.fact_id}
              style={
                fact.fact_id === highlighted
                  ? { borderColor: "var(--accent)", background: "#eef3f8" }
                  : undefined
              }
            >
              <div className="head">
                <strong>{humanise(fact.fact_type)}</strong>
                {fact.retracted ? <Pill tone="fail">retracted</Pill> : null}
                <button
                  className="link small"
                  onClick={() => {
                    params.set("page", String(fact.page));
                    params.set("fact", fact.fact_id);
                    setParams(params, { replace: true });
                  }}
                >
                  page {fact.page} →
                </button>
              </div>
              <div className="value">{fact.value ?? fact.literal}</div>
              {fact.value && fact.value !== fact.literal ? (
                <div className="small muted">document reads “{fact.literal}”</div>
              ) : null}
              <div className="snippet">“{fact.snippet}”</div>
              <div className="small muted" style={{ marginTop: 4 }}>
                {fact.method} · {fact.extractor} v{fact.extractor_version}
              </div>
              {fact.retracted ? (
                <div className="warnbox small" style={{ marginTop: 6 }}>
                  Withdrawn: {fact.retracted_reason}. It is shown because findings computed from it
                  stay explainable, and it must not be read as something this document states.
                </div>
              ) : null}
            </div>
          ))}
          {shown.length > FACTS_SHOWN ? (
            <p className="small muted">
              Showing {FACTS_SHOWN} of {shown.length}. Filter to narrow — a priced bill states
              thousands of values, and a list is not how anyone reads one.
            </p>
          ) : null}
        </div>
      </div>
    </>
  );
}

/**
 * The classifier disagrees with what this document is filed as. A person resolves it, or nobody
 * does.
 *
 * Both options are offered plainly, including "keep what is declared", because confirming an
 * existing type is a real decision: it moves the authority from *declared at upload* to *a person
 * looked*.
 */
function Classification({
  document,
  knowledge,
  onConfirmed,
}: {
  projectId: string;
  document: ProjectDocument;
  knowledge: Knowledge | undefined;
  onConfirmed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [who, setWho] = useState("");

  async function confirm(documentType: string) {
    setBusy(true);
    setError(undefined);
    try {
      await postJson(`/v1/documents/${document.document_id}/classification`, {
        document_type: documentType,
        confirmed_by: who,
      });
      onConfirmed();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="warnbox" style={{ marginTop: 12 }}>
      <div className="row">
        <Pill tone="review">disputed classification</Pill>
        <span>
          Filed as <strong>{humanise(document.document_type)}</strong>; the classifier
          {knowledge ? "" : ""} suggests <strong>{humanise(document.suggested_type ?? "")}</strong>
          {document.classifier ? (
            <span className="muted small"> ({document.classifier})</span>
          ) : null}
          .
        </span>
      </div>
      <p className="small" style={{ marginBottom: 6 }}>
        Nothing has been changed. A suggestion never sets a document's type, because the type decides
        whether a quoted amount is treated as a fact about this document — and a filename cannot
        settle that.
      </p>
      <div className="row">
        <input
          type="text"
          style={{ maxWidth: 220 }}
          value={who}
          placeholder="your name, to attribute the decision"
          onChange={(event) => setWho(event.target.value)}
        />
        <button
          disabled={busy || who.trim() === ""}
          onClick={() => confirm(document.document_type)}
        >
          Confirm {humanise(document.document_type)}
        </button>
        <button
          disabled={busy || who.trim() === "" || !document.suggested_type}
          onClick={() => confirm(document.suggested_type ?? document.document_type)}
        >
          Change to {humanise(document.suggested_type ?? "")}
        </button>
      </div>
      {error ? (
        <div style={{ marginTop: 8 }}>
          <ErrorBox error={error} />
        </div>
      ) : null}
    </div>
  );
}
