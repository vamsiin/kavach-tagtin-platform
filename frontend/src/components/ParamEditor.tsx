import type { ParamSchema } from "../types";
import { TAG_TYPE_LABELS } from "../types";

interface Props {
  schema: ParamSchema[];
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  disabled?: boolean;
}

/** Renders an editor for a checklist rule's parameters from its server-side schema. */
export function ParamEditor({ schema, value, onChange, disabled }: Props) {
  if (schema.length === 0) return <span className="muted small">No parameters.</span>;
  const set = (name: string, v: unknown) => onChange({ ...value, [name]: v });

  return (
    <div className="form-grid">
      {schema.map((s) => {
        const v = value[s.name];
        switch (s.type) {
          case "number":
          case "int":
            return (
              <label key={s.name}>{s.label}{s.required ? " *" : ""}
                <input type="number" step={s.type === "int" ? 1 : "any"} disabled={disabled}
                  value={v === null || v === undefined ? "" : String(v)}
                  onChange={(e) => set(s.name, e.target.value === "" ? (s.nullable ? null : "") : Number(e.target.value))} />
              </label>
            );
          case "bool":
            return (
              <label key={s.name} className="checkbox-label">
                <input type="checkbox" disabled={disabled} checked={v === undefined ? true : !!v}
                  onChange={(e) => set(s.name, e.target.checked)} /> {s.label}
              </label>
            );
          case "str":
            return (
              <label key={s.name}>{s.label}
                <input disabled={disabled} value={String(v ?? "")} onChange={(e) => set(s.name, e.target.value)} />
              </label>
            );
          case "choice":
            return (
              <label key={s.name}>{s.label}
                <select disabled={disabled} value={String(v ?? "")} onChange={(e) => set(s.name, e.target.value)}>
                  <option value="">— choose —</option>
                  {(s.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </label>
            );
          case "tag_types":
          case "element_types": {
            const sel = new Set((v as string[] | undefined) ?? []);
            return (
              <fieldset key={s.name} className="multi">
                <legend>{s.label}</legend>
                {s.type === "tag_types" ? (
                  (s.options ?? []).map((o) => (
                    <label key={o} className="checkbox-label">
                      <input type="checkbox" disabled={disabled} checked={sel.has(o)}
                        onChange={(e) => { const n = new Set(sel); if (e.target.checked) n.add(o); else n.delete(o); set(s.name, [...n]); }} />
                      {o} <span className="muted small">{TAG_TYPE_LABELS[o] ?? ""}</span>
                    </label>
                  ))
                ) : (
                  <select multiple disabled={disabled} size={5} value={[...sel]}
                    onChange={(e) => set(s.name, [...e.target.selectedOptions].map((o) => o.value))}>
                    {(s.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                )}
              </fieldset>
            );
          }
          case "parity_map": {
            const m = (v as Record<string, string> | undefined) ?? {};
            const entries = Object.entries(m);
            const write = (rows: [string, string][]) => set(s.name, Object.fromEntries(rows));
            return (
              <fieldset key={s.name} className="multi">
                <legend>{s.label}</legend>
                {entries.map(([dir, par], i) => (
                  <div key={i} className="inline-form">
                    <input disabled={disabled} value={dir} style={{ width: 120 }}
                      onChange={(e) => write(entries.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
                    <select disabled={disabled} value={par}
                      onChange={(e) => write(entries.map((x, j) => (j === i ? [x[0], e.target.value] : x)))}>
                      <option value="odd">odd</option>
                      <option value="even">even</option>
                    </select>
                    {!disabled && <button type="button" className="link-btn danger" onClick={() => write(entries.filter((_, j) => j !== i))}>remove</button>}
                  </div>
                ))}
                {!disabled && <button type="button" className="link-btn" onClick={() => write([...entries, ["", "odd"]])}>+ direction</button>}
              </fieldset>
            );
          }
          default:
            return null;
        }
      })}
    </div>
  );
}

export function paramSummary(schema: ParamSchema[], params: Record<string, unknown>): string {
  return schema.map((s) => {
    const v = params[s.name];
    if (v === null || v === undefined || (Array.isArray(v) && v.length === 0)) return null;
    if (s.type === "parity_map") return Object.entries(v as Record<string, string>).map(([k, x]) => `${k}=${x}`).join(", ");
    if (Array.isArray(v)) return `${s.label}: ${v.join(", ")}`;
    if (typeof v === "boolean") return v ? s.label : null;
    return `${s.label}: ${v}`;
  }).filter(Boolean).join(" · ");
}
