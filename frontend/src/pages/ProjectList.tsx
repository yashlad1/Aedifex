/**
 * Surface 1 — the project list.
 *
 * Operational information only: how much is held, how much needs a person, and which links of the
 * chain are missing. No charts, no totals nobody acts on, and no ranking — a list that sorts
 * projects by "risk" is a score wearing a table's clothes.
 *
 * One summary request per project. That is N+1 and it is deliberate: N is the number of projects a
 * reviewer has, the summaries are the same read model the overview uses, and an aggregate endpoint
 * built for this screen would be a second definition of "needs review" to keep in step with the
 * first.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Knowledge, Project, ProjectSummary, Source } from "../api";
import { getJson, humanise, postJson, useApi } from "../api";
import { ErrorBox, Loading, Pill } from "../components/bits";

interface Row {
  project: Project;
  summary: ProjectSummary | undefined;
  /**
   * Why the summary is missing, when it is.
   *
   * Kept separate from `summary === undefined`, because "not loaded yet" and "the request failed"
   * are different facts and the second one has to be shown. A dash in place of a count reads as
   * "nothing to report", and failure to *retrieve* evidence is not absence of evidence.
   */
  failure: string | undefined;
}

export function ProjectList() {
  const projects = useApi<{ returned: number; projects: Project[] }>("/v1/projects");
  const knowledge = useApi<Knowledge>("/v1/knowledge");
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    const list = projects.data?.projects;
    if (!list) return;
    let live = true;
    setRows(list.map((project) => ({ project, summary: undefined, failure: undefined })));
    void Promise.all(
      list.map(async (project): Promise<Row> => {
        try {
          const summary = await getJson<ProjectSummary>(
            `/v1/projects/${project.project_id}/summary`,
          );
          return { project, summary, failure: undefined };
        } catch (cause: unknown) {
          return {
            project,
            summary: undefined,
            failure: cause instanceof Error ? cause.message : String(cause),
          };
        }
      }),
    ).then((resolved) => {
      if (live) setRows(resolved);
    });
    return () => {
      live = false;
    };
  }, [projects.data]);

  if (projects.loading) return <Loading what="projects" />;
  if (projects.error) return <ErrorBox error={projects.error} />;

  const evidenceCategories = (knowledge.data?.workflow_categories ?? [])
    .filter((info) => info.is_project_evidence && info.category !== "other")
    .sort((a, b) => a.position - b.position);

  return (
    <>
      <h1>Projects</h1>
      <p className="muted small">
        {projects.data?.returned ?? 0} project(s). “Needs review” counts findings that are not a pass
        and have no review speaking for the verdict as it now stands.
      </p>

      <CreateProject onCreated={projects.reload} />

      {rows.map(({ project, summary, failure }) => {
        const held = summary?.documents_by_category ?? {};
        const isHeld = (category: string) => (held[category] ?? 0) > 0;
        const missing = evidenceCategories.filter((info) => !isHeld(info.category));
        return (
          <div className="panel" key={project.project_id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ marginBottom: 0 }}>
                <Link to={`/projects/${project.project_id}`}>
                  {project.name ?? project.label}
                </Link>
              </h3>
              <span className="small muted mono">{project.established_by}</span>
            </div>
            {project.external_ref ? (
              <div className="small mono muted">{project.external_ref}</div>
            ) : null}

            {failure ? (
              <div className="errbox small" style={{ marginTop: 8 }}>
                Summary unavailable — {failure}. The project and its documents are unaffected; what
                failed is this read. Open the project for its own view.
              </div>
            ) : null}

            <div className="row small" style={{ marginTop: 8 }}>
              <span>
                Documents <strong>{project.document_count}</strong>
              </span>
              <span>
                Findings{" "}
                <strong>
                  {summary
                    ? Object.values(summary.findings_by_outcome).reduce((a, b) => a + b, 0)
                    : failure
                      ? "unavailable"
                      : "…"}
                </strong>
              </span>
              <span>
                Needs review{" "}
                <strong>
                  {summary ? summary.findings_awaiting_review : failure ? "unavailable" : "…"}
                </strong>
              </span>
              {summary && summary.findings_awaiting_review > 0 ? (
                <Pill tone="review">a person is needed</Pill>
              ) : null}
              {summary && summary.classifications_disputed > 0 ? (
                <Pill tone="review">
                  {summary.classifications_disputed} disputed classification(s)
                </Pill>
              ) : null}
            </div>

            {summary ? (
              <div className="row small" style={{ marginTop: 8 }}>
                <span className="muted">Processing:</span>
                {Object.entries(summary.documents_by_status).map(([status, count]) => (
                  <span key={status}>
                    <Pill tone={status}>{humanise(status)}</Pill> {count}
                  </span>
                ))}
              </div>
            ) : null}

            {summary && evidenceCategories.length > 0 ? (
              <div className="small" style={{ marginTop: 8 }}>
                <span className="muted">Held: </span>
                {evidenceCategories
                  .filter((info) => isHeld(info.category))
                  .map((info) => humanise(info.category))
                  .join(", ") || "nothing yet"}
                <br />
                <span className="muted">Not held: </span>
                {missing.length === 0 ? (
                  "nothing missing"
                ) : (
                  <span title="These checks cannot run yet">
                    {missing.map((info) => humanise(info.category)).join(", ")}
                  </span>
                )}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}


/**
 * Declaring a project — the first step of the workflow, and until now only possible with curl.
 *
 * Three fields, and the source needs explaining rather than hiding. It is **acquisition metadata**:
 * it namespaces the project's identifier, because a tender reference is unique only within the
 * authority that issued it. It is not ownership, it does not become tenancy, and it does not
 * restrict what may be attached — a real project holds an owner's bill, a contractor's claim and a
 * published rate schedule, from different sources. `customer_provided` is the honest default for a
 * customer's own project, so it is offered first.
 */
function CreateProject({ onCreated }: { onCreated: () => void }) {
  const sources = useApi<{ sources: Source[] }>("/v1/sources?collectable_only=true");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");
  const [createdBy, setCreatedBy] = useState("");
  const [source, setSource] = useState("customer_provided");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const navigate = useNavigate();

  const uploadable = (sources.data?.sources ?? [])
    .filter((candidate) => candidate.retrieval === "manual_upload")
    .sort((a, b) => (a.id === "customer_provided" ? -1 : b.id === "customer_provided" ? 1 : 0));

  if (!open) {
    return (
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="primary" onClick={() => setOpen(true)}>
          Create a project
        </button>
      </div>
    );
  }

  async function submit() {
    setBusy(true);
    setError(undefined);
    try {
      const project = await postJson<Project>("/v1/projects", {
        name,
        source_id: source,
        created_by: createdBy,
        external_identifier: reference.trim() === "" ? null : reference,
        description: description.trim() === "" ? null : description,
      });
      onCreated();
      navigate(`/projects/${project.project_id}`);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>New project</h3>
      <label htmlFor="project-name">Name</label>
      <input
        id="project-name"
        type="text"
        value={name}
        placeholder="Hostel 19"
        onChange={(event) => setName(event.target.value)}
      />

      <label htmlFor="project-ref">Identifier, if the documents state one (optional)</label>
      <input
        id="project-ref"
        type="text"
        value={reference}
        placeholder="IITB/Dean (IPS)/CACI/H-19/NIT/R1"
        onChange={(event) => setReference(event.target.value)}
      />
      <p className="small muted">
        Left empty it stays empty — nothing invents a reference. Supplying the one the documents use
        lets a declared project and the evidence converge on a single row.
      </p>

      <label htmlFor="project-description">Description (optional)</label>
      <input
        id="project-description"
        type="text"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />

      <label htmlFor="project-source">Acquisition source</label>
      <select
        id="project-source"
        value={source}
        onChange={(event) => setSource(event.target.value)}
      >
        {uploadable.map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {candidate.name}
          </option>
        ))}
      </select>
      <p className="small muted">
        Namespaces the identifier above, and records how documents arrive. Not ownership: membership
        may span sources, and each document keeps its own origin.
      </p>

      <label htmlFor="project-by">Created by</label>
      <input
        id="project-by"
        type="text"
        value={createdBy}
        placeholder="your name — this is provenance"
        onChange={(event) => setCreatedBy(event.target.value)}
      />

      <div className="row" style={{ marginTop: 10 }}>
        <button
          className="primary"
          disabled={busy || name.trim() === "" || createdBy.trim() === ""}
          onClick={submit}
        >
          {busy ? "Creating…" : "Create project"}
        </button>
        <button onClick={() => setOpen(false)} disabled={busy}>
          Cancel
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
