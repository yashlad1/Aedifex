/**
 * The API, typed. This file is the only place that knows a URL.
 *
 * Two rules hold everywhere in this app, and they are the reason it stays small:
 *
 * 1. **The backend owns truth.** Nothing here recomputes an outcome, re-derives a category, decides
 *    whether a finding needs review, or ranks anything. Those are deterministic decisions with
 *    provenance behind them, and a second implementation in TypeScript would be a second answer.
 * 2. **Vocabulary comes from the server.** Workflow categories, their order, processing statuses and
 *    review decisions are read from `/v1/knowledge` rather than hardcoded, so a category added in
 *    Python appears here without an edit.
 */

import { useCallback, useEffect, useState } from "react";

export type Outcome = "pass" | "fail" | "review" | "inconclusive";

export interface Project {
  project_id: string;
  source_id: string;
  external_ref: string | null;
  name: string | null;
  description: string | null;
  label: string;
  established_by: string;
  document_count: number;
  first_seen_at: string;
}

export interface ProjectDocument {
  document_id: string;
  filename: string | null;
  file_format: string;
  size_bytes: number;
  sha256: string;
  document_type: string;
  type_authority: string;
  workflow_category: string;
  role: string;
  suggested_type: string | null;
  classification_confidence: number | null;
  classifier: string | null;
  classification_disputed: boolean;
  status: string;
  origin: string;
  source_id: string | null;
  acquired_at: string | null;
  attached_at: string;
  attached_by: string;
  fact_count: number;
  finding_count: number;
  review_needed: number;
}

export interface ProjectSummary {
  project: Project;
  documents: number;
  documents_by_status: Record<string, number>;
  documents_by_category: Record<string, number>;
  facts: number;
  findings_by_outcome: Record<string, number>;
  reviews_by_decision: Record<string, number>;
  stale_reviews: number;
  findings_awaiting_review: number;
  documents_unclassified: number;
  classifications_disputed: number;
  summary: string;
}

/** One citation. `origin` is the field that matters: extracted, derived or policy. */
export interface Evidence {
  role: string;
  origin: "extracted" | "derived" | "policy";
  fact_id: string;
  fact_type: string;
  literal: string;
  page: number | null;
  snippet: string | null;
  value: string | null;
  expression: string | null;
  document_id: string | null;
  sheet_name: string | null;
  cell: string | null;
  clause: string | null;
  authority: string | null;
  band: string | null;
}

export interface Review {
  review_id: string;
  decision: string;
  note: string;
  reviewer: string;
  reviewed_outcome: string;
  reviewed_rule_version: string;
  reviewed_at: string;
  /**
   * Whether this review still speaks for the finding.
   *
   * The server compares a digest of the whole conclusion — verdict, both values, the rule's own
   * numbers and the citations — not just the outcome. So a re-read that changed the numbers while
   * leaving the verdict alone marks it stale, and `reviewed_outcome` / `reviewed_rule_version` are
   * what to *show* when explaining it.
   */
  stale: boolean;
}

export interface Finding {
  finding_id: string;
  /** `document`, `project` or `work_item`. Exactly one of the three ids below is set. */
  scope: "document" | "project" | "work_item";
  document_id: string | null;
  project_id: string | null;
  work_item_id: string | null;
  rule_id: string;
  rule_version: string;
  outcome: Outcome;
  summary: string;
  expected: string;
  observed: string;
  detail: Record<string, string>;
  evaluated_at: string;
  evidence: Evidence[];
  reviews: Review[];
  review_state: string;
  /**
   * Whether this finding is waiting on a person — decided by the backend, never here.
   *
   * This app used to compute it as `outcome !== "pass" && review_state === "unreviewed"`, which
   * listed every INCONCLUSIVE finding as review work. A reviewer cannot resolve one: the rule could
   * not be applied because the evidence it needed is missing, and the fix is acquiring a document,
   * not clicking Accept. `GET /v1/knowledge` publishes `requires_human_review` per outcome for
   * explaining the difference.
   */
  needs_human_review: boolean;
}

