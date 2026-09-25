import { useEffect, useState } from "react";
import type { Station, Element, Tag, TIN, Track, AdjacentStation, ObservationDraft, ObservationSummary, CheckResult } from "./types";
import { api } from "./api";
import { AuthProvider, useAuth, useCan } from "./auth/AuthContext";
import { LoginScreen } from "./components/LoginScreen";
import { StationPanel } from "./components/StationPanel";
import { ElementsPanel } from "./components/ElementsPanel";
import { TagsPanel } from "./components/TagsPanel";
import { TinsPanel } from "./components/TinsPanel";
import { LinesPanel } from "./components/LinesPanel";
import { VerificationPanel } from "./components/VerificationPanel";
import { TocPanel } from "./components/TocPanel";
import { WorkflowPanel } from "./components/WorkflowPanel";
import { UsersPanel } from "./components/UsersPanel";
import { InputsPanel } from "./components/InputsPanel";
import { TraceabilityPanel } from "./components/TraceabilityPanel";
import { ObservationsPanel } from "./components/ObservationsPanel";
import { ReportsPanel } from "./components/ReportsPanel";
import { ChecklistPanel } from "./components/ChecklistPanel";
import { ManualChecklistPanel } from "./components/ManualChecklistPanel";
import { DashboardPanel } from "./components/DashboardPanel";
import { AssignmentPanel } from "./components/AssignmentPanel";
import { ConfigurationPanel } from "./components/ConfigurationPanel";
import "./styles.css";

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}

function Shell() {
  const { user, loading, logout } = useAuth();

  if (loading) return <div className="app"><p className="muted">Loading…</p></div>;
  if (!user) return <LoginScreen />;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>KAVACH RFID Tag/TIN Layout Platform</h1>
          <span className="muted">Design &amp; verification against RDSO/SPN/196/2020 Annexure-H</span>
        </div>
        <div className="user-badge">
          <span>{user.full_name} <span className="muted">({user.role_label ?? user.role})</span></span>
          <button onClick={logout} className="secondary">Log out</button>
        </div>
      </header>
      <MainContent />
    </div>
  );
}

