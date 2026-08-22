/**
 * A spreadsheet, read-only, with the cited cell highlighted.
 *
 * The counterpart of opening a PDF at a page — and the reason it exists is that the precedence rules
 * put spreadsheet cells *above* PDF text as evidence, while the viewer had them the other way round:
 * a page could be opened, a cell could only be downloaded and hunted through. That inverted the
 * product's own claim about its strongest evidence.
 *
 * Two things keep this inside the trust boundary rather than outside it:
 *
 * 1. **The grid comes from the server**, read by the same library and the same `data_only` setting
 *    the extractor used. A parser in the browser could disagree with the facts about what F43 says,
 *    and the reviewer would be looking at the disagreement without knowing.
 * 2. **The workbook remains authoritative and downloadable.** This is a view for locating evidence,
 *    and it says so on screen. Values are rendered as the text the library read — never
 *    re-formatted, because presenting our formatting as the document's content is the same mistake
 *    as re-rendering a PDF.
 */

import type { SheetWindow } from "../api";
import { contentUrl, sheetUrl, useApi } from "../api";
import { ErrorBox, Loading } from "./bits";

export function SheetView({
  documentId,
  sheet,
  row,
  highlight,
  onSheetChange,
  onRowChange,
}: {
  documentId: string;
  sheet: string | null;
  row: number;
  highlight: string | null;
  onSheetChange: (sheet: string) => void;
  onRowChange: (row: number) => void;
}) {
  const window = useApi<SheetWindow>(sheetUrl(documentId, sheet, row));

  if (window.loading) return <Loading what="the sheet" />;
  if (window.error) return <ErrorBox error={window.error} />;
  if (!window.data) return null;

  const grid = window.data;
  // Only columns that hold something in this window, so an empty sheet's 26 blank columns do not
  // push the values off screen. Never fewer than the highlighted cell's column.
  const used = new Set<number>();
  grid.rows.forEach((entry) =>
    entry.cells.forEach((cell) => {
      if (cell.value !== "" || cell.reference === highlight) used.add(cell.column);
    }),
  );
  const columns = [...used].sort((a, b) => a - b);

  return (
    <>
      <div className="bar">
        <select
          value={grid.sheet}
          onChange={(event) => onSheetChange(event.target.value)}
          style={{ maxWidth: 190 }}
          aria-label="Sheet"
        >
          {grid.sheets.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <button onClick={() => onRowChange(Math.max(1, row - 20))} disabled={grid.first_row <= 1}>
          ‹ up
        </button>
        <span className="small mono">
          rows {grid.first_row}–{grid.first_row + Math.max(0, grid.rows.length - 1)} of{" "}
          {grid.total_rows}
        </span>
        <button onClick={() => onRowChange(row + 20)}>down ›</button>
        <a
          className="small"
          style={{ marginLeft: "auto" }}
          href={contentUrl(documentId)}
          target="_blank"
          rel="noreferrer"
        >
          download the workbook
        </a>
      </div>

      <div className="sheet-scroll">
        <table className="sheet">
          <thead>
            <tr>
              <th className="rownum" />
              {columns.map((column) => (
                <th key={column}>
                  {grid.rows[0]?.cells.find((cell) => cell.column === column)?.letter ?? column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((entry) => (
              <tr key={entry.row} className={entry.row === row ? "target" : undefined}>
                <th className="rownum">{entry.row}</th>
                {columns.map((column) => {
                  const cell = entry.cells.find((candidate) => candidate.column === column);
                  const cited = cell !== undefined && cell.reference === highlight;
                  return (
                    <td
                      key={column}
                      className={cited ? "cited" : undefined}
                      title={cell?.reference}
                    >
                      {cell?.value ?? ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="small muted" style={{ padding: "6px 10px", margin: 0 }}>
        {grid.note}
        {grid.truncated ? " This sheet has rows outside this window." : ""}
      </p>
    </>
  );
}