export interface Fact {
  fact_id: string;
  document_id: string;
  fact_type: string;
  literal: string;
  value: string | null;
  currency: string | null;
  page: number;
  snippet: string;
  method: string;
  extractor: string;
  extractor_version: string;
  extracted_at: string;
  retracted: boolean;
  retracted_reason: string | null;
  sheet_name: string | null;
  sheet_row: number | null;
  sheet_column: number | null;
  cell: string | null;
}

export interface WorkflowCategoryInfo {
  category: string;
  position: number;
  description: string;
  verifies: string;
  is_project_evidence: boolean;
}

export interface Knowledge {
  workflow_categories: WorkflowCategoryInfo[];
  processing_statuses: { status: string; description: string; needs_a_person: boolean }[];
  review_decisions: { decision: string; description: string; closes_the_finding: boolean }[];
  finding_outcomes: { outcome: string; description: string; requires_human_review: boolean }[];
  rule_types: { rule_id: string; scope: string; description: string; consumes: string[] }[];
}

export interface SheetWindowCell {
  column: number;
  letter: string;
  reference: string;
  value: string;
}

export interface SheetWindow {
  document_id: string;
  sheet: string;
  sheets: string[];
  first_row: number;
  total_rows: number;
  truncated: boolean;
  max_rows: number;
  max_columns: number;
  rows: { row: number; cells: SheetWindowCell[] }[];
  note: string;
}

/** What one upload did. The two booleans are the deduplication contract, made visible. */
export interface UploadResult {
  project_id: string;
  document: ProjectDocument;
  artifact_was_new: boolean;
  membership_was_new: boolean;
  suggested_type: string | null;
  suggestion_matched: string | null;
}

export interface Source {
  id: string;
  name: string;
  retrieval: string;
  is_collectable: boolean;
}

export interface ProcessingReport {
  project_id: string;
  processed: string[];
  already_processed: string[];
  unsupported: { document_id: string; reason: string }[];
  failed: { document_id: string; reason: string }[];
  facts: number;
  document_findings: number;
  project_findings: number;
  summary: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    // The API puts a sentence in `detail` and it is usually the whole explanation -- an unapproved
    // source, a format we refuse, a digest that no longer matches. Surfacing it beats "500".
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* a non-JSON error body is still an error; keep the status line */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: "POST", body: form });
}

export interface Query<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch on mount, refetch on demand. Deliberately not a cache library.
 *
 * There is no cross-screen cache to invalidate here: every screen asks for what it shows, and after
 * a write the affected screen calls `reload`. A stale number in a review workspace is worse than a
 * second request, because the whole product claim is that what you are looking at is what is stored.
 */
export function useApi<T>(path: string | null): Query<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(path !== null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError(undefined);
    getJson<T>(path)
      .then((result) => {
        if (live) setData(result);
      })
      .catch((cause: unknown) => {
        if (live) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, loading, reload };
}

/** Where the original artifact is served from. The thing every citation ultimately points at. */
export function contentUrl(documentId: string, page?: number | null): string {
  const base = `/v1/documents/${documentId}/content`;
  // A fragment, not a query parameter: `#page=` is understood by the browser's own PDF viewer, and
  // it is deliberately not sent to the server -- the bytes are the same whichever page you open.
  return page ? `${base}#page=${page}&view=FitH` : base;
}

/**
 * A window onto a spreadsheet, read by the same library that extracted the facts.
 *
 * Deliberately a server call rather than a parser in the browser: two parsers can disagree about
 * what cell F43 contains, and the one a reviewer sees must be the one the finding was computed from.
 */
export function sheetUrl(documentId: string, sheet: string | null, row: number): string {
  const params = new URLSearchParams({ row: String(row), radius: "12" });
  if (sheet) params.set("sheet", sheet);
  return `/v1/documents/${documentId}/sheet?${params.toString()}`;
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Turn `bill_of_quantities` into `Bill of quantities`. Presentation only; the value is unchanged. */
export function humanise(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
