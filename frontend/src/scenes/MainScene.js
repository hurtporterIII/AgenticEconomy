import Phaser from "phaser";

const WIDTH = 960;
const HEIGHT = 540;
const TILE = 32;

const THEMES = {
  neon: {
    name: "Neon District",
    skyA: 0x091325,
    skyB: 0x12233b,
    tileA: 0x1c2f4a,
    tileB: 0x17263f,
    road: 0x223850,
    zoneStroke: 0x8ad4ff,
    zoneFill: 0x21486a,
    text: "#d9ecff",
  },
  village: {
    name: "Cyber Village",
    skyA: 0x1a2a1f,
    skyB: 0x223a2c,
    tileA: 0x37553f,
    tileB: 0x2e4a35,
    road: 0x3f5f48,
    zoneStroke: 0xb7f0c1,
    zoneFill: 0x4d7b59,
    text: "#ebf8ef",
  },
  dusk: {
    name: "Dusk Frontier",
    skyA: 0x2d1b1a,
    skyB: 0x402621,
    tileA: 0x5a3c34,
    tileB: 0x4b322b,
    road: 0x65443a,
    zoneStroke: 0xffc89f,
    zoneFill: 0x815944,
    text: "#fff0e4",
  },
  rain: {
    name: "Rainline Megacity",
    skyA: 0x101a2a,
    skyB: 0x152437,
    tileA: 0x24384f,
    tileB: 0x1f3044,
    road: 0x2c435c,
    zoneStroke: 0x9fd8ff,
    zoneFill: 0x325c82,
    text: "#e2f3ff",
  },
  orbit: {
    name: "Orbit Colony",
    skyA: 0x151732,
    skyB: 0x1d2242,
    tileA: 0x343b6a,
    tileB: 0x2d345f,
    road: 0x465286,
    zoneStroke: 0xc8d3ff,
    zoneFill: 0x5a67a1,
    text: "#edf0ff",
  },
  wasteland: {
    name: "Crimson Wasteland",
    skyA: 0x2a120f,
    skyB: 0x381714,
    tileA: 0x56302a,
    tileB: 0x472722,
    road: 0x6a3a33,
    zoneStroke: 0xffb6a4,
    zoneFill: 0x865044,
    text: "#ffece8",
  },
};

const DISTRICTS = {
  worker: { x: 170, y: 390, w: 220, h: 140, label: "MINING QUARRY" },
  thief: { x: 480, y: 340, w: 260, h: 170, label: "SHADOW DISTRICT" },
  cop: { x: 790, y: 320, w: 220, h: 160, label: "PRECINCT NEXUS" },
  banker: { x: 730, y: 120, w: 160, h: 100, label: "CREDIT TOWER" },
  bank: { x: 700, y: 220, w: 190, h: 120, label: "CENTRAL BANK" },
};

const ROLE_COLORS = {
  worker: 0x5fd892,
  thief: 0xf07a8f,
  cop: 0x79b6ff,
  banker: 0x79d5d0,
  bank: 0xdedede,
};

const ACTION_TINTS = {
  work: 0x62ff8b,
  steal: 0xff556f,
  chase: 0x55a8ff,
  bank: 0xf2ce6f,
  idle: 0xffffff,
};

function zoneForType(type) {
  return DISTRICTS[type] || DISTRICTS.worker;
}

function inferActionFromEvent(event) {
  const type = String(event?.type || "");
  if (type === "worker_earn") return "work";
  if (type === "steal_agent" || type === "steal_bank") return "steal";
  if (type === "cop_chase") return "chase";
  if (type.startsWith("bank_") || type === "debit" || type === "credit") return "bank";
  return "idle";
}

export default class MainScene extends Phaser.Scene {
  constructor() {
    super("MainScene");
    this.entities = new Map();
    this.lastKnownState = null;
    this.agentStories = new Map();
    this.passId = "neon";
    this.viewerMode = "night";
    this.audioEnabled = false;
    this.playbackSpeed = 1;
    this.roleTexturesReady = false;
    this.actionCache = new Map();
    this.idJitter = new Map();
    this.chaseLine = null;
    this.chaseLineExpireAt = 0;
    this.chaseFocusExpireAt = 0;
    this.lastCameraTargetId = null;
    this.legendText = null;
    this.agentPanelText = null;
    this.metricsText = null;
    this.demoStartAt = 0;
    this.cameraPhase = "wide";
    this.firstChaseCopId = null;
    this.recentEvents = [];
    this.lastRealTxHash = null;
    this.txFlashText = null;
  }

