import { useState } from "react";
import type { Tag, Element, Track } from "../types";
import { TAG_TYPES, TAG_TYPE_LABELS } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";
import { LineSelect, lineName } from "./ElementsPanel";

interface Props {
  tags: Tag[];
  elements: Element[];
  tracks: Track[];
  nextFree?: { odd: number | null; even: number | null };
  onAdd: (payload: Partial<Tag>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<Tag>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  lockReason?: string;
}

export function TagsPanel({ tags, elements, tracks, nextFree, onAdd, onUpdate, onDelete, readOnly, lockReason }: Props) {
  const columns: ColumnDef<Tag>[] = [
    { key: "tag_ref", label: "Ref" },
    { key: "tag_number", label: "No." },
    { key: "tag_type", label: "Type", render: (t) => `${t.tag_type} — ${TAG_TYPE_LABELS[t.tag_type]}` },
    { key: "location_m", label: "Location (m)" },
    { key: "track_id", label: "Line", render: (t) => lineName(tracks, t.track_id) },
    { key: "direction", label: "Dir" },
    { key: "linked_element_id", label: "Linked element",
      render: (t) => elements.find((e) => e.id === t.linked_element_id)?.element_ref ?? "—" },
    { key: "pair_group_id", label: "Pair group" },
    { key: "legend_shape", label: "Legend" },
    { key: "is_border_tag", label: "Border", render: (t) => t.is_border_tag ? "Yes" : "—" },
  ];

  return (
    <RegisterTable
      title="Tags"
      rows={tags}
      columns={columns}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onDelete={onDelete}
      readOnly={readOnly}
      readOnlyReason={readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing.") : undefined}
      renderForm={(submit, submitting) => (
        <TagForm elements={elements} tracks={tracks} nextFree={nextFree} onSubmit={submit} submitting={submitting} />
      )}
      renderEditForm={(row, submit, cancel, submitting) => (
        <TagForm elements={elements} tracks={tracks} nextFree={nextFree} initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
      )}
    />
  );
}

function TagForm({ elements, tracks, nextFree, initial, onSubmit, onCancel, submitting }: {
  elements: Element[];
  tracks: Track[];
  nextFree?: { odd: number | null; even: number | null };
  initial?: Tag;
  onSubmit: (p: Partial<Tag>) => void;
  onCancel?: () => void;
  submitting: boolean;
}) {
  const [ref, setRef] = useState(initial?.tag_ref ?? "");
  const [number, setNumber] = useState(initial?.tag_number != null ? String(initial.tag_number) : "");
  const [type, setType] = useState<string>(initial?.tag_type ?? TAG_TYPES[0]);
  const [loc, setLoc] = useState(initial ? String(initial.location_m) : "");
  const [dir, setDir] = useState(initial?.direction ?? "");
  const [linkedEl, setLinkedEl] = useState<string>(initial?.linked_element_id ? String(initial.linked_element_id) : "");
  const [pairGroup, setPairGroup] = useState(initial?.pair_group_id ?? "");
  const [legend, setLegend] = useState(initial?.legend_shape ?? "");
  const [exitSet, setExitSet] = useState(initial?.exit_set ?? "");
  const [isBorderTag, setIsBorderTag] = useState(initial?.is_border_tag ?? false);
  const [track, setTrack] = useState(initial?.track_id != null ? String(initial.track_id) : "");

  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        tag_ref: ref, tag_number: number ? parseInt(number) : null,
        tag_type: type, location_m: parseFloat(loc), direction: dir || null,
        linked_element_id: linkedEl ? parseInt(linkedEl) : null,
        pair_group_id: pairGroup || null, legend_shape: legend || null,
        exit_set: exitSet || null, is_border_tag: isBorderTag,
        track_id: track ? parseInt(track) : null,
      });
    }}>
      <input placeholder="Ref (e.g. R-775)" value={ref} onChange={(e) => setRef(e.target.value)} required />
      <input type="number" placeholder="Tag No. (1-1023)" value={number}
             onChange={(e) => setNumber(e.target.value)} style={{ width: 130 }} min={1} max={1023} />
      {nextFree && (
        <span className="muted small" title="Lowest unused numbers in this station's allotment (BR-001)">
          next free:{" "}
          {nextFree.odd != null && <button type="button" className="link-btn" onClick={() => setNumber(String(nextFree.odd))}>{nextFree.odd}</button>}
          {" / "}
          {nextFree.even != null && <button type="button" className="link-btn" onClick={() => setNumber(String(nextFree.even))}>{nextFree.even}</button>}
        </span>
      )}
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {TAG_TYPES.map((t) => <option key={t} value={t}>{t} — {TAG_TYPE_LABELS[t]}</option>)}
      </select>
      <input type="number" step="0.001" placeholder="Chainage (m)" title="Chainage in metres, e.g. 262910 for km 262.910" value={loc}
             onChange={(e) => setLoc(e.target.value)} required style={{ width: 130 }} />
      <LineSelect tracks={tracks} value={track} onChange={setTrack} />
      <select value={dir} onChange={(e) => setDir(e.target.value)}>
        <option value="">Dir —</option>
        <option value="Reverse">Reverse</option>
        <option value="Nominal">Nominal</option>
      </select>
      <select value={linkedEl} onChange={(e) => setLinkedEl(e.target.value)}>
        <option value="">Linked element —</option>
        {elements.map((el) => <option key={el.id} value={el.id}>{el.element_ref}</option>)}
      </select>
      <input placeholder="Pair group ID" value={pairGroup} onChange={(e) => setPairGroup(e.target.value)} style={{ width: 110 }} />
      <select value={legend} onChange={(e) => setLegend(e.target.value)}>
        <option value="">Legend —</option>
        <option value="Rectangle">Rectangle</option>
        <option value="Triangle">Triangle</option>
      </select>
      {type === "X" && (
        <select value={exitSet} onChange={(e) => setExitSet(e.target.value)}>
          <option value="">Exit set —</option>
          <option value="1st">1st</option>
          <option value="2nd">2nd</option>
        </select>
      )}
      <label className="checkbox-label">
        <input type="checkbox" checked={isBorderTag} onChange={(e) => setIsBorderTag(e.target.checked)} />
        Border tag
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? "Saving…" : initial ? "Save" : "Add"}
      </button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
