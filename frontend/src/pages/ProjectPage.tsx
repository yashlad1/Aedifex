/**
 * Surfaces 2 and 3 — project overview and document inventory.
 *
 * The overview exists to orient a reviewer in one screen: what is held, what has been read, what is
 * waiting for them, and which links of the chain are missing. The inventory exists to make
 * *disagreement* visible — a classifier's proposal beside the authoritative type, never instead of
 * it, and never auto-resolved.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type {
  Finding,
  Knowledge,
  ProcessingReport,
  ProjectDocument,
  ProjectSummary,
  Source,
  UploadResult,
} from "../api";
import { formatBytes, humanise, postForm, postJson, useApi } from "../api";
import { CountRow, ErrorBox, Loading, Pill, Stat } from "../components/bits";
import { Coverage } from "../components/Coverage";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const summary = useApi<ProjectSummary>(`/v1/projects/${projectId}/summary`);
  const documents = useApi<{ returned: number; documents: ProjectDocument[] }>(
    `/v1/projects/${projectId}/documents`,
  );
  const projectFindings = useApi<{ returned: number; findings: Finding[] }>(
    `/v1/projects/${projectId}/findings`,
  );
  const knowledge = useApi<Knowledge>("/v1/knowledge");

  const [processing, setProcessing] = useState(false);
  const [report, setReport] = useState<ProcessingReport | undefined>();
  const [processError, setProcessError] = useState<string | undefined>();

  async function process() {
    setProcessing(true);
    setProcessError(undefined);
    try {
      setReport(await postJson<ProcessingReport>(`/v1/projects/${projectId}/process`, {}));
      summary.reload();
      documents.reload();
      projectFindings.reload();
    } catch (cause: unknown) {
      setProcessError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setProcessing(false);
    }
  }

  if (summary.loading) return <Loading what="the project" />;
  if (summary.error) return <ErrorBox error={summary.error} />;
  if (!summary.data) return null;

  const project = summary.data.project;
  const rows = documents.data?.documents ?? [];

  return (
    <>
      <div className="crumbs">
        <Link to="/">Projects</Link> / {project.label}
      </div>
      <h1>{project.name ?? project.label}</h1>
      <p className="muted small">
        {project.external_ref ? <span className="mono">{project.external_ref} · </span> : null}
        established by <span className="mono">{project.established_by}</span>
        {project.description ? <> · {project.description}</> : null}
      </p>

      <h2>Document coverage</h2>
      <div className="panel">
        <Coverage
          categories={knowledge.data?.workflow_categories ?? []}
          present={summary.data.documents_by_category}
        />
      </div>

      <h2>Where this project stands</h2>
      <div className="grid">
        <Stat label="Documents" value={summary.data.documents} />
        <Stat label="Facts extracted" value={summary.data.facts.toLocaleString()} />
        <Stat
          label="Findings awaiting review"
          value={summary.data.findings_awaiting_review}
          tone={summary.data.findings_awaiting_review > 0 ? "review" : undefined}
        />
        <Stat label="Disputed classifications" value={summary.data.classifications_disputed} />
      </div>
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="row small">
          <span className="muted">Processing:</span>
          <CountRow counts={summary.data.documents_by_status} />
        </div>
        <div className="row small" style={{ marginTop: 6 }}>
          <span className="muted">Findings:</span>
          <CountRow counts={summary.data.findings_by_outcome} />
        </div>
        <div className="row small" style={{ marginTop: 6 }}>
          <span className="muted">Current reviews:</span>
          <CountRow counts={summary.data.reviews_by_decision} />
          {summary.data.stale_reviews > 0 ? (
            <span className="muted">
              · {summary.data.stale_reviews} stale (kept, deciding nothing)
            </span>
          ) : null}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={process} disabled={processing}>
            {processing ? "Processing… (this blocks)" : "Process this project"}
          </button>
          <span className="small muted">
            Runs the extraction and rules pipeline. Synchronous: there is no background worker, so
            the request waits — about 17 seconds for seven real documents.
          </span>
        </div>
        {processError ? (
          <div style={{ marginTop: 8 }}>
            <ErrorBox error={processError} />
          </div>
        ) : null}
        {report ? (
          <div className="warnbox" style={{ marginTop: 8 }}>
            {report.summary}
            {report.unsupported.length > 0 ? (
              <div style={{ marginTop: 6 }}>
                Unsupported:{" "}
                {report.unsupported.map((item) => item.reason).join("; ")} — the bytes are still
                held and still listed.
              </div>
            ) : null}
            {report.failed.length > 0 ? (
              <div style={{ marginTop: 6 }}>
                Failed: {report.failed.map((item) => item.reason).join("; ")}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <h2>Documents</h2>
      <UploadPanel
        projectId={projectId}
        sourceId={project.source_id}
        onUploaded={() => {
          documents.reload();
          summary.reload();
        }}
      />
      {documents.error ? <ErrorBox error={documents.error} /> : null}
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Type (and who decided)</th>
            <th>Chain</th>
            <th>Status</th>
            <th>Origin</th>
            <th className="num">Facts</th>
            <th className="num">Findings</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.document_id}>
              <td>
                <Link to={`/projects/${projectId}/documents/${row.document_id}`}>
                  {row.filename ?? row.document_id}
                </Link>
                <div className="small muted">
                  {row.file_format.toUpperCase()} · {formatBytes(row.size_bytes)}
                </div>
              </td>
              <td>
                <div>{humanise(row.document_type)}</div>
                <div className="small muted">{humanise(row.type_authority)}</div>
                {row.classification_disputed ? (
                  <div className="small" style={{ marginTop: 4 }}>
                    <Pill tone="review">disputed</Pill>{" "}
                    classifier suggests <strong>{humanise(row.suggested_type ?? "")}</strong>
                    {row.classification_confidence !== null ? (
                      <span className="muted"> ({row.classification_confidence.toFixed(2)})</span>
                    ) : null}
                  </div>
                ) : null}
              </td>
              <td className="small">{humanise(row.workflow_category)}</td>
              <td>
                <Pill tone={row.status}>{humanise(row.status)}</Pill>
                {row.review_needed > 0 ? (
                  <div className="small muted">{row.review_needed} awaiting review</div>
                ) : null}
              </td>
              <td className="small">
                {row.origin}
                <div className="muted">{row.source_id}</div>
              </td>
              <td className="num">{row.fact_count.toLocaleString()}</td>
              <td className="num">{row.finding_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted" style={{ marginTop: 6 }}>
        A classifier suggestion is never applied. Open a document to confirm or change its type; only
        a person may do that.
      </p>

      <h2>Project findings</h2>
      <p className="small muted">
        Conclusions that belong to no single document — “these two documents disagree” is not a fact
        about either of them. Work-item reconciliation lives here too, so a project with many items
        has many findings; the ones needing a person are listed first.
      </p>
      <FindingList projectId={projectId} findings={projectFindings.data?.findings ?? []} />

      <h2>Document findings</h2>
      <DocumentFindings projectId={projectId} documents={rows} />
    </>
  );
}

/**
 * Giving a project a document, from the browser.
 *
 * The declared type is optional and stays optional: absent means absent, and a re-upload with no
 * declaration keeps whatever the document already says rather than downgrading it to `unknown`. The
 * classifier proposes a type either way, into its own field, where nothing acts on it.
 *
 * The source defaults to the project's own, which is the ordinary case, and can be changed because
 * membership legitimately spans sources — a contractor's claim and a published rate schedule do not
 * arrive the same way.
 */