function MainContent() {
  const { user } = useAuth();
  const [stations, setStations] = useState<Station[]>([]);
  const [selected, setSelected] = useState<Station | null>(null);
  const [elements, setElements] = useState<Element[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tins, setTins] = useState<TIN[]>([]);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [adjacent, setAdjacent] = useState<AdjacentStation[]>([]);
  const [tab, setTab] = useState<"inputs" | "registers" | "verify" | "observations" | "trace" | "reports" | "workflow" | "config" | "checklist" | "users">("registers")
  const [obsDraft, setObsDraft] = useState<ObservationDraft | null>(null);
  const [obsSummary, setObsSummary] = useState<ObservationSummary | null>(null);

  useEffect(() => {
    api.listStations().then(setStations).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.listElements(selected.id).then(setElements).catch(console.error);
    api.listTags(selected.id).then(setTags).catch(console.error);
    api.listTins(selected.id).then(setTins).catch(console.error);
    api.listTracks(selected.id).then(setTracks).catch(console.error);
    api.listAdjacent(selected.id).then(setAdjacent).catch(console.error);
    api.listObservations(selected.id).then((r) => setObsSummary(r.summary)).catch(console.error);
  }, [selected]);

  const can = useCan();
  const isReviewer = can("observations.raise");
  function raiseFromCheck(r: CheckResult) {
    const tag = tags.find((t) => t.tag_ref === r.subject_ref);
    const el = elements.find((e) => e.element_ref === r.subject_ref);
    setObsDraft({
      description: `${r.clause} ${r.title}: ${r.message}`,
      severity: r.status === "FAIL" ? "major" : "minor",
      category: r.clause.startsWith("H2") ? "annexure-h" : r.clause === "DATA-UNITS" ? "data" : "other",
      clause: r.clause,
      subject_kind: tag ? "tag" : el ? "element" : "station",
      subject_id: tag?.id ?? el?.id ?? null,
    });
    setTab("observations");
  }

  async function reloadElements() {
    if (selected) setElements(await api.listElements(selected.id));
  }
  async function reloadTags() {
    if (selected) setTags(await api.listTags(selected.id));
  }
  async function reloadTins() {
    if (selected) setTins(await api.listTins(selected.id));
  }
  async function reloadTracks() {
    // deleting a line unassigns everything on it, so the registers reload too
    if (!selected) return;
    setTracks(await api.listTracks(selected.id));
    await Promise.all([reloadElements(), reloadTags(), reloadTins()]);
  }

  function handleStationChanged(updated: Station) {
    setSelected(updated);
    setStations(stations.map((s) => (s.id === updated.id ? updated : s)));
  }

  function handleStationDeleted(id: number) {
    setStations(stations.filter((s) => s.id !== id));
    if (selected?.id === id) setSelected(null);
  }

  // Registers/inputs are editable only in Draft, only by roles with registers.edit, and --
  // when a Project Manager has assigned a designer -- only by that designer (or an admin).
  const lockedByAssignment = !!selected?.assigned_designer && user?.role !== "admin"
    && selected.assigned_designer !== user?.username;
  const readOnly = !!selected && (selected.status !== "draft" || !can("registers.edit") || lockedByAssignment);
  const lockReason = !selected ? undefined
    : selected.status !== "draft" ? "Registers are locked while this station is not in Draft. Use 'Request changes' to reopen for editing."
    : !can("registers.edit") ? `Read-only for your role (${user?.role_label ?? user?.role}). Only designers edit the registers.`
    : lockedByAssignment ? `This station is assigned to designer '${selected.assigned_designer}'. Only they (or an admin) can edit it.`
    : undefined;

  return (
    <>
      {selected && (
        <button className="link-btn back-link" onClick={() => setSelected(null)}>← Portfolio dashboard</button>
      )}
      <StationPanel
        stations={stations}
        selected={selected}
        onSelect={setSelected}
        onCreated={(s) => { setStations([...stations, s]); setSelected(s); }}
        onDeleted={handleStationDeleted}
      />

      {selected && (
        <>
          <nav className="tabs">
            <button className={tab === "inputs" ? "active" : ""} onClick={() => setTab("inputs")}>
              Inputs
            </button>
            <button className={tab === "registers" ? "active" : ""} onClick={() => setTab("registers")}>
              Registers
            </button>
            <button className={tab === "verify" ? "active" : ""} onClick={() => setTab("verify")}>
              Verification
            </button>
            <button className={tab === "observations" ? "active" : ""} onClick={() => setTab("observations")}>
              Observations{obsSummary && obsSummary.unresolved + obsSummary.unverified > 0
                ? <span className="tab-count">{obsSummary.unresolved + obsSummary.unverified}</span> : null}
            </button>
            <button className={tab === "trace" ? "active" : ""} onClick={() => setTab("trace")}>
              Traceability
            </button>
            <button className={tab === "reports" ? "active" : ""} onClick={() => setTab("reports")}>
              Reports
            </button>
            <button className={tab === "workflow" ? "active" : ""} onClick={() => setTab("workflow")}>
              Workflow
            </button>
            <button className={tab === "config" ? "active" : ""} onClick={() => setTab("config")}>
              Configuration
            </button>
            <button className={tab === "checklist" ? "active" : ""} onClick={() => setTab("checklist")}>
              Checklist
            </button>
            {can("users.manage") && (
              <button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>
                Users
              </button>
            )}
          </nav>

          {tab === "inputs" && (
            <InputsPanel stationId={selected.id} readOnly={readOnly} existingElements={elements}
              onRegistersChanged={async () => { await reloadElements(); await reloadTags(); }} />
          )}

          {tab === "trace" && <TraceabilityPanel stationId={selected.id} />}

          {tab === "reports" && <ReportsPanel stationId={selected.id} stationStatus={selected.status} />}

          {tab === "observations" && (
            <ObservationsPanel stationId={selected.id} stationStatus={selected.status}
              tags={tags} elements={elements} tins={tins}
              draft={obsDraft} onDraftConsumed={() => setObsDraft(null)} onSummary={setObsSummary} />
          )}

          {tab === "registers" && (
            <>
              <LinesPanel station={selected} tracks={tracks} adjacent={adjacent} readOnly={readOnly}
                lockReason={lockReason} onTracksChanged={reloadTracks}
                onAdjacentChanged={async () => setAdjacent(await api.listAdjacent(selected.id))}
                onStationChanged={handleStationChanged} />
              <ElementsPanel elements={elements} tracks={tracks} readOnly={readOnly} lockReason={lockReason}
                onAdd={async (p) => { await api.addElement(selected.id, p); await reloadElements(); }}
                onUpdate={async (id, p) => { await api.updateElement(selected.id, id, p); await reloadElements(); }}
                onDelete={async (id) => { await api.deleteElement(selected.id, id); await reloadElements(); await reloadTags(); }} />
              <TagsPanel tags={tags} elements={elements} tracks={tracks} readOnly={readOnly} lockReason={lockReason}
                onAdd={async (p) => { await api.addTag(selected.id, p); await reloadTags(); }}
                onUpdate={async (id, p) => { await api.updateTag(selected.id, id, p); await reloadTags(); }}
                onDelete={async (id) => { await api.deleteTag(selected.id, id); await reloadTags(); }} />
              <TinsPanel tins={tins} tracks={tracks} readOnly={readOnly} lockReason={lockReason}
                onAdd={async (p) => { await api.addTin(selected.id, p); await reloadTins(); }}
                onUpdate={async (id, p) => { await api.updateTin(selected.id, id, p); await reloadTins(); }}
                onDelete={async (id) => { await api.deleteTin(selected.id, id); await reloadTins(); }} />
            </>
          )}

          {tab === "verify" && (
            <>
              <VerificationPanel stationId={selected.id}
                onRaiseObservation={isReviewer && selected.status !== "railway_submitted" ? raiseFromCheck : undefined} />
              <ManualChecklistPanel stationId={selected.id} stationStatus={selected.status} />
              <TocPanel stationId={selected.id} />
            </>
          )}

          {tab === "workflow" && (
            <>
              <AssignmentPanel station={selected} assignedChecker={selected.assigned_checker}
                onStationChanged={handleStationChanged} />
              <WorkflowPanel station={selected} onStationChanged={handleStationChanged} />
            </>
          )}

          {tab === "checklist" && <ChecklistPanel />}

          {tab === "config" && <ConfigurationPanel station={selected} onStationChanged={handleStationChanged} />}

          {tab === "users" && can("users.manage") && <UsersPanel />}
        </>
      )}

      {!selected && (
        <DashboardPanel onOpen={(id) => { const s = stations.find((x) => x.id === id); if (s) setSelected(s); }} />
      )}
    </>
  );
}
