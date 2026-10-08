/** REQ-TAGTIN-DIR-001..006: a line / TIN section is entered as two endpoint
 *  chainages and an independent movement direction. Whatever order the endpoints are
 *  typed in, the section is saved with the LOWER chainage as From / Start and the
 *  HIGHER as To / End; changing the direction never swaps them. */

export const DIRECTION_OPTIONS = [
  { value: "Nominal", label: "Nominal — lower to higher chainage" },
  { value: "Reverse", label: "Reverse — higher to lower chainage" },
  { value: "Both", label: "Both directions" },
];

export const directionText = (d: string | null | undefined) =>
  d === "Nominal" ? "Nominal (lower → higher)" : d === "Reverse" ? "Reverse (higher → lower)"
    : d === "Both" ? "Both directions" : "—";

const kmText = (m: number) => (m / 1000).toFixed(3);

export function normaliseEndpoints(a: string, b: string): { lo?: number; hi?: number; swapped?: boolean; error?: string } {
  if (a.trim() === "" || b.trim() === "") return { error: "Enter both endpoint chainages" };
  const x = Number(a), y = Number(b);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return { error: "Chainages must be numbers" };
  if (x < 0 || y < 0) return { error: "Chainage cannot be negative" };
  if (x === y) return { error: "The two endpoints are equal — a section needs two different chainages" };
  return x < y ? { lo: x, hi: y, swapped: false } : { lo: y, hi: x, swapped: true };
}

export function movementText(lo: number, hi: number, dir: string | null | undefined): string {
  if (dir === "Nominal") return `${kmText(lo)} → ${kmText(hi)}`;
  if (dir === "Reverse") return `${kmText(hi)} → ${kmText(lo)}`;
  return dir === "Both" ? "both ways" : "direction not set";
}

interface Props {
  a: string; b: string; direction: string;
  onChange: (a: string, b: string, direction: string) => void;
  allowBlankDirection?: boolean;
}

export function SectionEndpoints({ a, b, direction, onChange, allowBlankDirection = true }: Props) {
  const n = normaliseEndpoints(a, b);
  return (
    <>
      <input type="number" step="0.001" min="0" placeholder="Endpoint A (m)" value={a} required style={{ width: 125 }}
        title="Chainage of one end of the section, in metres (either end)"
        onChange={(e) => onChange(e.target.value, b, direction)} />
      <input type="number" step="0.001" min="0" placeholder="Endpoint B (m)" value={b} required style={{ width: 125 }}
        title="Chainage of the other end, in metres"
        onChange={(e) => onChange(a, e.target.value, direction)} />
      <select value={direction} onChange={(e) => onChange(a, b, e.target.value)} title="Movement direction">
        {allowBlankDirection && <option value="">Direction —</option>}
        {DIRECTION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {(a.trim() !== "" || b.trim() !== "") && (
        n.error
          ? <span className="error small">{n.error}</span>
          : <span className="muted small">
              Saved as From / Start <strong>{n.lo}</strong> · To / End <strong>{n.hi}</strong>
              {" · "}movement {movementText(n.lo!, n.hi!, direction)}
              {n.swapped && " (endpoints put in lower → higher order)"}
            </span>
      )}
    </>
  );
}
