import { useEffect, useMemo, useRef, useState } from "react";
import type { DocType, InputDocument, Element } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";
import { DxfReviewPanel } from "./DxfReviewPanel";

interface Props {
  stationId: number;
  readOnly: boolean;
  existingElements: Element[];
  onRegistersChanged: () => Promise<void>;
}

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** FR-001: SIP / Site Survey / RFID Allocation Chart / Adjacent Layout / ToC uploads,
 *  kept as immutable revisions. FR-002: DXF import entry point. */
export function InputsPanel({ stationId, readOnly, existingElements, onRegistersChanged }: Props) {
  const can = useCan();
  // readOnly already folds in status, role and designer assignment (see App.tsx)
  const canUpload = !readOnly && can("inputs.upload");

  const [types, setTypes] = useState<DocType[]>([]);
  const [docs, setDocs] = useState<InputDocument[]>([]);
  const [docType, setDocType] = useState("SIP");
  const [versionLabel, setVersionLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [dxfDocId, setDxfDocId] = useState<number | null>(null);
  const [dxfFile, setDxfFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dxfInput = useRef<HTMLInputElement>(null);

  async function reload() {
    setDocs(await api.listDocuments(stationId));
  }

  useEffect(() => {
    api.listDocTypes().then(setTypes).catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    setDxfDocId(null);
    setDxfFile(null);
    reload().catch((e) => setError(String(e)));
  }, [stationId]);

  const typeLabel = (code: string) => types.find((t) => t.code === code)?.label ?? code;
  const selectedType = types.find((t) => t.code === docType);
  const currentByType = useMemo(() => {
    const m: Record<string, InputDocument> = {};
    for (const d of docs) if (d.is_current) m[d.doc_type] = d;
    return m;
  }, [docs]);
  const visibleDocs = showHistory ? docs : docs.filter((d) => d.is_current);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadDocument(stationId, file, docType, versionLabel, notes);
      setVersionLabel("");
      setNotes("");
      await reload();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(d: InputDocument) {
    if (!confirm(`Delete ${typeLabel(d.doc_type)} rev ${d.revision} (${d.original_filename})?`)) return;
    setError(null);
    try {
      await api.deleteDocument(stationId, d.id);
      await reload();
    } catch (err) {
      setError(String(err));
    }
  }

  function handleDxfPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setDxfDocId(null);
    setDxfFile(file);
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <h3>Design Inputs</h3>
          <label className="checkbox-label">
            <input type="checkbox" checked={showHistory} onChange={(e) => setShowHistory(e.target.checked)} />
            Show superseded revisions
          </label>
        </div>
        <p className="muted small">
          Source documents this layout is derived from. Re-uploading a type creates a new revision; older
          revisions are kept because tags and past workflow submissions may trace to them.
        </p>

        <div className="input-checklist">
          {types.filter((t) => t.code !== "OTHER").map((t) => (
            <span key={t.code} className={`badge ${currentByType[t.code] ? "pass" : t.required ? "fail" : "na"}`}>
              {t.label}{currentByType[t.code] ? ` · rev ${currentByType[t.code].revision}` : t.required ? " · missing" : ""}
            </span>
          ))}
        </div>

        {canUpload && (
          <div className="inline-form wrap">
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              {types.map((t) => <option key={t.code} value={t.code}>{t.label}</option>)}
            </select>
            <input placeholder="Drawing rev label (e.g. SIP Rev-3)" value={versionLabel}
              onChange={(e) => setVersionLabel(e.target.value)} />
            <input placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <button onClick={() => fileInput.current?.click()} disabled={busy}>
              {busy ? "Uploading…" : "Upload file"}
            </button>
            <input ref={fileInput} type="file" style={{ display: "none" }}
              accept={selectedType?.extensions.join(",")} onChange={handleUpload} />
            <button className="secondary" onClick={() => dxfInput.current?.click()}>Import DXF…</button>
            <input ref={dxfInput} type="file" accept=".dxf" style={{ display: "none" }} onChange={handleDxfPicked} />
          </div>
        )}
        {readOnly && <p className="muted small">Inputs are read-only for you here: the station is not in Draft, your role cannot upload, or another designer is assigned.</p>}
        {error && <div className="error">{error}</div>}

        <table className="register-table">
          <thead>
            <tr><th>Type</th><th>Rev</th><th>Label</th><th>File</th><th>Size</th><th>Uploaded</th><th>SHA-256</th><th></th></tr>
          </thead>
          <tbody>
            {visibleDocs.map((d) => (
              <tr key={d.id} className={d.is_current ? "" : "row-superseded"}>
                <td>{typeLabel(d.doc_type)}</td>
                <td>{d.revision}{!d.is_current && <span className="muted small"> (superseded)</span>}</td>
                <td>{d.version_label ?? "—"}</td>
                <td>
                  <button className="link-btn" onClick={() => api.downloadDocument(stationId, d).catch((e) => setError(String(e)))}>
                    {d.original_filename}
                  </button>
                  {d.notes && <div className="muted small">{d.notes}</div>}
                </td>
                <td>{fmtSize(d.size_bytes)}</td>
                <td>{d.uploaded_by}<div className="muted small">{d.uploaded_at.slice(0, 16).replace("T", " ")}</div></td>
                <td><code title={d.sha256}>{d.sha256.slice(0, 10)}…</code></td>
                <td className="row-actions">
                  {d.original_filename.toLowerCase().endsWith(".dxf") && (
                    <button className="link-btn" onClick={() => { setDxfFile(null); setDxfDocId(d.id); }}>Review DXF</button>
                  )}
                  {canUpload && <button className="link-btn danger" onClick={() => handleDelete(d)}>Delete</button>}
                </td>
              </tr>
            ))}
            {visibleDocs.length === 0 && (
              <tr><td colSpan={8} className="muted">No design inputs uploaded yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {(dxfFile || dxfDocId !== null) && (
        <DxfReviewPanel
          stationId={stationId}
          file={dxfFile}
          documentId={dxfDocId}
          canCommit={canUpload}
          existingElements={existingElements}
          onClose={() => { setDxfFile(null); setDxfDocId(null); }}
          onImported={async (docId) => { setDxfFile(null); setDxfDocId(docId); await reload(); }}
          onCommitted={async () => { await onRegistersChanged(); }}
        />
      )}
    </>
  );
}
