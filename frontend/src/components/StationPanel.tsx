import { useState } from "react";
import { Trash2, Check, X } from "lucide-react";
import type { Station } from "../types";
import { STATUS_LABELS } from "../types";
import { api } from "../api";
import { useAuth, useCan } from "../auth/AuthContext";

interface Props {
  stations: Station[];
  selected: Station | null;
  onSelect: (s: Station) => void;
  onCreated: (s: Station) => void;
  onDeleted: (id: number) => void;
}

export function StationPanel({ stations, selected, onSelect, onCreated, onDeleted }: Props) {
  const { user } = useAuth();
  const can = useCan();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [kavachId, setKavachId] = useState("");
  const [sipDrawing, setSipDrawing] = useState("");
  const [kavachVer, setKavachVer] = useState("");
  const [sipVer, setSipVer] = useState("");
  const [guidelineVer, setGuidelineVer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const station = await api.createStation({
        name, kavach_station_id: kavachId, sip_drawing_number: sipDrawing || null,
        kavach_version: kavachVer || null, sip_version: sipVer || null,
        guideline_version: guidelineVer || null,
      });
      onCreated(station);
      setShowForm(false);
      setName(""); setKavachId(""); setSipDrawing("");
      setKavachVer(""); setSipVer(""); setGuidelineVer("");
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleDeleteConfirm(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    setDeleting(true);
    setError(null);
    try {
      await api.deleteStation(id);
      onDeleted(id);
      setPendingDeleteId(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="panel">
      <h2>Station</h2>
      <div className="station-list">
        {stations.map((s) => {
          const canDelete = user?.role === "admin" ||
            (user?.username === s.created_by && s.status === "draft");
          return (
          <div key={s.id} className={`station-chip-wrap ${selected?.id === s.id ? "active" : ""}`}>
            <button className="station-chip" onClick={() => onSelect(s)}>
              {s.name} <span className="muted">({s.kavach_station_id})</span>
            </button>
            {canDelete && (
              pendingDeleteId === s.id ? (
                <span className="confirm-delete">
                  <button className="icon-btn danger" title="Confirm delete"
                          onClick={(e) => handleDeleteConfirm(s.id, e)} disabled={deleting}>
                    <Check size={14} />
                  </button>
                  <button className="icon-btn" title="Cancel"
                          onClick={(e) => { e.stopPropagation(); setPendingDeleteId(null); }} disabled={deleting}>
                    <X size={14} />
                  </button>
                </span>
              ) : (
                <button className="icon-btn danger"
                        title={user?.role === "admin" ? "Delete station" : "Delete your draft station"}
                        onClick={(e) => { e.stopPropagation(); setPendingDeleteId(s.id); }}>
                  <Trash2 size={14} />
                </button>
              )
            )}
          </div>
          );
        })}
        {can("station.create") && (
          <button className="station-chip new" onClick={() => setShowForm(!showForm)}>
            + New station
          </button>
        )}
      </div>

      {selected && (
        <div className="station-meta">
          <span>Layout version: <strong>{selected.layout_version}</strong></span>
          <span>Status: <strong>{STATUS_LABELS[selected.status] ?? selected.status}</strong></span>
          <span>SIP: <strong>{selected.sip_drawing_number || "—"}</strong></span>
        </div>
      )}

      {showForm && (
        <form className="inline-form" onSubmit={handleCreate}>
          <input placeholder="Station name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="KAVACH station ID" value={kavachId} onChange={(e) => setKavachId(e.target.value)} required />
          <input placeholder="SIP drawing no." value={sipDrawing} onChange={(e) => setSipDrawing(e.target.value)} />
          <input placeholder="X (KAVACH ver.)" value={kavachVer} onChange={(e) => setKavachVer(e.target.value)} style={{ width: 90 }} />
          <input placeholder="Y (SIP ver.)" value={sipVer} onChange={(e) => setSipVer(e.target.value)} style={{ width: 90 }} />
          <input placeholder="Z (guideline ver.)" value={guidelineVer} onChange={(e) => setGuidelineVer(e.target.value)} style={{ width: 110 }} />
          <button type="submit">Create</button>
        </form>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
