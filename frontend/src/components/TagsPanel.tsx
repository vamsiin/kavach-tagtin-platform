import { useState, type ReactNode } from "react";
import type { Tag, Element, Track } from "../types";
import { POINTS_TYPE, TAG_TYPES, TAG_TYPE_LABELS, directionLabel, isSuitableLink, LINK_HINTS } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";
import { LineSelect, lineName } from "./ElementsPanel";

interface Props {
  tags: Tag[];
  elements: Element[];
  tracks: Track[];
  nextFree?: { odd: number | null; even: number | null };
  dnDirection?: string;
  onAdd: (payload: Partial<Tag>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<Tag>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  lockReason?: string;
  headerExtra?: ReactNode;
}

const km = (m: number) => (m / 1000).toFixed(3);

/** The other tag(s) sharing this tag's pair / set ID. */
const partnersOf = (t: Tag, tags: Tag[]) =>
  t.pair_group_id ? tags.filter((x) => x.id !== t.id && x.pair_group_id === t.pair_group_id) : [];

function elementLabel(e: Element, tracks: Track[]): string {
  const line = e.track_id != null ? lineName(tracks, e.track_id) : "no line";
  const to = e.to_track_id != null ? ` → ${lineName(tracks, e.to_track_id)}` : "";
  return `${e.element_ref} · ${e.element_type} · ${line}${to} · km ${km(e.location_m)}`;
}

export function TagsPanel({ tags, elements, tracks, nextFree, dnDirection, onAdd, onUpdate, onDelete, readOnly, lockReason, headerExtra }: Props) {
  const columns: ColumnDef<Tag>[] = [
    { key: "tag_ref", label: "Tag ID" },
    { key: "tag_number", label: "No." },
    { key: "tag_type", label: "Type", render: (t) => `${t.tag_type} — ${TAG_TYPE_LABELS[t.tag_type]}` },
    { key: "location_m", label: "Chainage (m)",
      render: (t) => t.tag_type === "A" && t.abs2_m != null ? `${t.location_m} (ABS-2 ${t.abs2_m})` : String(t.location_m) },
    { key: "track_id", label: "Line", render: (t) => lineName(tracks, t.track_id) },
    { key: "direction", label: "Direction", render: (t) => t.direction ? directionLabel(t.direction, dnDirection) : "—" },
    { key: "linked_element_id", label: "Placed for",
      render: (t) => elements.find((e) => e.id === t.linked_element_id)?.element_ref ?? "—" },
    { key: "pair_group_id", label: "Paired with",
      render: (t) => {
        const p = partnersOf(t, tags);
        return p.length ? `${p.map((x) => x.tag_ref).join(", ")}${t.is_duplicate ? " (this is the duplicate)" : ""}` : "—";
      } },
    { key: "legend_shape", label: "Legend" },
    { key: "is_border_tag", label: "Border", render: (t) => t.is_border_tag ? "Yes" : "—" },
  ];

  /** Saving a pair also gives the partner the same pair ID (and the matching legend). */
  async function syncPartner(saved: Partial<Tag>, partnerId: number | null) {
    if (!partnerId || !saved.pair_group_id) return;
    const partner = tags.find((t) => t.id === partnerId);
    if (!partner) return;
    if (partner.pair_group_id === saved.pair_group_id && partner.legend_shape === saved.legend_shape
        && partner.is_duplicate === !saved.is_duplicate) return;
    const { id, ...rest } = partner;
    await onUpdate(id, { ...rest, pair_group_id: saved.pair_group_id, legend_shape: saved.legend_shape ?? partner.legend_shape,
      is_duplicate: !saved.is_duplicate });
  }

  // the form passes the chosen partner as _partner_id; it is stripped before saving
  type WithPartner = Partial<Tag> & { _partner_id?: number | null };
  const split = (p: WithPartner) => { const { _partner_id, ...rest } = p; return [rest, _partner_id ?? null] as const; };
  const addTag = async (p: WithPartner) => { const [t, pid] = split(p); await onAdd(t); await syncPartner(t, pid); };
  const updateTag = async (id: number, p: WithPartner) => { const [t, pid] = split(p); await onUpdate(id, t); await syncPartner(t, pid); };

  const form = (initial: Tag | undefined, submit: (p: Partial<Tag>) => void, submitting: boolean, cancel?: () => void) => (
    <TagForm elements={elements} tracks={tracks} tags={tags} nextFree={nextFree} dnDirection={dnDirection}
      initial={initial} onCancel={cancel} submitting={submitting}
      onSubmit={(payload, partnerId) => submit({ ...payload, _partner_id: partnerId } as WithPartner)} />
  );

  return (
    <RegisterTable
      title="Tags"
      rows={tags}
      columns={columns}
      onAdd={addTag}
      onUpdate={updateTag}
      onDelete={onDelete}
      readOnly={readOnly}
      headerExtra={headerExtra}
      readOnlyReason={readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing.") : undefined}
      renderForm={(submit, submitting) => form(undefined, submit, submitting)}
      renderEditForm={(row, submit, cancel, submitting) => form(row, submit, submitting, cancel)}
    />
  );
}

function Field({ label, help, children, wide }: { label: string; help?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <label style={wide ? { gridColumn: "1 / -1" } : undefined}>
      <span><strong>{label}</strong></span>
      {children}
      {help && <span className="muted small">{help}</span>}
    </label>
  );
}

function TagForm({ elements, tracks, tags, nextFree, dnDirection, initial, onSubmit, onCancel, submitting }: {
  dnDirection?: string;
  elements: Element[];
  tracks: Track[];
  tags: Tag[];
  nextFree?: { odd: number | null; even: number | null };
  initial?: Tag;
  onSubmit: (p: Partial<Tag>, partnerId: number | null) => void;
  onCancel?: () => void;
  submitting: boolean;
}) {
  const [ref, setRef] = useState(initial?.tag_ref ?? "");
  const [number, setNumber] = useState(initial?.tag_number != null ? String(initial.tag_number) : "");
  const [type, setType] = useState<string>(initial?.tag_type ?? TAG_TYPES[0]);
  const [loc, setLoc] = useState(initial ? String(initial.location_m) : "");
  const [abs2, setAbs2] = useState(initial?.abs2_m != null ? String(initial.abs2_m) : "");
  const [dir, setDir] = useState(initial?.direction ?? "");
  const [linkedEl, setLinkedEl] = useState<string>(initial?.linked_element_id ? String(initial.linked_element_id) : "");
  const initialPartner = initial ? partnersOf(initial, tags)[0] : undefined;
  const [partner, setPartner] = useState<string>(initialPartner ? String(initialPartner.id) : "");
  const [isDup, setIsDup] = useState(initial?.is_duplicate ?? false);
  const [legend, setLegend] = useState(initial?.legend_shape ?? "");
  const [exitSet, setExitSet] = useState(initial?.exit_set ?? "");
  const [exitComm, setExitComm] = useState(initial?.exit_comm ?? "");
  const [isBorderTag, setIsBorderTag] = useState(initial?.is_border_tag ?? false);
  const [track, setTrack] = useState(initial?.track_id != null ? String(initial.track_id) : "");

  const here = loc.trim() === "" ? null : Number(loc);
  const trackId = track ? Number(track) : null;
  const dist = (m: number) => (here == null ? Infinity : Math.abs(m - here));

  // Linked element: elements that suit this tag type first, nearest (and on the same line) first.
  const sortByNear = (a: Element, b: Element) =>
    Number(b.track_id === trackId) - Number(a.track_id === trackId) || dist(a.location_m) - dist(b.location_m);
  const suitable = elements.filter((e) => isSuitableLink(type, e.element_type)).sort(sortByNear);
  const others = elements.filter((e) => !isSuitableLink(type, e.element_type)).sort(sortByNear);
  const linked = elements.find((e) => String(e.id) === linkedEl);
  const noPoints = (type === "T" || type === "X") && !elements.some((e) => e.element_type === POINTS_TYPE);

  // Pair partner: other tags, nearest first.
  const candidates = tags.filter((t) => t.id !== initial?.id)
    .sort((a, b) => Number(b.track_id === trackId) - Number(a.track_id === trackId) || dist(a.location_m) - dist(b.location_m));
  const partnerTag = tags.find((t) => String(t.id) === partner);
  const gap = partnerTag && here != null ? Math.abs(partnerTag.location_m - here) : null;
  const autoLegend = gap == null ? "" : gap === 0 ? "Rectangle" : "Triangle";
  const coLocated = type === "T" || type === "A";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    let group: string | null = null;
    if (partnerTag) {
      group = partnerTag.pair_group_id
        || initial?.pair_group_id
        || `PAIR-${[partnerTag.tag_ref, ref].sort().join("/")}`;
    }
    onSubmit({
      tag_ref: ref, tag_number: number ? parseInt(number) : null,
      tag_type: type, location_m: parseFloat(loc), direction: dir || null,
      abs2_m: type === "A" && abs2.trim() !== "" ? parseFloat(abs2) : null,
      linked_element_id: linkedEl ? parseInt(linkedEl) : null,
      pair_group_id: group, is_duplicate: partnerTag ? isDup : false,
      legend_shape: partnerTag ? (legend || autoLegend || null) : (legend || null),
      exit_set: exitSet || null, exit_comm: type === "X" ? (exitComm || null) : null, is_border_tag: isBorderTag,
      track_id: track ? parseInt(track) : null,
    }, partnerTag ? partnerTag.id : null);
  }

  return (
    <form onSubmit={submit}>
      <div className="muted small" style={{ margin: "4px 0" }}><strong>1. Which tag</strong></div>
      <div className="form-grid">
        <Field label="Tag ID" help="As written on the drawing, e.g. R-775">
          <input value={ref} onChange={(e) => setRef(e.target.value)} required placeholder="R-775" />
        </Field>
        <Field label="Tag number" help={<>From the allotment chart (1-1023); odd = Nominal, even = Reverse.{nextFree && (
          <> Next free:{" "}
            {nextFree.odd != null && <button type="button" className="link-btn" onClick={() => setNumber(String(nextFree.odd))}>{nextFree.odd}</button>}
            {" / "}
            {nextFree.even != null && <button type="button" className="link-btn" onClick={() => setNumber(String(nextFree.even))}>{nextFree.even}</button>}
          </>)}</>}>
          <input type="number" value={number} onChange={(e) => setNumber(e.target.value)} min={1} max={1023} placeholder="775" />
        </Field>
        <Field label="Tag type" help={LINK_HINTS[type] ? `Placed for ${LINK_HINTS[type]}.` : undefined}>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TAG_TYPES.map((t) => <option key={t} value={t}>{t} — {TAG_TYPE_LABELS[t]}</option>)}
          </select>
        </Field>
      </div>

      <div className="muted small" style={{ margin: "4px 0" }}><strong>2. Where it is</strong></div>
      <div className="form-grid">
        <Field label="Line" help="The line the tag is fixed on">
          <LineSelect tracks={tracks} value={track} onChange={setTrack} placeholder="Pick a line…" />
        </Field>
        <Field label={type === "A" ? "ABS-1 — physical location (m)" : "Chainage (m)"} help={here != null && Number.isFinite(here) ? `km ${km(here)}` : "In metres, e.g. 262910 for km 262.910"}>
          <input type="number" step="0.001" value={loc} onChange={(e) => setLoc(e.target.value)} required placeholder="262910" />
        </Field>
        {type === "A" && (
          <Field label="ABS-2 — corrected location (m)" help={<>Adjustment tag: the chainage above is ABS-1, the physical
            location; ABS-2 is the corrected location the tag reports.{abs2 && Number.isFinite(Number(abs2)) ? ` km ${km(Number(abs2))}` : ""}</>}>
            <input type="number" step="0.001" value={abs2} onChange={(e) => setAbs2(e.target.value)} placeholder="261144" />
          </Field>
        )}
        <Field label="Direction of travel" help="The trains this tag is read by: Nominal = towards higher km, Reverse = towards lower km">
          <select value={dir} onChange={(e) => setDir(e.target.value)}>
            <option value="">Not set</option>
            <option value="Nominal">{directionLabel("Nominal", dnDirection)}</option>
            <option value="Reverse">{directionLabel("Reverse", dnDirection)}</option>
          </select>
        </Field>
      </div>

      <div className="muted small" style={{ margin: "4px 0" }}><strong>3. What it is placed for</strong></div>
      <div className="form-grid">
        <Field wide label={type === "T" ? "Points / turnout" : type === "S" ? "Signal or board" : type === "G" ? "LC gate"
          : type === "L" ? "Last stop signal" : "Linked element"}
          help={<>
            {LINK_HINTS[type] ? `Pick ${LINK_HINTS[type]}.` : "Optional."}
            {noPoints && " No points / turnouts are recorded yet — add them under Elements (type 'Points / Turnout', with the line they lead to) to link turnout tags."}
            {linked && !isSuitableLink(type, linked.element_type) && <span style={{ color: "#8a6116" }}> This element type does not usually go with a {type} tag.</span>}
          </>}>
          <select value={linkedEl} onChange={(e) => setLinkedEl(e.target.value)}>
            <option value="">None</option>
            {suitable.length > 0 && (
              <optgroup label={`Suitable for a ${type} tag (nearest first)`}>
                {suitable.map((el) => <option key={el.id} value={el.id}>{elementLabel(el, tracks)}{here != null ? ` · ${dist(el.location_m).toFixed(0)} m away` : ""}</option>)}
              </optgroup>
            )}
            {others.length > 0 && (
              <optgroup label="Other elements">
                {others.map((el) => <option key={el.id} value={el.id}>{elementLabel(el, tracks)}</option>)}
              </optgroup>
            )}
          </select>
        </Field>
      </div>

      <div className="muted small" style={{ margin: "4px 0" }}><strong>4. Main + duplicate pair (H2.12, H2.15)</strong> — only if this tag is installed as a pair with another tag</div>
      <div className="form-grid">
        <Field label="Paired with" help={coLocated ? "T and A tag pairs must be at the same chainage." : "Main and duplicate tag of the same set (normally 3-5 m apart)."}>
          <select value={partner} onChange={(e) => setPartner(e.target.value)}>
            <option value="">Not paired</option>
            {candidates.map((t) => <option key={t.id} value={t.id}>{t.tag_ref} ({t.tag_type}) · km {km(t.location_m)}{here != null ? ` · ${dist(t.location_m).toFixed(1)} m away` : ""}</option>)}
          </select>
        </Field>
        {partnerTag && (
          <Field label="This tag is the" help={gap != null ? `${gap.toFixed(1)} m from ${partnerTag.tag_ref}` : undefined}>
            <select value={isDup ? "dup" : "main"} onChange={(e) => setIsDup(e.target.value === "dup")}>
              <option value="main">Main tag ({partnerTag.tag_ref} is the duplicate)</option>
              <option value="dup">Duplicate ({partnerTag.tag_ref} is the main tag)</option>
            </select>
          </Field>
        )}
        <Field label="Legend shape on the drawing" help={partnerTag ? `Auto: ${autoLegend || "—"} (Rectangle when co-located, Triangle otherwise)` : "Only for paired tags"}>
          <select value={legend} onChange={(e) => setLegend(e.target.value)} disabled={!partnerTag && !legend}>
            <option value="">{partnerTag ? `Auto (${autoLegend || "—"})` : "—"}</option>
            <option value="Rectangle">Rectangle — main and duplicate co-located</option>
            <option value="Triangle">Triangle — duplicate ahead of the main tag</option>
          </select>
        </Field>
      </div>

      <div className="inline-form wrap" style={{ marginTop: 6 }}>
        {type === "X" && (
          <select value={exitSet} onChange={(e) => setExitSet(e.target.value)} title="Exit tags are placed in two sets">
            <option value="">Exit set —</option>
            <option value="1st">1st set</option>
            <option value="2nd">2nd set</option>
          </select>
        )}
        {type === "X" && (
          <select value={exitComm} onChange={(e) => setExitComm(e.target.value)}
                  title="1st exit tag: communication in the direction of entry only. 2nd exit tag: none either way.">
            <option value="">Programming —</option>
            <option value="ENTRY">Entry direction only (1st set)</option>
            <option value="NONE">No communication (2nd set)</option>
          </select>
        )}
        <label className="checkbox-label" title="Marks the boundary with the neighbouring station / block section (H2.16)">
          <input type="checkbox" checked={isBorderTag} onChange={(e) => setIsBorderTag(e.target.checked)} />
          Border tag (at the border with a neighbouring station)
        </label>
        <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add tag"}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
