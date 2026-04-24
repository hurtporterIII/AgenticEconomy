import Phaser from "phaser";
import MainScene from "./scenes/MainScene";
import {
  getActionLogs,
  getActionLogStats,
  getAgentsCurrent,
  getBehaviorSettings,
  getEconomyHealth,
  getSpawnTypes,
  getSmallvilleFrame,
  getTransactionsCount,
  getTxDiagnostics,
  probeArcTransaction,
  spawnAgent,
  stepSimulation,
  updateBehaviorSettings,
} from "./api/client";

// Final demo pass: lightweight UI poll cadence for visibility-only data.
// Runs independently of the simulation stepper so the transaction counter,
// economy health, and per-sprite action labels tick smoothly even when
// auto-step is paused. Picked 300ms (inside the 250-500ms band) as a
// balance between "feels live" and "doesn't hammer the backend".
const LIVE_POLL_MS = 300;
import { initControls } from "./ui/controls";
import { initDashboard } from "./ui/dashboard";
import { initMapOverlay } from "./ui/mapOverlay";

function describeArcStatus(d) {
  if (!d || typeof d !== "object") {
    return { className: "arc-status arc-status--unknown", title: "Arc", lines: ["No diagnostics yet."] };
  }
  const cfg = d.config || {};
  const st = d.settlement || {};
  const diag = d.diagnostics || {};
  const strategy = String(st.strategy || "").toLowerCase();
  const realMode = String(cfg.real_mode || "auto").toLowerCase();
  const envOk = Boolean(
    cfg.has_circle_api_key &&
      cfg.has_entity_secret &&
      cfg.has_wallet_address &&
      cfg.has_destination_address,
  );
  const breakerUntil = Number(diag.real_disabled_until || 0);
  const breakerOpen = breakerUntil > Date.now() / 1000;

  const lines = [];
  lines.push(`Settlement: ${strategy || "?"}`);
  lines.push(`TX_REAL_MODE: ${realMode}`);
  if (cfg.blockchain) lines.push(`Chain: ${cfg.blockchain}`);
  lines.push(`Real txs (diag): ${diag.real_tx_count ?? 0} · Sim: ${diag.simulated_tx_count ?? 0}`);
  if (typeof st.pending_intents === "number") lines.push(`Pending intents: ${st.pending_intents}`);
  if (diag.last_tx_hash) lines.push(`Last hash: ${String(diag.last_tx_hash).slice(0, 18)}…`);
  if (diag.last_failure_reason) lines.push(`Last issue: ${diag.last_failure_reason}`);

  if (strategy === "off" || realMode === "off") {
    return {
      className: "arc-status arc-status--sim",
      title: "SIMULATION",
      subtitle: "Settlement or real mode is off.",
      lines,
    };
  }
  if (!envOk) {
    return {
      className: "arc-status arc-status--sim",
      title: "SETUP REQUIRED",
      subtitle: "Circle / wallet env incomplete — only simulated hashes.",
      lines,
    };
  }
  if (breakerOpen) {
    return {
      className: "arc-status arc-status--warn",
      title: "LIVE (PAUSED)",
      subtitle: diag.breaker_reason ? `Breaker: ${diag.breaker_reason}` : "Temporary pause on real submits.",
      lines,
    };
  }
  if (realMode === "strict") {
    return {
      className: "arc-status arc-status--live",
      title: "LIVE — STRICT",
      subtitle: "Failed real transfers raise errors (no silent simulate).",
      lines,
    };
  }
  return {
    className: "arc-status arc-status--live",
    title: "LIVE — AUTO",
    subtitle: "Tries Arc; may simulate on errors (see diagnostics).",
    lines,
  };
}

