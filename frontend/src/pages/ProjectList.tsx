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
import { Link } from "react-router-dom";

import type { Knowledge, Project, ProjectSummary } from "../api";
import { getJson, humanise, useApi } from "../api";
import { ErrorBox, Loading, Pill } from "../components/bits";

interface Row {
  project: Project;
  summary: ProjectSummary | undefined;
}

export function ProjectList() {
  const projects = useApi<{ returned: number; projects: Project[] }>("/v1/projects");
  const knowledge = useApi<Knowledge>("/v1/knowledge");
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    const list = projects.data?.projects;
    if (!list) return;
    let live = true;
    setRows(list.map((project) => ({ project, summary: undefined })));
    void Promise.all(
      list.map(async (project) => {
        try {
          const summary = await getJson<ProjectSummary>(
            `/v1/projects/${project.project_id}/summary`,
          );
          return { project, summary };
        } catch {
          return { project, summary: undefined };
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

      {rows.map(({ project, summary }) => {
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

            <div className="row small" style={{ marginTop: 8 }}>
              <span>
                Documents <strong>{project.document_count}</strong>
              </span>
              <span>
                Findings <strong>{summary ? Object.values(summary.findings_by_outcome).reduce((a, b) => a + b, 0) : "—"}</strong>
              </span>
              <span>
                Needs review{" "}
                <strong>{summary ? summary.findings_awaiting_review : "—"}</strong>
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
