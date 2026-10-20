import React, { useState, useEffect, useRef, useCallback } from "react";
import { ChevronLeft, Plus, Trash2, Flame, TrendingUp, X, Check, Minus, Dumbbell } from "lucide-react";

const STORAGE_KEY = "repmax-data-v1";
const MIN_W = 0;
const MAX_W = 200;
const STEP_W = 5;
const ITEM_H = 46;
const VISIBLE = 7;
const TRACK_H = ITEM_H * VISIBLE;
const PAD = (TRACK_H - ITEM_H) / 2;

const WEIGHTS = [];
for (let w = MIN_W; w <= MAX_W; w += STEP_W) WEIGHTS.push(w);

const ACCENTS = ["#E8A33D", "#6FCF97", "#7FB3E8", "#C792EA", "#E86A5D"];

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function formatDate(iso) {
  const d = new Date(iso);
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  if (isToday) return "Today";
  const yest = new Date(today);
  yest.setDate(yest.getDate() - 1);
  if (d.toDateString() === yest.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function lastLog(exercise) {
  if (!exercise.logs || exercise.logs.length === 0) return null;
  return exercise.logs[exercise.logs.length - 1];
}

function maxWeight(exercise) {
  if (!exercise.logs || exercise.logs.length === 0) return null;
  return Math.max(...exercise.logs.map((l) => l.weight));
}

export default function RepMax() {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [screen, setScreen] = useState("home");
  const [activeSectionId, setActiveSectionId] = useState(null);
  const [activeExerciseId, setActiveExerciseId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const saveTimer = useRef(null);

  // Replaced proprietary async storage with standard standard localStorage for iPhone Web/PWA
  useEffect(() => {
    try {
      const res = localStorage.getItem(STORAGE_KEY);
      if (res) {
        setData(JSON.parse(res));
      } else {
        setData({ sections: [] });
      }
    } catch (e) {
      console.error("Failed to load local storage:", e);
      setData({ sections: [] });
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!loaded || !data) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    
    // Debounce save operations to prevent rendering bottlenecks
    saveTimer.current = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      } catch (e) {
        console.error("Storage quota exceeded or unavailable:", e);
      }
    }, 250);
    
    return () => clearTimeout(saveTimer.current);
  }, [data, loaded]);

  const addSection = (name) => {
    if (!name.trim()) return;
    setData((d) => ({
      sections: [...d.sections, { id: uid(), name: name.trim(), exercises: [] }],
    }));
  };

  const deleteSection = (id) => {
    setData((d) => ({ sections: d.sections.filter((s) => s.id !== id) }));
    setConfirmDelete(null);
  };

  const addExercise = (sectionId, name) => {
    if (!name.trim()) return;
    setData((d) => ({
      sections: d.sections.map((s) =>
        s.id === sectionId
          ? { ...s, exercises: [...s.exercises, { id: uid(), name: name.trim(), logs: [] }] }
          : s
      ),
    }));
  };

  const deleteExercise = (sectionId, exerciseId) => {
    setData((d) => ({
      sections: d.sections.map((s) =>
        s.id === sectionId
          ? { ...s, exercises: s.exercises.filter((e) => e.id !== exerciseId) }
          : s
      ),
    }));
    setConfirmDelete(null);
  };

  const logSet = (sectionId, exerciseId, weight, reps) => {
    setData((d) => ({
      sections: d.sections.map((s) =>
        s.id === sectionId
          ? {
              ...s,
              exercises: s.exercises.map((e) =>
                e.id === exerciseId
                  ? {
                      ...e,
                      logs: [...e.logs, { id: uid(), date: new Date().toISOString(), weight, reps }],
                    }
                  : e
              ),
            }
          : s
      ),
    }));
  };

  if (!loaded || !data) {
    return (
      <div style={styles.appShell}>
        <GlobalStyle />
        <div style={{ ...styles.phone, alignItems: "center", justifyContent: "center", display: "flex" }}>
          <span style={{ color: "#9B98A3", fontFamily: "Inter, sans-serif", fontSize: 14 }}>Loading…</span>
        </div>
      </div>
    );
  }

  const activeSection = data.sections.find((s) => s.id === activeSectionId) || null;
  const activeExercise = activeSection
    ? activeSection.exercises.find((e) => e.id === activeExerciseId)
    : null;

  return (
    <div style={styles.appShell}>
      <GlobalStyle />
      <div style={styles.phone}>
        {screen === "home" && (
          <HomeScreen
            data={data}
            onOpenSection={(id) => {
              setActiveSectionId(id);
              setScreen("section");
            }}
            onAddSection={addSection}
            onDeleteSection={deleteSection}
            confirmDelete={confirmDelete}
            setConfirmDelete={setConfirmDelete}
          />
        )}
        {screen === "section" && activeSection && (
          <SectionScreen
            section={activeSection}
            onBack={() => {
              setScreen("home");
              setConfirmDelete(null);
            }}
            onOpenExercise={(id) => {
              setActiveExerciseId(id);
              setScreen("exercise");
            }}
            onAddExercise={(name) => addExercise(activeSection.id, name)}
            onDeleteExercise={(exId) => deleteExercise(activeSection.id, exId)}
            confirmDelete={confirmDelete}
            setConfirmDelete={setConfirmDelete}
          />
        )}
        {screen === "exercise" && activeSection && activeExercise && (
          <ExerciseScreen
            exercise={activeExercise}
            onBack={() => {
              setScreen("section");
            }}
            onLog={(weight, reps) => logSet(activeSection.id, activeExercise.id, weight, reps)}
          />
        )}
      </div>
    </div>
  );
}

