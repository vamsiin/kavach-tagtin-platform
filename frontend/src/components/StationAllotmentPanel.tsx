import type { AllotmentUsage, StationAllotment } from "../types";

function Usage({ label, u }: { label: string; u: AllotmentUsage }) {
  return (
    <div className="allot-usage">
      <div><strong>{label}</strong>: {u.used_in_own} of {u.allotted} used · {u.free} free
        {" · next free "}<strong>odd {u.next_free_odd ?? "—"}</strong>, <strong>even {u.next_free_even ?? "—"}</strong></div>
      <div className="muted small">Free: {u.free_ranges || "none"}</div>
      {u.outside.length > 0 && (
        <div className="error small">Not in this station's or its adjacent sections' allotment:{" "}
          {u.outside.map((x) => `${x.ref} (${x.number})`).join(", ")}</div>
      )}
    </div>
  );
}

/** BR-001 / FR-004: this station's row on the current allotment chart, its adjacent
 *  sections' rows, and how much of the allotment is used. */
export function StationAllotmentPanel({ data }: { data: StationAllotment | null }) {
  if (!data) return null;
  if (!data.chart) {
    return (
      <div className="panel">
        <h3>Tag / TIN allotment</h3>
        <p className="muted small">No allotment chart loaded yet (Allotment tab). Numbers are only checked against 1-1023 / 1-255.</p>
      </div>
    );
  }
  return (
    <div className="panel">
      <h3>Tag / TIN allotment <span className="muted small">{data.chart.title}{data.chart.reference_no ? ` · ${data.chart.reference_no}` : ""}{data.chart.issued_on ? ` · ${data.chart.issued_on}` : ""}</span></h3>
      {!data.own ? (
        <div className="status-banner fail">This station's KAVACH ID isn't on the current chart, so none of its numbers can be accepted (BR-001).</div>
      ) : (
        <>
          <table className="register-table">
            <thead><tr><th></th><th>Chart row</th><th>Station ID</th><th>TIN range</th><th>Tag range</th></tr></thead>
            <tbody>
              <tr><td>This station</td><td><strong>{data.own.name}</strong></td><td>{data.own.station_id}</td>
                <td>{data.own.tin_ranges}</td><td>{data.own.tag_ranges}</td></tr>
              {data.adjacent.map((a) => (
                <tr key={a.adjacent_name}>
                  <td className="small">Adjacent: {a.adjacent_name}</td>
                  {a.row ? <><td>{a.row.name}</td><td>{a.row.station_id}</td><td>{a.row.tin_ranges}</td><td>{a.row.tag_ranges}</td></>
                    : <td colSpan={4} className="small"><span className="badge warn">not on the chart</span> record its KAVACH ID under Adjacent stations</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {data.tags && <Usage label="Tags" u={data.tags} />}
          {data.tins && <Usage label="TINs" u={data.tins} />}
          <p className="muted small">Numbers from an adjacent section's row are accepted too: the layout shows the block-section tags up to its borders.</p>
        </>
      )}
    </div>
  );
}