  init(data) {
    this.passId = data?.passId || this.passId;
    this.viewerMode = data?.viewerMode || this.viewerMode;
    this.audioEnabled = Boolean(data?.audioEnabled);
  }

  preload() {}

  create() {
    this.renderWorld();
    this.ensureRoleTextures();
    this.chaseLine = this.add.graphics();
    this.chaseLine.setDepth(900);
    this.demoStartAt = this.time.now;
    this.setupHud();
    this.setupHotkeys();
    this.cameras.main.setZoom(0.9);
    this.cameras.main.centerOn(WIDTH / 2, HEIGHT / 2);
  }

  setVisualPass(passId, audioEnabled = this.audioEnabled, viewerMode = this.viewerMode) {
    if (!THEMES[passId]) return;
    this.scene.restart({ passId, audioEnabled, viewerMode });
  }

  setViewerMode(mode) {
    if (mode !== "day" && mode !== "night") return;
    this.viewerMode = mode;
    this.renderWorld();
  }

  setPlaybackSpeed(multiplier) {
    this.playbackSpeed = Math.max(1, Number(multiplier || 1));
    this.anims.globalTimeScale = this.playbackSpeed;
  }

  async setAudioEnabled(enabled) {
    this.audioEnabled = Boolean(enabled);
  }

  ensureRoleTextures() {
    if (this.roleTexturesReady) return;
    ["worker", "thief", "cop", "banker", "bank"].forEach((role) => this.createRoleSheet(role));
    this.roleTexturesReady = true;
  }

