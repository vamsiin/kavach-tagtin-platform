import { useState } from "react";
import type { Element } from "../types";
import { ELEMENT_TYPES } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";

interface Props {
  elements: Element[];
  onAdd: (payload: Partial<Element>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<Element>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  lockReason?: string;
}

const columns: ColumnDef<Element>[] = [
  { key: "element_ref", label: "Ref" },
  { key: "element_type", label: "Type" },
  { key: "location_m", label: "Location (m)" },
  { key: "direction", label: "Dir" },
  { key: "remarks", label: "Remarks" },
];

export function ElementsPanel({ elements, onAdd, onUpdate, onDelete, readOnly, lockReason }: Props) {
  return (
    <RegisterTable
      title="Elements"
      rows={elements}
      columns={columns}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onDelete={onDelete}
      readOnly={readOnly}
      readOnlyReason={readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing.") : undefined}
      renderForm={(submit, submitting) => <ElementForm onSubmit={submit} submitting={submitting} />}
      renderEditForm={(row, submit, cancel, submitting) => (
        <ElementForm initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
      )}
    />
  );
}

function ElementForm({ initial, onSubmit, onCancel, submitting }: {
  initial?: Element;
  onSubmit: (p: Partial<Element>) => void;
  onCancel?: () => void;
  submitting: boolean;
}) {
  const [ref, setRef] = useState(initial?.element_ref ?? "");
  const [type, setType] = useState<string>(initial?.element_type ?? ELEMENT_TYPES[0]);
  const [loc, setLoc] = useState(initial ? String(initial.location_m) : "");
  const [dir, setDir] = useState(initial?.direction ?? "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");

  return (
    <form className="inline-form" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        element_ref: ref, element_type: type, location_m: parseFloat(loc),
        direction: dir || null, remarks: remarks || null,
      });
    }}>
      <input placeholder="Ref (e.g. SIG-HS-01)" value={ref} onChange={(e) => setRef(e.target.value)} required />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {ELEMENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <input type="number" step="0.001" placeholder="Chainage (m)" title="Chainage in metres, e.g. 262910 for km 262.910" value={loc}
             onChange={(e) => setLoc(e.target.value)} required style={{ width: 130 }} />
      <select value={dir} onChange={(e) => setDir(e.target.value)}>
        <option value="">Dir —</option>
        <option value="UP">UP</option>
        <option value="Down">Down</option>
      </select>
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>
        {submitting ? "Saving…" : initial ? "Save" : "Add"}
      </button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
