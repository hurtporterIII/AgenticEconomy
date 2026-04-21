import Phaser from "phaser";
import MainScene from "./scenes/MainScene";
import {
  getActionLogs,
  getActionLogStats,
  getBehaviorSettings,
  getSpawnTypes,
  getSmallvilleFrame,
  spawnAgent,
  stepSimulation,
  updateBehaviorSettings,
} from "./api/client";
import { initControls } from "./ui/controls";
import { initDashboard } from "./ui/dashboard";
import { initMapOverlay } from "./ui/mapOverlay";

export function bootGame() {
  const app = document.getElementById("app");
  app.innerHTML = `
    <div id="shell">
      <div id="topbar">
        <div>
          <div id="title">AGENTIC ECONOMY: NEON DISTRICT</div>
          <div id="subtitle">Miners, thieves, cop cars, bankers, and live Arc settlement.</div>
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

  async function sync({ stepFirst = false } = {}) {
    if (stepFirst) {
      await stepSimulation();
    }
    syncCount += 1;
    const shouldRefreshLogStats = syncCount % 5 === 0 || !cachedLogStats.path;
    const [frame, logRows, logStats] = await Promise.all([
      getSmallvilleFrame(800),
      getActionLogs(150, lastLogSeq),
      shouldRefreshLogStats ? getActionLogStats() : Promise.resolve(cachedLogStats),
    ]);
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
    scene.applyWorld(state, newEvents);
    mapOverlay.update({
      newEvents,
      resolvePoint: (entityId) => scene.getEntityPoint(entityId),
      captureCanvas: () => game.canvas,
    });
    dashboard.update(state, newEvents, scene.getStoriesSnapshot(), { rows: logRows, stats: cachedLogStats });

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

  return game;
}
