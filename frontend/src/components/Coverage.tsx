/**
 * Document coverage across the construction chain.
 *
 * The most important thing on the overview, and the only screen element whose *absences* carry the
 * message. A project with a BOQ and an RA bill but nothing under Measurement cannot have
 * over-certification checked, and the reviewer needs to know that before they trust a clean result.
 *
 * Two things this must never say:
 *
 * - "missing" does not mean the project has no such document. It means **Aedifex does not hold
 *   one**, which is a statement about our corpus, not about the works.
 * - the order is the server's (`position`), not this file's. A viewer that sorts the chain itself
 *   eventually disagrees with the domain, and the order is load-bearing: measurement precedes the
 *   bill it justifies.
 */

import type { WorkflowCategoryInfo } from "../api";
import { humanise } from "../api";

export function Coverage({
  categories,
  present,
}: {
  categories: WorkflowCategoryInfo[];
  present: Record<string, number>;
}) {
  const chain = [...categories].sort((a, b) => a.position - b.position);
  return (
    <>
      <div className="chain">
        {chain.map((info) => {
          const held = present[info.category] ?? 0;
          return (
            <div
              key={info.category}
              className={`link ${held > 0 ? "present" : ""}`}
              title={held > 0 ? info.description : `Not held. ${info.verifies}`}
            >
              <div className="name">{humanise(info.category)}</div>
              <div className="mark">
                {held > 0 ? `✓ ${held} held` : "✗ not held"}
                {info.is_project_evidence ? "" : " · governs"}
              </div>
            </div>
          );
        })}
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>
        “Not held” means Aedifex has not been given a document of that kind — not that the project
        lacks one. Hover a link to see which check it enables.
      </p>
    </>
  );
}
