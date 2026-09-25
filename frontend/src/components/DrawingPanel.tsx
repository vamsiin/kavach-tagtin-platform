import { useEffect, useState } from "react";
import type { Station } from "../types";
import { api } from "../api";

/** The RFID Tag / TIN layout sheet generated from the registers (Annexure-H H2.24-H2.29):
 *  preview here, download as PDF (print / submission) or DXF (continue in AutoCAD). */
export function DrawingPanel({ station, version }: { station: Station; version: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  async function load() {
    setError(null);
    try {
      const svg = await api.drawingSvg(station.id);
      setUrl((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })); });
    } catch (e) { setError(String(e)); }
  }
  useEffect(() => { load(); }, [station.id, version]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function download(fmt: "pdf" | "dxf" | "svg") {
    setBusy(fmt); setError(null);
    try { await api.downloadDrawing(station.id, fmt); } catch (e) { setError(String(e)); } finally { setBusy(null); }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Layout drawing <span className="muted small">generated from the registers · layout {station.layout_version}</span></h3>
        <div className="inline-form">
          <button className="secondary" onClick={() => setZoom(Math.max(1, zoom - 0.5))} disabled={zoom <= 1}>−</button>
          <span className="small">{Math.round(zoom * 100)}%</span>
          <button className="secondary" onClick={() => setZoom(Math.min(4, zoom + 0.5))}>+</button>
          <button className="secondary" onClick={load}>Refresh</button>
          <button onClick={() => download("pdf")} disabled={!!busy}>{busy === "pdf" ? "Generating…" : "PDF"}</button>
          <button onClick={() => download("dxf")} disabled={!!busy}>{busy === "dxf" ? "Generating…" : "DXF (AutoCAD)"}</button>
          <button className="secondary" onClick={() => download("svg")} disabled={!!busy}>SVG</button>
        </div>
      </div>
      <p className="muted small">
        A3 sheet, not drawn to scale: features keep their true order and true distances are written on the sheet.
        Lines, TINs in their colours, tags with legend shapes and km, signals, LC gates, points, borders, the
        centre line, and the legend, allotment, revision, signature and title blocks. PDF and DXF downloads are logged.
      </p>
      {error && <div className="error">{error}</div>}
      <div style={{ overflow: "auto", border: "1px solid #ddd", background: "#fff", maxHeight: "75vh" }}>
        {url && <img src={url} alt="Layout drawing" style={{ width: `${zoom * 100}%`, display: "block" }} />}
      </div>
    </div>
  );
}