export function bootGame() {
  const app = document.getElementById("app");
  app.innerHTML = `
    <div id="shell">
      <div id="topbar">
        <div class="topbar-left">
          <div id="title">AGENTIC ECONOMY: NEON DISTRICT</div>
          <div id="subtitle">Miners, thieves, cop cars, bankers, and live Arc settlement.</div>
        </div>
        <div id="arc-status" class="arc-status arc-status--unknown" title="">
          <div class="arc-status-title">…</div>
          <div class="arc-status-sub"></div>
        </div>
      </div>
      <div id="game-container">
        <div id="map-overlay"></div>
      </div>
      <div id="sidepanel">
        <div id="controls-root"></div>
        <div id="dashboard-root"></div>
      </div>
    </div>
  `;

  const scene = new MainScene();
  const dashboard = initDashboard(document.getElementById("dashboard-root"));
  const mapOverlay = initMapOverlay(document.getElementById("map-overlay"));

  const game = new Phaser.Game({
    type: Phaser.AUTO,
    width: 960,
    height: 540,
    backgroundColor: "#081126",
    scene: [scene],
    parent: "game-container",
  });

  let autoInterval = null;
  let lastEventCount = 0;
  let soundEnabled = false;
  let viewerMode = "night";
  let speedMultiplier = 1;
  let autoEnabled = false;
  let autoBaseIntervalMs = 1500;
  const replayBuffer = [];
  let latestSnapshot = null;
  let lastLogSeq = null;
  let syncCount = 0;
  let cachedLogStats = {};
  let startupChaseNudgeDone = false;
  const arcStatusEl = document.getElementById("arc-status");

  function applyArcStatusUi(payload) {
    if (!arcStatusEl) return;
    const { className, title, subtitle, lines } = describeArcStatus(payload);
    arcStatusEl.className = className;
    arcStatusEl.title = (lines || []).join("\n");
    const t = arcStatusEl.querySelector(".arc-status-title");
    const s = arcStatusEl.querySelector(".arc-status-sub");
    if (t) t.textContent = title || "…";
    if (s) s.textContent = subtitle || "";
  }

  async function ensureStartupChaseNudge(snapshot) {
    if (startupChaseNudgeDone) return;
    startupChaseNudgeDone = true;
    const entities = Object.values(snapshot?.entities || {});
    const counts = { thief: 0, cop: 0 };
    for (const entity of entities) {
      if (entity.type === "thief") counts.thief += 1;
      if (entity.type === "cop") counts.cop += 1;
    }

    const spawnOps = [];
    if (counts.thief < 2) {
      for (let i = 0; i < 2 - counts.thief; i += 1) {
        spawnOps.push(spawnAgent("thief", { balance: 2 }));
      }
    }
    if (counts.cop < 1) {
      spawnOps.push(spawnAgent("cop", { balance: 2 }));
    }
    if (spawnOps.length === 0) return;

    await Promise.all(spawnOps);
    await stepSimulation();
  }

  let syncInFlight = false;

  async function sync({ stepFirst = false } = {}) {
    // Coalesce overlapping calls: if a sync is already running, skip instead
    // of stacking requests. Prevents duplicate fetches when auto-tick and a
    // manual button press (or a retry) fire close together.
    if (syncInFlight) return;
    syncInFlight = true;
    try {
      return await runSync({ stepFirst });
    } finally {
      syncInFlight = false;
    }
  }

  async function runSync({ stepFirst = false } = {}) {
    if (stepFirst) {
      await stepSimulation();
    }
    syncCount += 1;
    const shouldRefreshLogStats = syncCount % 5 === 0 || !cachedLogStats.path;
    // Final demo pass: also pull live economy health + current-action map
    // so the UI can display transaction count and per-sprite labels sourced
    // from the backend (no frontend inference).
    const [frame, logRows, logStats, txDiag, health, currentActions] = await Promise.all([
      getSmallvilleFrame(800),
      getActionLogs(150, lastLogSeq),
      shouldRefreshLogStats ? getActionLogStats() : Promise.resolve(cachedLogStats),
      getTxDiagnostics().catch(() => null),
      getEconomyHealth().catch(() => null),
      getAgentsCurrent().catch(() => ({})),
    ]);
    applyArcStatusUi(txDiag);
    const state = frame?.state || {};
    const events = Array.isArray(frame?.events) ? frame.events : [];
    cachedLogStats = logStats || cachedLogStats || {};
    if (Array.isArray(logRows) && logRows.length) {
      const newest = logRows[logRows.length - 1];
      if (newest && typeof newest._seq === "number") {
        lastLogSeq = newest._seq;
      }
    }
    if (lastEventCount > events.length) {
      lastEventCount = 0;
    }
    const newEvents = events.slice(lastEventCount);
    lastEventCount = events.length;
    latestSnapshot = state;
    if (newEvents.length) {
      replayBuffer.push(...newEvents);
      if (replayBuffer.length > 500) {
        replayBuffer.splice(0, replayBuffer.length - 500);
      }
    }
    scene.applyWorld(state, newEvents, currentActions || {});
    mapOverlay.update({
      newEvents,
      resolvePoint: (entityId) => scene.getEntityPoint(entityId),
      captureCanvas: () => game.canvas,
    });
    dashboard.update(
      state,
      newEvents,
      scene.getStoriesSnapshot(),
      { rows: logRows, stats: cachedLogStats },
      { health: health || null, currentActions: currentActions || {} },
    );

    if (!startupChaseNudgeDone) {
      await ensureStartupChaseNudge(state);
      await sync();
    }
  }

  function stopAuto() {
    if (autoInterval) {
      clearInterval(autoInterval);
      autoInterval = null;
    }
  }

  initControls(document.getElementById("controls-root"), {
    onSpawn: async (entityType, count, balance) => {
      for (let i = 0; i < count; i += 1) {
        await spawnAgent(entityType, { balance });
      }
      await sync();
    },
    onStep: async () => {
      await sync({ stepFirst: true });
    },
    onAutoToggle: (enabled, intervalMs) => {
      autoEnabled = enabled;
      autoBaseIntervalMs = Math.max(250, Number(intervalMs || 1500));
      stopAuto();
      if (enabled) {
        const effectiveInterval = Math.max(80, Math.round(autoBaseIntervalMs / Math.max(1, speedMultiplier)));
        autoInterval = setInterval(() => {
          sync({ stepFirst: true }).catch(() => {
            stopAuto();
            autoEnabled = false;
          });
        }, effectiveInterval);
      }
    },
    onSync: async () => {
      await sync();
    },
    onArcProbe: async () => {
      const result = await probeArcTransaction(0.001);
      await sync();
      return result;
    },
    onPassChange: (passId) => {
      scene.setVisualPass(passId, soundEnabled, viewerMode);
      setTimeout(() => {
        sync().catch(() => {
          // ignore sync failure while backend is offline
        });
      }, 50);
    },
    onSoundToggle: async (enabled) => {
      soundEnabled = enabled;
      await scene.setAudioEnabled(enabled);
    },
    onViewerToggle: (mode) => {
      viewerMode = mode;
      scene.setViewerMode(mode);
    },
    onSpeedChange: (speed, intervalMs) => {
      speedMultiplier = Math.max(1, Number(speed || 1));
      scene.setPlaybackSpeed(speedMultiplier);
      if (typeof intervalMs === "number" && Number.isFinite(intervalMs)) {
        autoBaseIntervalMs = Math.max(250, Number(intervalMs));
      }
      if (autoEnabled) {
        stopAuto();
        const effectiveInterval = Math.max(80, Math.round(autoBaseIntervalMs / speedMultiplier));
        autoInterval = setInterval(() => {
          sync({ stepFirst: true }).catch(() => {
            stopAuto();
            autoEnabled = false;
          });
        }, effectiveInterval);
      }
    },
    onExportReplay: async () => {
      const payload = {
        exported_at: new Date().toISOString(),
        events_captured: replayBuffer.length,
        metrics: latestSnapshot?.metrics || {},
        entities: Object.keys(latestSnapshot?.entities || {}).length,
        recent_events: replayBuffer.slice(-250),
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `agentic-replay-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
    onLoadBehaviorSettings: async () => getBehaviorSettings(),
    onSaveBehaviorSettings: async (payload) => {
      const result = await updateBehaviorSettings(payload);
      return result.settings || {};
    },
  });

  getSpawnTypes()
    .then((types) => {
      const subtitle = document.getElementById("subtitle");
      subtitle.textContent = `${subtitle.textContent} Agent cap: ${types.max_total_agents}`;
    })
    .catch(() => {
      // Leave subtitle unchanged if endpoint is unavailable.
    });

  sync().catch(() => {
    // Start with static scene if backend is offline.
  });

  // Dedicated 300ms "visibility" poll: pulls only the three demo endpoints
  // and updates the nano-summary panel + sprite labels in place. Guarded
  // by `livePollInFlight` so a slow request never stacks with the next
  // tick, and wrapped in try/catch so a transient 5xx doesn't kill the
  // interval. Does NOT step the simulation.
  let livePollInFlight = false;
  setInterval(async () => {
    if (livePollInFlight) return;
    livePollInFlight = true;
    try {
      const [health, currentActions, txCount] = await Promise.all([
        getEconomyHealth().catch(() => null),
        getAgentsCurrent().catch(() => ({})),
        getTransactionsCount().catch(() => null),
      ]);
      // Prefer the dedicated counter endpoint when it responds, since it's
      // cheaper than /economy/health and is the one judges will watch.
      const mergedHealth = health
        ? { ...health, total_transactions: Number(txCount?.total_transactions ?? health.total_transactions ?? 0) }
        : (txCount ? { total_transactions: Number(txCount.total_transactions || 0), healthy: true } : null);
      dashboard.updateLive({ health: mergedHealth, currentActions });
      scene.applyLiveActions(currentActions || {});
    } catch {
      // Swallow transient errors so the interval keeps running.
    } finally {
      livePollInFlight = false;
    }
  }, LIVE_POLL_MS);

  return game;
}
