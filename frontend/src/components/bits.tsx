/** Small shared pieces. Nothing here decides anything; they render what the API said. */

import type { ReactNode } from "react";

import { humanise } from "../api";

/** A short label. `tone` is the API's own value, so the class follows the vocabulary. */
export function Pill({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`pill ${tone ?? ""}`}>{children}</span>;
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <div className="n" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
      <div className="k">{label}</div>
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="muted">Loading {what}…</p>;
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="errbox">{error}</div>;
}

/**
 * Counts keyed by an API vocabulary term, rendered in a stable order.
 *
 * Zero-valued keys are *not* invented: if the API did not report an outcome, this shows nothing for
 * it. A displayed `FAIL 0` looks like a checked-and-clean result, when the truth may be that no rule
 * of that kind ran at all.
 */
export function CountRow({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return <span className="muted">none</span>;
  return (
    <span className="row">
      {entries.map(([key, value]) => (
        <span key={key}>
          <Pill tone={key}>{humanise(key)}</Pill> <strong>{value}</strong>
        </span>
      ))}
    </span>
  );
}