  createRoleSheet(role) {
    const key = `${role}_sheet`;
    if (this.textures.exists(key)) return;
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 32;
    const ctx = canvas.getContext("2d");
    const base = ROLE_COLORS[role] || 0xffffff;
    for (let f = 0; f < 4; f += 1) {
      const ox = f * 32;
      ctx.clearRect(ox, 0, 32, 32);
      ctx.fillStyle = "rgba(0,0,0,0)";
      ctx.fillRect(ox, 0, 32, 32);
      ctx.fillStyle = "#0b1220";
      ctx.beginPath();
      ctx.arc(ox + 16, 9, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = `#${base.toString(16).padStart(6, "0")}`;
      ctx.fillRect(ox + 11, 14, 10, 12);
      const legOffset = (f % 2 === 0) ? 0 : 2;
      ctx.fillRect(ox + 11 - legOffset, 24, 4, 7);
      ctx.fillRect(ox + 17 + legOffset, 24, 4, 7);
    }
    this.textures.addSpriteSheet(key, canvas, { frameWidth: 32, frameHeight: 32 });
    const walkKey = `${role}_walk`;
    const idleKey = `${role}_idle`;
    if (!this.anims.exists(walkKey)) {
      this.anims.create({
        key: walkKey,
        frames: this.anims.generateFrameNumbers(key, { start: 0, end: 3 }),
        frameRate: 8,
        repeat: -1,
      });
    }
    if (!this.anims.exists(idleKey)) {
      this.anims.create({
        key: idleKey,
        frames: [{ key, frame: 0 }],
        frameRate: 1,
        repeat: -1,
      });
    }
  }

  renderWorld() {
    this.children.removeAll();
    const theme = THEMES[this.passId] || THEMES.neon;

    const bg = this.add.graphics();
    bg.fillGradientStyle(theme.skyA, theme.skyB, theme.skyB, theme.skyA, 1);
    bg.fillRect(0, 0, WIDTH, HEIGHT);

    for (let y = 0; y < HEIGHT; y += TILE) {
      for (let x = 0; x < WIDTH; x += TILE) {
        const checker = ((x / TILE) + (y / TILE)) % 2 === 0;
        bg.fillStyle(checker ? theme.tileA : theme.tileB, 0.7);
        bg.fillRect(x, y, TILE, TILE);
      }
    }

    bg.fillStyle(theme.road, 0.35);
    bg.fillRect(0, 250, WIDTH, 44);
    bg.fillRect(460, 0, 44, HEIGHT);

    Object.values(DISTRICTS).forEach((zone) => {
      const rect = this.add.rectangle(zone.x, zone.y, zone.w, zone.h, theme.zoneFill, 0.24);
      rect.setStrokeStyle(2, theme.zoneStroke, 0.7);
      this.add.text(zone.x, zone.y - zone.h / 2 - 16, zone.label, {
        fontFamily: "Orbitron",
        fontSize: "12px",
        color: theme.text,
        stroke: "#050b14",
        strokeThickness: 3,
      }).setOrigin(0.5);
    });

    if (this.viewerMode === "night") {
      this.add.rectangle(WIDTH / 2, HEIGHT / 2, WIDTH, HEIGHT, 0x04070c, 0.2);
    } else {
      this.add.rectangle(WIDTH / 2, HEIGHT / 2, WIDTH, HEIGHT, 0xfff6dc, 0.08);
    }
  }

  applyWorld(snapshot, newEvents = []) {
    if (!snapshot?.entities) return;
    this.lastKnownState = snapshot;
    this.captureActionsFromEvents(newEvents);
    this.syncEntities(snapshot.entities, snapshot.balances || {});
    this.refreshStories(snapshot.entities);
    this.renderEventFx(newEvents);
    this.updateHud(snapshot);
    this.captureRecentEvents(newEvents);
  }

  captureActionsFromEvents(events) {
    const now = this.time.now;
    for (const event of events || []) {
      const action = inferActionFromEvent(event);
      if (event.worker_id) this.actionCache.set(event.worker_id, { action, until: now + 1800 });
      if (event.thief_id) this.actionCache.set(event.thief_id, { action, until: now + 1800 });
      if (event.cop_id) this.actionCache.set(event.cop_id, { action, until: now + 1800 });
      if (event.bank_id) this.actionCache.set(event.bank_id, { action: "bank", until: now + 1800 });
      if (event.target_id && action === "steal") this.actionCache.set(event.target_id, { action: "idle", until: now + 1200 });
      if (event.agent && event.type === "api_call") this.actionCache.set(event.agent, { action: "chase", until: now + 1500 });
      if (event.type === "cop_chase" && event.cop_id && event.target_id) {
        if (!this.firstChaseCopId) this.firstChaseCopId = event.cop_id;
        this.lockChaseCamera(event.cop_id, event.target_id, 2600);
      }
      const txHash = String(event?.tx_hash || "");
      if (txHash.startsWith("0x")) {
        this.lastRealTxHash = txHash;
      }
    }
  }

  lockChaseCamera(copId, targetId, durationMs = 2500) {
    const cop = this.entities.get(copId);
    const target = this.entities.get(targetId);
    if (!cop || !target) return;
    this.chaseFocusExpireAt = this.time.now + durationMs;
    this.lastCameraTargetId = copId;
    this.chaseLineExpireAt = this.time.now + durationMs;
  }

  inferAction(entityId, entity) {
    const cached = this.actionCache.get(entityId);
    if (cached && cached.until > this.time.now) return cached.action;
    if (entity.type === "cop" && entity.target) return "chase";
    if (entity.type === "worker") return "work";
    if (entity.type === "bank" || entity.type === "banker") return "bank";
    return "idle";
  }

  syncEntities(entityMap, balances) {
    const incoming = new Set(Object.keys(entityMap));

    for (const [id, view] of this.entities.entries()) {
      if (!incoming.has(id)) {
        view.label.destroy();
        view.balance.destroy();
        view.story.destroy();
        view.sprite.destroy();
        this.entities.delete(id);
        this.agentStories.delete(id);
      }
    }

    for (const [id, entity] of Object.entries(entityMap)) {
      const zone = zoneForType(entity.type);
      const targetX = Number.isFinite(Number(entity.x)) ? Number(entity.x) : zone.x;
      const targetY = Number.isFinite(Number(entity.y)) ? Number(entity.y) : zone.y;
      const balance = Number(balances[id] ?? 0);
      this.upsertEntity(entity, targetX, targetY, balance);
    }

    const first = this.entities.values().next().value;
    if (first && this.cameras.main._follow !== first.sprite) {
      this.cameras.main.startFollow(first.sprite, true, 0.04, 0.04);
      this.cameras.main.setZoom(1.05);
    }
  }

  upsertEntity(entity, x, y, balance) {
    const existing = this.entities.get(entity.id);
    if (!existing) {
      const role = entity.type || "worker";
      const sprite = this.add.sprite(x, y, `${role}_sheet`, 0).setDepth(10);
      sprite.play(`${role}_walk`);
      const label = this.add.text(x, y + 26, entity.id, {
        fontFamily: "Rajdhani",
        fontSize: "12px",
        color: "#f1f5ff",
        stroke: "#090f1a",
        strokeThickness: 3,
      }).setOrigin(0.5);
      const balanceText = this.add.text(x, y - 28, `${balance.toFixed(2)} USDC`, {
        fontFamily: "Rajdhani",
        fontSize: "11px",
        color: "#bff7d5",
        stroke: "#081222",
        strokeThickness: 3,
      }).setOrigin(0.5);
      const story = this.add.text(x, y - 42, "", {
        fontFamily: "Rajdhani",
        fontSize: "11px",
        color: "#d5e9ff",
        stroke: "#07111d",
        strokeThickness: 3,
      }).setOrigin(0.5);
      this.entities.set(entity.id, {
        sprite,
        label,
        balance: balanceText,
        story,
        targetX: x,
        targetY: y,
        action: "idle",
        jitterX: this.getJitter(entity.id, 7),
        jitterY: this.getJitter(entity.id, 13),
      });
      return;
    }
    existing.targetX = x + existing.jitterX;
    existing.targetY = y + existing.jitterY;
    existing.balance.setText(`${balance.toFixed(2)} USDC`);
    existing.action = this.inferAction(entity.id, entity);
  }

  getJitter(id, salt = 0) {
    const key = `${id}_${salt}`;
    if (this.idJitter.has(key)) return this.idJitter.get(key);
    let hash = 0;
    for (let i = 0; i < id.length; i += 1) {
      hash = ((hash << 5) - hash) + id.charCodeAt(i) + salt;
      hash |= 0;
    }
    const value = (Math.abs(hash) % 10) - 5;
    this.idJitter.set(key, value);
    return value;
  }

  refreshStories(entityMap) {
    for (const [id, entity] of Object.entries(entityMap || {})) {
      const action = this.inferAction(id, entity);
      let line = "Walking the district";
      if (action === "work") line = "Heading to work";
      if (action === "steal") line = "Lining up a steal";
      if (action === "chase") line = "Pursuing suspect";
      if (action === "bank") line = "Managing funds";
      this.agentStories.set(id, { line, progress: 0.6, mood: action });
    }
  }

  playState(entityId, view, moving, role) {
    const anim = moving ? `${role}_walk` : `${role}_idle`;
    if (view.sprite.anims.currentAnim?.key !== anim) {
      view.sprite.play(anim, true);
    }
    const action = view.action || "idle";
    view.sprite.setTint(ACTION_TINTS[action] || ACTION_TINTS.idle);
  }

  getStoriesSnapshot() {
    const out = {};
    for (const [id, story] of this.agentStories.entries()) {
      out[id] = story;
    }
    return out;
  }

  getEntityPoint(entityId) {
    const view = this.entities.get(entityId);
    if (!view) return null;
    return { x: view.sprite.x, y: view.sprite.y };
  }

  update() {
    if (!this.lastKnownState?.entities) return;
    for (const [id, view] of this.entities.entries()) {
      const entity = this.lastKnownState.entities[id];
      if (!entity) continue;
      const t = this.time.now * 0.001 + view.jitterX;
      const wobbleX = Math.sin(t) * 15;
      const wobbleY = Math.cos(t * 0.8) * 15;
      const activeTargetX = view.targetX + wobbleX;
      const activeTargetY = view.targetY + wobbleY;

      const dx = activeTargetX - view.sprite.x;
      const dy = activeTargetY - view.sprite.y;
      const near = Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5;
      if (near) {
        view.sprite.x = activeTargetX;
        view.sprite.y = activeTargetY;
      } else {
        view.sprite.x += dx * 0.12;
        view.sprite.y += dy * 0.12;
      }
      const moving = true;
      this.playState(id, view, moving, entity.type || "worker");

      if (dx < -1) view.sprite.setFlipX(true);
      if (dx > 1) view.sprite.setFlipX(false);
      view.sprite.setDepth(view.sprite.y);

      view.label.setPosition(view.sprite.x, view.sprite.y + 26);
      view.label.setDepth(view.sprite.y + 5);
      view.balance.setPosition(view.sprite.x, view.sprite.y - 28);
      view.balance.setDepth(view.sprite.y + 5);
      const story = this.agentStories.get(id);
      view.story.setPosition(view.sprite.x, view.sprite.y - 42);
      view.story.setText(story?.line || "");
      view.story.setDepth(view.sprite.y + 5);
    }

    this.drawChaseLine();
    this.releaseChaseCameraIfNeeded();
    this.runDemoCameraScript();
  }

  drawChaseLine() {
    if (!this.chaseLine) return;
    this.chaseLine.clear();
    if (this.time.now > this.chaseLineExpireAt) return;
    const entities = this.lastKnownState?.entities || {};
    for (const [id, entity] of Object.entries(entities)) {
      if (entity.type !== "cop" || !entity.target) continue;
      const cop = this.entities.get(id);
      const target = this.entities.get(entity.target);
      if (!cop || !target) continue;
      this.chaseLine.lineStyle(2, 0xff4d4d, 0.9);
      this.chaseLine.beginPath();
      this.chaseLine.moveTo(cop.sprite.x, cop.sprite.y);
      this.chaseLine.lineTo(target.sprite.x, target.sprite.y);
      this.chaseLine.strokePath();
    }
  }

  releaseChaseCameraIfNeeded() {
    if (this.time.now <= this.chaseFocusExpireAt) return;
    this.lastCameraTargetId = null;
  }

  renderEventFx(events) {
    for (const event of events || []) {
      if (event.type === "worker_earn" && event.worker_id) {
        this.spawnFloatText(event.worker_id, `+${Number(event.reward || 0).toFixed(1)}`, "#66ff9a");
      } else if ((event.type === "steal_agent" || event.type === "steal_bank") && event.thief_id) {
        this.spawnFloatText(event.thief_id, `+$${Number(event.amount || 0).toFixed(1)}`, "#ff7c9a");
      } else if (event.type === "cop_chase" && event.cop_id) {
        this.spawnFloatText(event.cop_id, "CHASE", "#74b7ff");
      }
    }
  }

  spawnFloatText(entityId, text, color) {
    const view = this.entities.get(entityId);
    if (!view) return;
    const t = this.add.text(view.sprite.x, view.sprite.y - 18, text, {
      fontFamily: "Orbitron",
      fontSize: "11px",
      color,
      stroke: "#06101d",
      strokeThickness: 3,
    }).setOrigin(0.5).setDepth(999);
    this.tweens.add({
      targets: t,
      y: t.y - 14,
      alpha: 0,
      duration: 800,
      onComplete: () => t.destroy(),
    });
  }

  setupHud() {
    this.legendText = this.add.text(10, 10, [
      "GREEN = work",
      "RED = theft",
      "BLUE = police",
      "LINES = chase",
    ].join("\n"), {
      fontFamily: "Rajdhani",
      fontSize: "12px",
      color: "#ffffff",
      stroke: "#05101d",
      strokeThickness: 3,
    }).setDepth(1000).setScrollFactor(0);

    this.agentPanelText = this.add.text(10, 72, "", {
      fontFamily: "Rajdhani",
      fontSize: "12px",
      color: "#ffffff",
      stroke: "#05101d",
      strokeThickness: 3,
    }).setDepth(1000).setScrollFactor(0);

    this.metricsText = this.add.text(WIDTH - 250, HEIGHT - 36, "", {
      fontFamily: "Rajdhani",
      fontSize: "12px",
      color: "#ffffff",
      stroke: "#05101d",
      strokeThickness: 3,
    }).setDepth(1000).setScrollFactor(0);
  }

  setupHotkeys() {
    this.input.keyboard.on("keydown-P", () => {
      const tx = this.lastRealTxHash;
      if (!tx) return;
      if (this.txFlashText) {
        this.txFlashText.destroy();
        this.txFlashText = null;
      }
      this.txFlashText = this.add.text(WIDTH / 2, 20, tx, {
        fontFamily: "Orbitron",
        fontSize: "12px",
        color: "#00ffcc",
        stroke: "#021012",
        strokeThickness: 4,
      }).setOrigin(0.5).setDepth(1100).setScrollFactor(0);
      this.txFlashText.setAlpha(1);
      this.tweens.add({
        targets: this.txFlashText,
        alpha: 0,
        duration: 1200,
        onComplete: () => {
          if (this.txFlashText) {
            this.txFlashText.destroy();
            this.txFlashText = null;
          }
        },
      });
    });
  }

  captureRecentEvents(events) {
    if (!Array.isArray(events) || events.length === 0) return;
    this.recentEvents.push(...events);
    if (this.recentEvents.length > 200) {
      this.recentEvents.splice(0, this.recentEvents.length - 200);
    }
  }

  updateHud(snapshot) {
    if (!snapshot) return;
    const entities = snapshot.entities || {};
    const balances = snapshot.balances || {};
    const tracked = this.pickTrackedAgent(entities);
    if (tracked) {
      const balance = Number(balances[tracked.id] || 0);
      const action = this.inferAction(tracked.id, tracked);
      this.agentPanelText.setText([
        `Agent: ${tracked.id}`,
        `State: ${tracked.reflection || "neutral"}`,
        `Action: ${tracked.top_action || action || "idle"}`,
        `Balance: ${balance.toFixed(2)} USDC`,
      ].join("\n"));
    }
    const metrics = snapshot.metrics || {};
    const tx = Number(metrics.successful_tx || 0);
    const cpa = Number(metrics.cost_per_action || 0);
    const sr = Number(metrics.success_rate || 0) * 100;
    this.metricsText.setText([
      `TX: ${tx}`,
      `$/action: ${cpa.toFixed(4)}`,
      `Success: ${sr.toFixed(0)}%`,
    ].join(" | "));
  }

  pickTrackedAgent(entities) {
    const values = Object.values(entities || {});
    if (values.length === 0) return null;
    return values.find((e) => e.type === "cop") || values[0];
  }

  runDemoCameraScript() {
    const elapsed = this.time.now - this.demoStartAt;
    if (elapsed < 10000) {
      if (this.cameraPhase !== "wide") {
        this.cameraPhase = "wide";
      }
      this.cameras.main.stopFollow();
      this.cameras.main.zoomTo(0.9, 200);
      this.cameras.main.pan(WIDTH / 2, HEIGHT / 2, 200);
      return;
    }
    if (elapsed < 25000) {
      if (this.firstChaseCopId) {
        const cop = this.entities.get(this.firstChaseCopId);
        if (cop) {
          if (this.cameraPhase !== "chase") {
            this.cameraPhase = "chase";
            this.cameras.main.startFollow(cop.sprite, true, 0.08, 0.08);
            this.cameras.main.zoomTo(1.05, 300);
          }
          return;
        }
      }
      return;
    }
    if (elapsed < 40000) {
      if (this.cameraPhase !== "zones") {
        this.cameraPhase = "zones";
        this.cameras.main.stopFollow();
        this.cameras.main.zoomTo(1.0, 500);
        this.cameras.main.pan(500, 300, 1500);
      }
      return;
    }
    if (this.cameraPhase !== "proof") {
      this.cameraPhase = "proof";
      this.cameras.main.stopFollow();
      this.cameras.main.zoomTo(1.0, 400);
      this.cameras.main.pan(520, 280, 1200);
    }
  }
}
