import { useState } from "react";
import type { TIN } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";

interface Props {
  tins: TIN[];
  onAdd: (payload: Partial<TIN>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<TIN>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  lockReason?: string;
}

const columns: ColumnDef<TIN>[] = [
  { key: "tin_no", label: "TIN No" },
  { key: "section_type", label: "Section" },
  { key: "color", label: "Color" },
  { key: "start_m", label: "Start (m)" },
  { key: "end_m", label: "End (m)" },
  { key: "is_non_kavach_territory", label: "Non-KAVACH", render: (t) => t.is_non_kavach_territory ? "Yes" : "No" },
];

export function TinsPanel({ tins, onAdd, onUpdate, onDelete, readOnly, lockReason }: Props) {
  return (
    <RegisterTable
      title="TINs"
      rows={tins}
      columns={columns}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onDelete={onDelete}
      readOnly={readOnly}
      readOnlyReason={readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing.") : undefined}
      renderForm={(submit, submitting) => <TinForm onSubmit={submit} submitting={submitting} />}
      renderEditForm={(row, submit, cancel, submitting) => (
        <TinForm initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
      )}
    />
  );
}

function TinForm({ initial, onSubmit, onCancel, submitting }: {
  initial?: TIN;
  onSubmit: (p: Partial<TIN>) => void;
  onCancel?: () => void;
  submitting: boolean;
}) {
  const [tinNo, setTinNo] = useState(initial ? String(initial.tin_no) : "");
  const [sectionType, setSectionType] = useState(initial?.section_type ?? "Station");
  const [color, setColor] = useState(initial?.color ?? "");
  const [startM, setStartM] = useState(initial ? String(initial.start_m) : "");
  const [endM, setEndM] = useState(initial ? String(initial.end_m) : "");
  const [nonKavach, setNonKavach] = useState(initial?.is_non_kavach_territory ?? false);

  return (
    <form className="inline-form" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        tin_no: parseInt(tinNo), section_type: sectionType, color: color || null,
        start_m: parseFloat(startM), end_m: parseFloat(endM),
        is_non_kavach_territory: nonKavach,
      });
    }}>
      <input type="number" placeholder="TIN No" value={tinNo} onChange={(e) => setTinNo(e.target.value)} required style={{ width: 90 }} />
      <select value={sectionType} onChange={(e) => setSectionType(e.target.value)}>
        <option value="Station">Station</option>
        <option value="Block">Block</option>
      </select>
      <input placeholder="Color" value={color} onChange={(e) => setColor(e.target.value)} style={{ width: 100 }} />
      <input type="number" step="0.001" placeholder="Start (m)" value={startM} onChange={(e) => setStartM(e.target.value)} required style={{ width: 110 }} />
      <input type="number" step="0.001" placeholder="End (m)" value={endM} onChange={(e) => setEndM(e.target.value)} required style={{ width: 110 }} />
      <label className="checkbox-label">
        <input type="checkbox" checked={nonKavach} onChange={(e) => setNonKavach(e.target.checked)} />
        Non-KAVACH territory
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? "Saving…" : initial ? "Save" : "Add"}
      </button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