function UploadPanel({
  projectId,
  sourceId,
  onUploaded,
}: {
  projectId: string;
  sourceId: string;
  onUploaded: () => void;
}) {
  const sources = useApi<{ sources: Source[] }>("/v1/sources?collectable_only=true");
  const knowledge = useApi<Knowledge>("/v1/knowledge");
  const [file, setFile] = useState<File | null>(null);
  const [declared, setDeclared] = useState("");
  const [uploadedBy, setUploadedBy] = useState("");
  const [source, setSource] = useState(sourceId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<string | undefined>();

  const uploadable = (sources.data?.sources ?? []).filter(
    (candidate) => candidate.retrieval === "manual_upload",
  );
  const types = knowledge.data?.workflow_categories === undefined ? [] : DOCUMENT_TYPES;

  async function submit() {
    if (file === null) return;
    setBusy(true);
    setError(undefined);
    setOutcome(undefined);
    const form = new FormData();
    form.set("file", file);
    form.set("source_id", source);
    form.set("uploaded_by", uploadedBy);
    if (declared !== "") form.set("document_type", declared);
    try {
      const body = await postForm<UploadResult>(`/v1/projects/${projectId}/documents`, form);
      setOutcome(
        `${body.document.filename ?? "document"}: ` +
          `${body.artifact_was_new ? "stored" : "already held"}, ` +
          `${body.membership_was_new ? "attached" : "already attached"}` +
          (body.suggested_type ? `; classifier suggests ${humanise(body.suggested_type)}` : ""),
      );
      setFile(null);
      onUploaded();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="row">
        <input
          type="file"
          style={{ maxWidth: 340 }}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <select
          value={declared}
          onChange={(event) => setDeclared(event.target.value)}
          style={{ maxWidth: 220 }}
          aria-label="Document type"
        >
          <option value="">Type: not stated</option>
          {types.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
        <select
          value={source}
          onChange={(event) => setSource(event.target.value)}
          style={{ maxWidth: 220 }}
          aria-label="Source"
        >
          {uploadable.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name}
            </option>
          ))}
        </select>
        <input
          type="text"
          style={{ maxWidth: 170 }}
          value={uploadedBy}
          placeholder="uploaded by"
          onChange={(event) => setUploadedBy(event.target.value)}
        />
        <button
          className="primary"
          disabled={busy || file === null || uploadedBy.trim() === ""}
          onClick={submit}
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
      <p className="small muted" style={{ marginBottom: 0 }}>
        Leaving the type unstated is fine and often right: a suggestion is recorded either way, and a
        person confirms it. Re-uploading the same bytes creates no second copy and no second
        membership. Processing is a separate step.
      </p>
      {outcome ? (
        <div className="warnbox small" style={{ marginTop: 8 }}>
          {outcome}
        </div>
      ) : null}
      {error ? (
        <div style={{ marginTop: 8 }}>
          <ErrorBox error={error} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * The types a person may declare at upload.
 *
 * Listed here rather than fetched because the API publishes no document-type vocabulary endpoint —
 * `/v1/knowledge` describes facts, rules, categories and outcomes, not document types. That is a gap
 * worth closing when something else needs it; a stale entry here fails loudly, because the API
 * validates the value and rejects anything it does not know.
 */
const DOCUMENT_TYPES = [
  "bill_of_quantities",
  "measurement_book",
  "running_bill",
  "payment_certificate",
  "invoice",
  "change_order",
  "contract",
  "tender_notice",
  "bid_document",
  "award_notice",
  "corrigendum",
  "purchase_order",
  "delivery_challan",
  "goods_receipt_note",
  "material_test_certificate",
  "inspection_report",
  "technical_specification",
  "schedule_of_rates",
  "model_agreement",
  "audit_report",
  "drawing",
  "bank_guarantee",
  "unknown",
];

const FINDINGS_SHOWN = 20;

/**
 * A list of findings, open ones first, capped.
 *
 * The ordering is presentation over two fields the API already provides — the outcome, and whether a
 * review speaks for it. Nothing here re-decides either. The cap exists because one real project
 * reconciles 37 work items against 4 rules, and 150 cards is not a list anybody reads.
 */
function FindingList({ projectId, findings }: { projectId: string; findings: Finding[] }) {
  const [all, setAll] = useState(false);
  if (findings.length === 0) return <p className="muted small">None.</p>;

  // `needs_human_review` comes from the backend. This file used to compute it as
  // `outcome !== "pass" && review_state === "unreviewed"`, which put every INCONCLUSIVE finding in
  // the review queue — work no reviewer can complete, because the rule could not be applied for want
  // of evidence. Severity ordering within "needs a person" is presentation; the decision is not.
  const rank = (finding: Finding) => {
    if (!finding.needs_human_review) return 3;
    return finding.outcome === "fail" ? 0 : 1;
  };
  const ordered = [...findings].sort((a, b) => rank(a) - rank(b));
  const shown = all ? ordered : ordered.slice(0, FINDINGS_SHOWN);

  return (
    <>
      {shown.map((finding) => (
        <FindingRow key={finding.finding_id} projectId={projectId} finding={finding} />
      ))}
      {ordered.length > shown.length ? (
        <button className="link" onClick={() => setAll(true)}>
          Show the remaining {ordered.length - shown.length} finding(s)
        </button>
      ) : null}
    </>
  );
}

/** A finding as it appears in a list: verdict, what it says, and whether anyone has looked. */
export function FindingRow({ projectId, finding }: { projectId: string; finding: Finding }) {
  return (
    <div className={`finding ${finding.outcome}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <Pill tone={finding.outcome}>{finding.outcome.toUpperCase()}</Pill>
          <span className="rule">
            {finding.rule_id} v{finding.rule_version}
          </span>
        </div>
        <div className="row">
          {finding.review_state === "unreviewed" ? (
            <span className="small muted">unreviewed</span>
          ) : (
            <Pill tone={finding.review_state}>{humanise(finding.review_state)}</Pill>
          )}
          <Link to={`/projects/${projectId}/findings/${finding.finding_id}`}>Open →</Link>
        </div>
      </div>
      <p style={{ margin: "7px 0 0" }}>{finding.summary}</p>
    </div>
  );
}

/**
 * Each document's own findings, fetched per document.
 *
 * One request per document rather than a project-wide endpoint that does not exist. Findings are
 * scoped to a document or to the project, and the API exposes exactly those two views; inventing a
 * third here would mean deciding which scope a finding "really" belongs to.
 */
function DocumentFindings({
  projectId,
  documents,
}: {
  projectId: string;
  documents: ProjectDocument[];
}) {
  return (
    <>
      {documents.map((document) => (
        <DocumentFindingGroup key={document.document_id} projectId={projectId} document={document} />
      ))}
    </>
  );
}

function DocumentFindingGroup({
  projectId,
  document,
}: {
  projectId: string;
  document: ProjectDocument;
}) {
  const findings = useApi<{ returned: number; findings: Finding[] }>(
    document.finding_count > 0 ? `/v1/documents/${document.document_id}/findings` : null,
  );
  if (document.finding_count === 0) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="small muted" style={{ marginBottom: 5 }}>
        {document.filename}
      </div>
      <FindingList projectId={projectId} findings={findings.data?.findings ?? []} />
    </div>
  );
}
