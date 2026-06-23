import type { TableData } from "@/lib/types";

export default function ResultsTable({ table }: { table: TableData }) {
  return (
    <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border)" }}>
      <table className="w-full text-[12px]" style={{ color: "var(--text)" }}>
        <thead style={{ background: "var(--bg3)" }}>
          <tr>
            {table.columns.map((c) => (
              <th key={c} className="text-left px-3 py-2 font-mono font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-1.5 font-mono">
                  {cell === null ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
