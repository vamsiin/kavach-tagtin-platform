import { useEffect, useState } from "react";
import type { Station, Element, Tag, TIN, ObservationDraft, ObservationSummary, CheckResult } from "./types";
import { api } from "./api";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginScreen } from "./components/LoginScreen";
import { StationPanel } from "./components/StationPanel";
import { ElementsPanel } from "./components/ElementsPanel";
import { TagsPanel } from "./components/TagsPanel";
import { TinsPanel } from "./components/TinsPanel";
import { VerificationPanel } from "./components/VerificationPanel";
import { TocPanel } from "./components/TocPanel";
import { WorkflowPanel } from "./components/WorkflowPanel";
import { UsersPanel } from "./components/UsersPanel";
import { InputsPanel } from "./components/InputsPanel";
import { TraceabilityPanel } from "./components/TraceabilityPanel";
import { ObservationsPanel } from "./components/ObservationsPanel";
import { ReportsPanel } from "./components/ReportsPanel";
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
          <span>{user.full_name} <span className="muted">({user.role})</span></span>
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
  const [tab, setTab] = useState<"inputs" | "registers" | "verify" | "observations" | "trace" | "reports" | "workflow" | "users">("registers")
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
    api.listObservations(selected.id).then((r) => setObsSummary(r.summary)).catch(console.error);
  }, [selected]);

  const isReviewer = !!user && ["checker", "approver", "admin"].includes(user.role);
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

  function handleStationChanged(updated: Station) {
    setSelected(updated);
    setStations(stations.map((s) => (s.id === updated.id ? updated : s)));
  }

  function handleStationDeleted(id: number) {
    setStations(stations.filter((s) => s.id !== id));
    if (selected?.id === id) setSelected(null);
  }

  const readOnly = !!selected && selected.status !== "draft";

  return (
    <>
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
            {user?.role === "admin" && (
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
              <ElementsPanel elements={elements} readOnly={readOnly}
                onAdd={async (p) => { await api.addElement(selected.id, p); await reloadElements(); }}
                onUpdate={async (id, p) => { await api.updateElement(selected.id, id, p); await reloadElements(); }}
                onDelete={async (id) => { await api.deleteElement(selected.id, id); await reloadElements(); await reloadTags(); }} />
              <TagsPanel tags={tags} elements={elements} readOnly={readOnly}
                onAdd={async (p) => { await api.addTag(selected.id, p); await reloadTags(); }}
                onUpdate={async (id, p) => { await api.updateTag(selected.id, id, p); await reloadTags(); }}
                onDelete={async (id) => { await api.deleteTag(selected.id, id); await reloadTags(); }} />
              <TinsPanel tins={tins} readOnly={readOnly}
                onAdd={async (p) => { await api.addTin(selected.id, p); await reloadTins(); }}
                onUpdate={async (id, p) => { await api.updateTin(selected.id, id, p); await reloadTins(); }}
                onDelete={async (id) => { await api.deleteTin(selected.id, id); await reloadTins(); }} />
            </>
          )}

          {tab === "verify" && (
            <>
              <VerificationPanel stationId={selected.id}
                onRaiseObservation={isReviewer && selected.status !== "railway_submitted" ? raiseFromCheck : undefined} />
              <TocPanel stationId={selected.id} />
            </>
          )}

          {tab === "workflow" && (
            <WorkflowPanel station={selected} onStationChanged={handleStationChanged} />
          )}

          {tab === "users" && user?.role === "admin" && <UsersPanel />}
        </>
      )}

      {!selected && <p className="muted" style={{ padding: "2rem" }}>Select or create a station to begin.</p>}
    </>
  );
}
