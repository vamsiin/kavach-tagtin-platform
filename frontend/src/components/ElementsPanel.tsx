import { useState, type ReactNode } from "react";
import type { Element, Track } from "../types";
import { ELEMENT_TYPES, LC_CLASSES, LC_GATE, LC_MANNING, POINTS, defaultAspects, isSignalType } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";

interface Props {
  elements: Element[];
  tracks: Track[];
  dnDirection?: string;
  onAdd: (payload: Partial<Element>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<Element>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  lockReason?: string;
  headerExtra?: ReactNode;
}

export function lineName(tracks: Track[], id: number | null | undefined) {
  return id == null ? "—" : tracks.find((t) => t.id === id)?.name ?? "?";
}

export function LineSelect({ tracks, value, onChange, placeholder = "Line —" }: {
  tracks: Track[]; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} title="Line this sits on">
      <option value="">{placeholder}</option>
      {tracks.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
    </select>
  );
}

export function ElementsPanel({ elements, tracks, dnDirection, onAdd, onUpdate, onDelete, readOnly, lockReason, headerExtra }: Props) {
  const columns: ColumnDef<Element>[] = [
    { key: "element_ref", label: "Ref" },
    { key: "element_type", label: "Type" },
    { key: "location_m", label: "Location (m)" },
    { key: "track_id", label: "Line", render: (e) => lineName(tracks, e.track_id) },
    { key: "direction", label: "Dir", render: (e) => e.direction
        ? (/^(up|down|dn)$/i.test(e.direction) ? `${e.direction} (${/^up$/i.test(e.direction)
            ? ((dnDirection ?? "Nominal") === "Nominal" ? "Reverse" : "Nominal") : (dnDirection ?? "Nominal")})` : e.direction)
        : "—" },
    { key: "to_track_id", label: "Details", render: (e) =>
        e.element_type === POINTS ? (e.to_track_id != null ? `to ${lineName(tracks, e.to_track_id)}` : "to —")
            + (e.b_end_m != null ? ` · A-end ${e.location_m} / B-end ${e.b_end_m}` : " · B-end —")
        : e.element_type === LC_GATE ? [e.lc_class && `Class ${e.lc_class}`, e.lc_manning].filter(Boolean).join(", ") || "—"
        : isSignalType(e.element_type) ? (e.aspects ? `Aspects ${e.aspects}`
            : defaultAspects(e.element_type) ? `Aspects ${defaultAspects(e.element_type)} (default)` : "Aspects —")
        : "" },
    { key: "remarks", label: "Remarks" },
  ];
  return (
    <RegisterTable
      title="Elements"
      rows={elements}
      columns={columns}
      onAdd={onAdd}
      onUpdate={onUpdate}
      onDelete={onDelete}
      readOnly={readOnly}
      headerExtra={headerExtra}
      readOnlyReason={readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing.") : undefined}
      renderForm={(submit, submitting) => <ElementForm tracks={tracks} onSubmit={submit} submitting={submitting} />}
      renderEditForm={(row, submit, cancel, submitting) => (
        <ElementForm tracks={tracks} initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
      )}
    />
  );
}

function ElementForm({ tracks, initial, onSubmit, onCancel, submitting }: {
  tracks: Track[];
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
  const [track, setTrack] = useState(initial?.track_id != null ? String(initial.track_id) : "");
  const [toTrack, setToTrack] = useState(initial?.to_track_id != null ? String(initial.to_track_id) : "");
  const [lcClass, setLcClass] = useState(initial?.lc_class ?? "");
  const [lcManning, setLcManning] = useState(initial?.lc_manning ?? "");
  const [aspects, setAspects] = useState(initial?.aspects ?? "");
  const [side, setSide] = useState(initial?.signal_side ?? "");
  const [bEnd, setBEnd] = useState(initial?.b_end_m != null ? String(initial.b_end_m) : "");
  const [sidingName, setSidingName] = useState(initial?.siding_name ?? "");
  const [sidingShed, setSidingShed] = useState(initial?.siding_shed ?? "");
  const isBoard = type === "BSLB Board" || type === "Stop Board/Buffer Stop";
  const id = (v: string) => (v ? parseInt(v) : null);

  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        element_ref: ref, element_type: type, location_m: parseFloat(loc),
        direction: dir || null, remarks: remarks || null, track_id: id(track),
        to_track_id: type === POINTS ? id(toTrack) : null,
        lc_class: type === LC_GATE ? lcClass || null : null,
        lc_manning: type === LC_GATE ? lcManning || null : null,
        aspects: isSignalType(type) ? aspects.trim() || null : null,
        signal_side: isSignalType(type) || isBoard ? side || null : null,
        siding_name: type === POINTS && !toTrack && sidingName.trim() ? sidingName.trim() : null,
        siding_shed: type === POINTS && !toTrack && sidingShed.trim() ? sidingShed.trim() : null,
        b_end_m: type === POINTS && bEnd.trim() ? parseFloat(bEnd) : null,
      });
    }}>
      <input placeholder="Ref (e.g. SIG-HS-01)" value={ref} onChange={(e) => setRef(e.target.value)} required />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {ELEMENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <input type="number" step="0.001" placeholder={type === POINTS ? "A-end ABS (m)" : "Chainage (m)"}
             title={type === POINTS ? "Points: A-end absolute location (m), on the line the points are on" : "Chainage in metres, e.g. 262910 for km 262.910"} value={loc}
             onChange={(e) => setLoc(e.target.value)} required style={{ width: 130 }} />
      <LineSelect tracks={tracks} value={track} onChange={setTrack} />
      <select value={dir} onChange={(e) => setDir(e.target.value)}>
        <option value="">Dir —</option>
        <option value="UP">UP</option>
        <option value="Down">Down</option>
      </select>
      {type === POINTS && (
        <LineSelect tracks={tracks.filter((t) => String(t.id) !== track)} value={toTrack} onChange={setToTrack}
          placeholder="Leads to line —" />
      )}
      {type === POINTS && (
        <input type="number" step="0.001" placeholder="B-end ABS (m)" value={bEnd} onChange={(e) => setBEnd(e.target.value)}
               title="Points: B-end absolute location (m), where the turnout meets the line it leads to" style={{ width: 130 }} />
      )}
      {type === POINTS && !toTrack && (
        <>
          <input placeholder="Siding name (e.g. Siding for sub station & tower wagon)" value={sidingName}
                 onChange={(e) => setSidingName(e.target.value)} style={{ width: 300 }}
                 title="Points that lead to no recorded line lead to a siding outside KAVACH. Its name is written over the siding, which is drawn as the line carrying straight on to a buffer stop (BS)." />
          <input placeholder="Shed on it (e.g. Tower wagon shed)" value={sidingShed}
                 onChange={(e) => setSidingShed(e.target.value)} style={{ width: 220 }}
                 title="Optional: a shed standing on the siding, drawn as a long box named over it." />
        </>
      )}
      {type === LC_GATE && (
        <>
          <select value={lcClass} onChange={(e) => setLcClass(e.target.value)} title="LC gate class">
            <option value="">Class —</option>
            {LC_CLASSES.map((c) => <option key={c} value={c}>Class {c}</option>)}
          </select>
          <select value={lcManning} onChange={(e) => setLcManning(e.target.value)}>
            <option value="">Manning —</option>
            {LC_MANNING.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </>
      )}
      {isBoard && (
        <select value={side} onChange={(e) => setSide(e.target.value)}
                title="Which side of the line the board is drawn on. Leave on automatic to follow the Dir you set (set Dir to the direction of the Home signal this board serves) or, failing that, the line's direction. The BSLB box always stands behind its post.">
          <option value="">Drawn: by Home signal direction</option>
          <option value="Above">Drawn above the line</option>
          <option value="Below">Drawn below the line</option>
        </select>
      )}
      {type === "Sand Hump" && (
        <span className="muted small" title="A sand hump closes the end of a line">
          Chainage at the end of the line; drawn as a half disc with a bar, on the nearer end.
        </span>
      )}
      {isSignalType(type) && (
        <>
        <select value={side} onChange={(e) => setSide(e.target.value)}
                title="Which side of the line the signal is drawn on; automatic = Nominal above, Reverse below">
          <option value="">Drawn: automatic</option>
          <option value="Above">Drawn above the line</option>
          <option value="Below">Drawn below the line</option>
        </select>
        <input placeholder={`Aspects (default ${defaultAspects(type) ?? "—"})`} value={aspects}
               onChange={(e) => setAspects(e.target.value)} style={{ width: 170 }}
               title="Lamps from the SIP, e.g. R/Y/G or R/Y/YY/G+RI (R red, Y yellow, YY double yellow, G green, C calling-on, SH shunt, +RI route indicator). A calling-on signal is its C marker followed by its calling-on aspect(s), e.g. C/Y (the default: marker + a small yellow lens). Leave blank to use the default for the signal type." />
        </>
      )}
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>
        {submitting ? "Saving…" : initial ? "Save" : "Add"}
      </button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