function HomeScreen({ data, onOpenSection, onAddSection, onDeleteSection, confirmDelete, setConfirmDelete }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const totalExercises = data.sections.reduce((n, s) => n + s.exercises.length, 0);
  const totalPRs = data.sections.reduce(
    (n, s) =>
      n +
      s.exercises.filter((e) => e.logs.length > 0).length,
    0
  );
  const totalSets = data.sections.reduce(
    (n, s) => n + s.exercises.reduce((m, e) => m + e.logs.length, 0),
    0
  );

  return (
    <div style={styles.screen}>
      <div style={{ padding: "28px 20px 8px" }}>
        <div style={styles.wordmark}>REPMAX</div>
        <div style={styles.tagline}>Know your numbers before you touch the bar.</div>
      </div>

      <div style={styles.statRow}>
        <StatCard icon={<Dumbbell size={16} color="#E8A33D" />} label="Exercises" value={totalExercises} />
        <StatCard icon={<Flame size={16} color="#E86A5D" />} label="Sets logged" value={totalSets} />
        <StatCard icon={<TrendingUp size={16} color="#6FCF97" />} label="With history" value={totalPRs} />
      </div>

      <div style={styles.sectionHeaderRow}>
        <span style={styles.sectionHeaderLabel}>Training days</span>
      </div>

      <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 10 }}>
        {data.sections.length === 0 && !adding && (
          <div style={styles.emptyBlock}>
            <div style={styles.emptyTitle}>No training days yet</div>
            <div style={styles.emptyBody}>Add a day — like Push, Pull, or Legs — to start logging lifts.</div>
          </div>
        )}

        {data.sections.map((s, i) => {
          const accent = ACCENTS[i % ACCENTS.length];
          const exCount = s.exercises.length;
          const isConfirming = confirmDelete === s.id;
          return (
            <div key={s.id} style={{ ...styles.dayCard, borderColor: isConfirming ? "#E86A5D" : "#34323C" }}>
              <div style={{ ...styles.dayAccent, background: accent }} />
              <button style={styles.dayCardMain} onClick={() => onOpenSection(s.id)}>
                <div>
                  <div style={styles.dayName}>{s.name}</div>
                  <div style={styles.daySub}>
                    {exCount} {exCount === 1 ? "exercise" : "exercises"}
                  </div>
                </div>
                <ChevronLeft size={18} color="#9B98A3" style={{ transform: "rotate(180deg)" }} />
              </button>
              {isConfirming ? (
                <div style={styles.confirmRow}>
                  <button style={styles.confirmYes} onClick={() => onDeleteSection(s.id)}>
                    <Check size={14} /> Delete
                  </button>
                  <button style={styles.confirmNo} onClick={() => setConfirmDelete(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  style={styles.trashBtn}
                  onClick={() => setConfirmDelete(s.id)}
                  aria-label={`Delete ${s.name}`}
                >
                  <Trash2 size={15} color="#6B6875" />
                </button>
              )}
            </div>
          );
        })}

        {adding ? (
          <div style={styles.addRow}>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Push Day"
              style={styles.addInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onAddSection(name);
                  setName("");
                  setAdding(false);
                }
                if (e.key === "Escape") {
                  setAdding(false);
                  setName("");
                }
              }}
            />
            <button
              style={styles.addConfirm}
              onClick={() => {
                onAddSection(name);
                setName("");
                setAdding(false);
              }}
            >
              <Check size={16} />
            </button>
            <button
              style={styles.addCancel}
              onClick={() => {
                setAdding(false);
                setName("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <button style={styles.addDayBtn} onClick={() => setAdding(true)}>
            <Plus size={16} /> Add day
          </button>
        )}
      </div>
      <div style={{ height: 24 }} />
    </div>
  );
}

function StatCard({ icon, label, value }) {
  return (
    <div style={styles.statCard}>
      {icon}
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  );
}

function SectionScreen({ section, onBack, onOpenExercise, onAddExercise, onDeleteExercise, confirmDelete, setConfirmDelete }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  return (
    <div style={styles.screen}>
      <TopBar title={section.name} onBack={onBack} />
      <div style={{ padding: "4px 20px 0" }}>
        <div style={styles.sectionSubLabel}>
          {section.exercises.length} {section.exercises.length === 1 ? "exercise" : "exercises"}
        </div>
      </div>

      <div style={{ padding: "12px 20px 0", display: "flex", flexDirection: "column", gap: 10 }}>
        {section.exercises.length === 0 && !adding && (
          <div style={styles.emptyBlock}>
            <div style={styles.emptyTitle}>No exercises in {section.name} yet</div>
            <div style={styles.emptyBody}>Add the lifts you do on this day to start tracking weight.</div>
          </div>
        )}

        {section.exercises.map((ex) => {
          const last = lastLog(ex);
          const isConfirming = confirmDelete === ex.id;
          return (
            <div key={ex.id} style={{ ...styles.exRow, borderColor: isConfirming ? "#E86A5D" : "#34323C" }}>
              <button style={styles.exRowMain} onClick={() => onOpenExercise(ex.id)}>
                <div>
                  <div style={styles.exName}>{ex.name}</div>
                  <div style={styles.exSub}>
                    {last ? `Last: ${last.weight} lbs × ${last.reps}` : "No sets yet"}
                  </div>
                </div>
                <ChevronLeft size={17} color="#9B98A3" style={{ transform: "rotate(180deg)" }} />
              </button>
              {isConfirming ? (
                <div style={styles.confirmRow}>
                  <button style={styles.confirmYes} onClick={() => onDeleteExercise(ex.id)}>
                    <Check size={14} /> Delete
                  </button>
                  <button style={styles.confirmNo} onClick={() => setConfirmDelete(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button style={styles.trashBtn} onClick={() => setConfirmDelete(ex.id)} aria-label={`Delete ${ex.name}`}>
                  <Trash2 size={14} color="#6B6875" />
                </button>
              )}
            </div>
          );
        })}

        {adding ? (
          <div style={styles.addRow}>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Bench Press"
              style={styles.addInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onAddExercise(name);
                  setName("");
                  setAdding(false);
                }
                if (e.key === "Escape") {
                  setAdding(false);
                  setName("");
                }
              }}
            />
            <button
              style={styles.addConfirm}
              onClick={() => {
                onAddExercise(name);
                setName("");
                setAdding(false);
              }}
            >
              <Check size={16} />
            </button>
            <button
              style={styles.addCancel}
              onClick={() => {
                setAdding(false);
                setName("");
              }}
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <button style={styles.addDayBtn} onClick={() => setAdding(true)}>
            <Plus size={16} /> Add exercise
          </button>
        )}
      </div>
      <div style={{ height: 24 }} />
    </div>
  );
}

function ExerciseScreen({ exercise, onBack, onLog }) {
  const last = lastLog(exercise);
  const pr = maxWeight(exercise);
  const startWeight = last ? last.weight : 45;
  const startIndex = Math.round((clamp(startWeight, MIN_W, MAX_W) - MIN_W) / STEP_W);

  const [weight, setWeight] = useState(WEIGHTS[startIndex]);
  const [reps, setReps] = useState(last ? last.reps : 8);
  const [justLogged, setJustLogged] = useState(false);
  const trackRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (trackRef.current) {
      trackRef.current.scrollTop = startIndex * ITEM_H;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleScroll = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      if (!trackRef.current) return;
      const idx = clamp(Math.round(trackRef.current.scrollTop / ITEM_H), 0, WEIGHTS.length - 1);
      setWeight(WEIGHTS[idx]);
    });
  }, []);

  const scrollToIndex = (idx) => {
    const clamped = clamp(idx, 0, WEIGHTS.length - 1);
    if (trackRef.current) {
      trackRef.current.scrollTo({ top: clamped * ITEM_H, behavior: "smooth" });
    }
    setWeight(WEIGHTS[clamped]);
  };

  const bump = (deltaSteps) => {
    const currentIdx = WEIGHTS.indexOf(weight);
    scrollToIndex(currentIdx + deltaSteps);
  };

  const doLog = () => {
    onLog(weight, reps);
    setJustLogged(true);
    setTimeout(() => setJustLogged(false), 1400);
  };

  const isNewPR = pr === null || weight > pr;

  return (
    <div style={styles.screen}>
      <TopBar title={exercise.name} onBack={onBack} />

      <div style={{ padding: "8px 20px 0" }}>
        <div style={styles.refRow}>
          <div style={styles.refPill}>
            {last ? `Last time: ${last.weight} lbs × ${last.reps} · ${formatDate(last.date)}` : "No sets logged yet"}
          </div>
          {pr !== null && (
            <div style={styles.prPill}>
              <TrendingUp size={12} color="#6FCF97" /> Best: {pr} lbs
            </div>
          )}
        </div>
      </div>

      <div style={styles.bigWeightWrap}>
        <div style={styles.bigWeight}>
          {weight}
          <span style={styles.bigWeightUnit}>lbs</span>
        </div>
        {isNewPR && weight > 0 && <div style={styles.prBadge}>NEW PR</div>}
      </div>

      <div style={styles.rulerOuter}>
        <button style={styles.stepBtn} onClick={() => bump(1)} aria-label="Increase weight">
          <Plus size={18} color="#F5F3EF" />
        </button>

        <div style={{ ...styles.rulerViewport, height: TRACK_H }}>
          <div style={styles.centerLine} />
          <div
            ref={trackRef}
            onScroll={handleScroll}
            style={{ ...styles.rulerTrack, height: TRACK_H, paddingTop: PAD, paddingBottom: PAD }}
          >
            {WEIGHTS.map((w) => (
              <div key={w} style={{ ...styles.rulerItem, height: ITEM_H }}>
                <span style={{ ...styles.rulerTick, opacity: w === weight ? 1 : 0.35 }} />
                <span
                  style={{
                    ...styles.rulerLabel,
                    color: w === weight ? "#F5F3EF" : "#6B6875",
                    fontSize: w === weight ? 22 : 16,
                    fontWeight: w === weight ? 700 : 500,
                  }}
                >
                  {w}
                </span>
              </div>
            ))}
          </div>
        </div>

        <button style={styles.stepBtn} onClick={() => bump(-1)} aria-label="Decrease weight">
          <Minus size={18} color="#F5F3EF" />
        </button>
      </div>

      <div style={styles.repsRow}>
        <span style={styles.repsLabel}>Reps</span>
        <button style={styles.repsBtn} onClick={() => setReps((r) => Math.max(1, r - 1))}>
          <Minus size={14} color="#F5F3EF" />
        </button>
        <span style={styles.repsValue}>{reps}</span>
        <button style={styles.repsBtn} onClick={() => setReps((r) => Math.min(50, r + 1))}>
          <Plus size={14} color="#F5F3EF" />
        </button>
      </div>

      <div style={{ padding: "14px 20px 0" }}>
        <button style={styles.logBtn} onClick={doLog}>
          {justLogged ? (
            <>
              <Check size={17} /> Logged
            </>
          ) : (
            "Log set"
          )}
        </button>
      </div>

      <div style={{ padding: "18px 20px 24px" }}>
        {exercise.logs.length > 0 && <div style={styles.historyLabel}>History</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {[...exercise.logs]
            .slice()
            .reverse()
            .slice(0, 8)
            .map((log) => (
              <div key={log.id} style={styles.historyRow}>
                <span style={styles.historyWeight}>
                  {log.weight} lbs × {log.reps}
                </span>
                <span style={styles.historyRight}>
                  {pr !== null && log.weight === pr && <span style={styles.historyPR}>PR</span>}
                  <span style={styles.historyDate}>{formatDate(log.date)}</span>
                </span>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

function TopBar({ title, onBack }) {
  return (
    <div style={styles.topBar}>
      <button style={styles.backBtn} onClick={onBack} aria-label="Back">
        <ChevronLeft size={20} color="#F5F3EF" />
      </button>
      <div style={styles.topBarTitle}>{title}</div>
      <div style={{ width: 32 }} />
    </div>
  );
}

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

function GlobalStyle() {
  return (
    <style>{`
      @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap');
      * { box-sizing: border-box; }
      button { font-family: inherit; cursor: pointer; }
      input { font-family: inherit; }
      div[style*="overflow-y"]::-webkit-scrollbar { display: none; }
    `}</style>
  );
}

const styles = {
  appShell: {
    fontFamily: "'Inter', sans-serif",
    background: "#0E0D11",
    minHeight: "100vh",
    display: "flex",
    justifyContent: "center",
    padding: "0",
  },
  phone: {
    width: "100%",
    maxWidth: 430,
    minHeight: "100vh",
    background: "#16151A",
    position: "relative",
  },
  screen: {
    display: "flex",
    flexDirection: "column",
  },
  wordmark: {
    fontFamily: "'Oswald', sans-serif",
    fontSize: 30,
    fontWeight: 700,
    letterSpacing: 1,
    color: "#F5F3EF",
  },
  tagline: {
    fontSize: 13,
    color: "#8B8894",
    marginTop: 4,
  },
  statRow: {
    display: "flex",
    gap: 10,
    padding: "18px 20px 6px",
  },
  statCard: {
    flex: 1,
    background: "#1E1D24",
    border: "1px solid #2C2A33",
    borderRadius: 12,
    padding: "12px 10px",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  statValue: {
    fontFamily: "'Oswald', sans-serif",
    fontSize: 22,
    fontWeight: 600,
    color: "#F5F3EF",
  },
  statLabel: {
    fontSize: 11,
    color: "#8B8894",
  },
  sectionHeaderRow: {
    padding: "18px 20px 8px",
  },
  sectionHeaderLabel: {
    fontSize: 13,
    fontWeight: 600,
    color: "#9B98A3",
  },
  sectionSubLabel: {
    fontSize: 13,
    color: "#8B8894",
    marginTop: 2,
  },
  dayCard: {
    position: "relative",
    background: "#1E1D24",
    border: "1px solid #34323C",
    borderRadius: 14,
    overflow: "hidden",
    display: "flex",
    alignItems: "stretch",
  },
  dayAccent: {
    width: 5,
  },
  dayCardMain: {
    flex: 1,
    background: "transparent",
    border: "none",
    padding: "16px 14px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    textAlign: "left",
  },
  dayName: {
    fontSize: 16,
    fontWeight: 600,
    color: "#F5F3EF",
  },
  daySub: {
    fontSize: 12.5,
    color: "#8B8894",
    marginTop: 3,
  },
  trashBtn: {
    background: "transparent",
    border: "none",
    padding: "0 14px",
    display: "flex",
    alignItems: "center",
  },
  confirmRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "0 10px",
  },
  confirmYes: {
    background: "#E86A5D",
    border: "none",
    color: "#16151A",
    fontSize: 12.5,
    fontWeight: 600,
    borderRadius: 8,
    padding: "8px 10px",
    display: "flex",
    alignItems: "center",
    gap: 4,
  },
  confirmNo: {
    background: "transparent",
    border: "1px solid #34323C",
    color: "#9B98A3",
    fontSize: 12.5,
    borderRadius: 8,
    padding: "8px 10px",
  },
  emptyBlock: {
    border: "1px dashed #34323C",
    borderRadius: 14,
    padding: "22px 16px",
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: "#F5F3EF",
    marginBottom: 4,
  },
  emptyBody: {
    fontSize: 13,
    color: "#8B8894",
    lineHeight: 1.5,
  },
  addRow: {
    display: "flex",
    gap: 8,
    alignItems: "center",
  },
  addInput: {
    flex: 1,
    background: "#1E1D24",
    border: "1px solid #E8A33D",
    borderRadius: 10,
    padding: "12px 12px",
    color: "#F5F3EF",
    fontSize: 14,
    outline: "none",
  },
  addConfirm: {
    background: "#E8A33D",
    border: "none",
    borderRadius: 10,
    width: 40,
    height: 40,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#16151A",
  },
  addCancel: {
    background: "transparent",
    border: "1px solid #34323C",
    borderRadius: 10,
    width: 40,
    height: 40,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#9B98A3",
  },
  addDayBtn: {
    background: "transparent",
    border: "1px dashed #454250",
    borderRadius: 12,
    padding: "13px",
    color: "#C9C6D1",
    fontSize: 14,
    fontWeight: 500,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  topBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "20px 12px 6px",
  },
  backBtn: {
    background: "transparent",
    border: "none",
    width: 32,
    height: 32,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  topBarTitle: {
    fontFamily: "'Oswald', sans-serif",
    fontSize: 18,
    fontWeight: 600,
    color: "#F5F3EF",
    letterSpacing: 0.3,
  },
  exRow: {
    position: "relative",
    background: "#1E1D24",
    border: "1px solid #34323C",
    borderRadius: 12,
    display: "flex",
    alignItems: "stretch",
  },
  exRowMain: {
    flex: 1,
    background: "transparent",
    border: "none",
    padding: "14px 14px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    textAlign: "left",
  },
  exName: {
    fontSize: 15,
    fontWeight: 600,
    color: "#F5F3EF",
  },
  exSub: {
    fontSize: 12.5,
    color: "#8B8894",
    marginTop: 3,
  },
  refRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  refPill: {
    background: "#1E1D24",
    border: "1px solid #34323C",
    borderRadius: 20,
    padding: "6px 12px",
    fontSize: 12,
    color: "#C9C6D1",
  },
  prPill: {
    background: "rgba(111,207,151,0.1)",
    border: "1px solid rgba(111,207,151,0.35)",
    borderRadius: 20,
    padding: "6px 12px",
    fontSize: 12,
    color: "#6FCF97",
    display: "flex",
    alignItems: "center",
    gap: 4,
  },
  bigWeightWrap: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    marginTop: 14,
    position: "relative",
  },
  bigWeight: {
    fontFamily: "'Oswald', sans-serif",
    fontSize: 68,
    fontWeight: 700,
    color: "#F5F3EF",
    lineHeight: 1,
    display: "flex",
    alignItems: "baseline",
    gap: 6,
  },
  bigWeightUnit: {
    fontSize: 18,
    fontWeight: 500,
    color: "#8B8894",
  },
  prBadge: {
    marginTop: 6,
    background: "#6FCF97",
    color: "#16151A",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.5,
    borderRadius: 20,
    padding: "3px 10px",
  },
  rulerOuter: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
    marginTop: 10,
  },
  stepBtn: {
    background: "#26242C",
    border: "1px solid #34323C",
    borderRadius: "50%",
    width: 38,
    height: 38,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  rulerViewport: {
    position: "relative",
    width: 130,
    overflow: "hidden",
  },
  rulerTrack: {
    height: "100%",
    overflowY: "scroll",
    scrollSnapType: "y mandatory",
    WebkitOverflowScrolling: "touch",
  },
  rulerItem: {
    scrollSnapAlign: "center",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  rulerTick: {
    width: 18,
    height: 2,
    background: "#E8A33D",
    borderRadius: 2,
  },
  rulerLabel: {
    fontFamily: "'Oswald', sans-serif",
    minWidth: 34,
    textAlign: "left",
  },
  centerLine: {
    position: "absolute",
    left: 0,
    right: 0,
    top: "50%",
    transform: "translateY(-50%)",
    height: ITEM_H,
    background: "rgba(232,163,61,0.08)",
    border: "1px solid rgba(232,163,61,0.4)",
    borderLeft: "none",
    borderRight: "none",
    pointerEvents: "none",
  },
  repsRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
    marginTop: 16,
  },
  repsLabel: {
    fontSize: 13,
    color: "#8B8894",
    marginRight: 4,
  },
  repsBtn: {
    background: "#26242C",
    border: "1px solid #34323C",
    borderRadius: "50%",
    width: 30,
    height: 30,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  repsValue: {
    fontFamily: "'Oswald', sans-serif",
    fontSize: 18,
    fontWeight: 600,
    color: "#F5F3EF",
    minWidth: 24,
    textAlign: "center",
  },
  logBtn: {
    width: "100%",
    background: "#E8A33D",
    border: "none",
    borderRadius: 14,
    padding: "16px",
    fontSize: 15,
    fontWeight: 700,
    color: "#16151A",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    letterSpacing: 0.3,
  },
  historyLabel: {
    fontSize: 13,
    fontWeight: 600,
    color: "#9B98A3",
    marginBottom: 8,
  },
  historyRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    background: "#1B1A20",
    border: "1px solid #2C2A33",
    borderRadius: 10,
    padding: "10px 12px",
  },
  historyWeight: {
    fontSize: 13.5,
    color: "#F5F3EF",
    fontWeight: 500,
  },
  historyRight: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  historyPR: {
    background: "rgba(111,207,151,0.15)",
    color: "#6FCF97",
    fontSize: 10,
    fontWeight: 700,
    borderRadius: 6,
    padding: "2px 6px",
  },
  historyDate: {
    fontSize: 12,
    color: "#8B8894",
  },
};
