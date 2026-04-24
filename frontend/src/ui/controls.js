export function initControls(root, handlers) {
  root.innerHTML = `
    <div class="panel-block">
      <div class="panel-title">Command Deck</div>
      <div class="panel-help">Hover any control for a quick explanation.</div>
      <div class="controls-grid">
        <div>
          <label for="role" title="Choose which type of agent to create.">Role</label>
          <select id="role" title="Select the role for newly spawned agents.">
            <option value="worker">Miner Worker</option>
            <option value="thief">Thief</option>
            <option value="cop">Cop Car</option>
            <option value="banker">Banker</option>
            <option value="bank">Bank</option>
          </select>
        </div>
        <div>
          <label for="count" title="How many agents to spawn in one action.">Count</label>
          <input id="count" type="number" min="1" max="1000" value="1" title="Spawn quantity for the selected role." />
        </div>
        <div>
          <label for="balance" title="Initial balance assigned to each spawned agent.">Start Balance</label>
          <input id="balance" type="number" min="0" step="0.1" value="1" title="Starting balance for each new spawned agent." />
        </div>
        <div>
          <label for="tick-rate" title="Engine step interval while auto mode is running.">Auto Step (ms)</label>
          <input id="tick-rate" type="number" min="250" step="250" value="1500" title="Lower values make simulation step more often in auto mode." />
        </div>
        <div>
          <label for="speed-multiplier" title="Playback and step speed multiplier.">Speed</label>
          <select id="speed-multiplier" title="Increase simulation and animation speed above normal.">
            <option value="1">1x (Normal)</option>
            <option value="1.5">1.5x</option>
            <option value="2">2x</option>
            <option value="3">3x</option>
          </select>
        </div>
        <div>
          <label for="visual-pass" title="Select visual world art direction.">Visual Pass</label>
          <select id="visual-pass" title="Switch map mood and palette without changing simulation rules.">
            <option value="neon">Pass 1: Neon District</option>
            <option value="dusk">Pass 2: Dusk Frontier</option>
            <option value="rain">Pass 3: Rainline Megacity</option>
            <option value="orbit">Pass 4: Orbit Colony</option>
            <option value="village">Pass 5: Cyber Village</option>
            <option value="wasteland">Pass 6: Crimson Wasteland</option>
          </select>
        </div>
      </div>
      <div class="controls-grid" style="margin-top:8px">
        <button id="spawn-btn" class="btn-accent" title="Create agents with the selected role, count, and starting balance.">Spawn Agents</button>
        <button id="step-btn" title="Execute one simulation tick.">Run One Step</button>
        <button id="auto-btn" title="Toggle continuous simulation stepping.">Start Auto</button>
        <button id="sync-btn" title="Fetch latest state and events from backend.">Refresh State</button>
        <button id="pass-btn" title="Apply selected visual pass to the scene.">Apply Pass</button>
        <button id="sound-btn" title="Toggle ambient and event sound effects.">Sound Off</button>
        <button id="viewer-btn" title="Viewer-only lighting mode. Does not affect agent logic.">Viewer: Night</button>
        <button id="export-btn" title="Download recent events and metrics as replay JSON.">Export Replay</button>
        <button id="arc-probe-btn" title="Send a tiny probe USDC transfer on Arc (Circle dev wallets). Check explorer for the returned hash.">
          Test Arc Transfer
        </button>
      </div>
      <div id="status">Ready.</div>
    </div>
    <div class="panel-block">
      <div class="panel-title">Behavior Settings</div>
      <div class="panel-help">These profiles set role doctrine; each agent still gets unique personality DNA.</div>
      <div class="controls-grid">
        <div>
          <label for="behavior-role" title="Choose which role doctrine you are editing.">Role Profile</label>
          <select id="behavior-role" title="Select role behavior profile to view or change.">
            <option value="worker">Worker</option>
            <option value="thief">Thief</option>
            <option value="cop">Cop</option>
            <option value="banker">Banker</option>
            <option value="bank">Bank</option>
          </select>
        </div>
        <div>
          <label for="trait-a"><span id="trait-a-label">Trait A</span> (<span id="trait-a-value">60</span>%)</label>
          <input id="trait-a" type="range" min="0" max="100" step="1" value="60" title="Primary trait value for this role profile." />
        </div>
        <div>
          <label for="trait-b"><span id="trait-b-label">Trait B</span> (<span id="trait-b-value">55</span>%)</label>
          <input id="trait-b" type="range" min="0" max="100" step="1" value="55" title="Secondary trait value for this role profile." />
        </div>
        <div>
          <label for="trait-c"><span id="trait-c-label">Trait C</span> (<span id="trait-c-value">70</span>%)</label>
          <input id="trait-c" type="range" min="0" max="100" step="1" value="70" title="Tertiary trait value for this role profile." />
        </div>
      </div>
      <div class="controls-grid" style="margin-top:8px">
        <button id="load-settings-btn" title="Load current backend settings for this role.">Load Role Profile</button>
        <button id="save-settings-btn" class="btn-accent" title="Save edited trait values to backend and apply role doctrine.">Save Role Profile</button>
      </div>
    </div>
  `;

  const role = root.querySelector("#role");
  const count = root.querySelector("#count");
  const balance = root.querySelector("#balance");
  const tickRate = root.querySelector("#tick-rate");
  const speedMultiplier = root.querySelector("#speed-multiplier");
  const visualPass = root.querySelector("#visual-pass");
  const spawnBtn = root.querySelector("#spawn-btn");
  const stepBtn = root.querySelector("#step-btn");
  const autoBtn = root.querySelector("#auto-btn");
  const syncBtn = root.querySelector("#sync-btn");
  const passBtn = root.querySelector("#pass-btn");
  const soundBtn = root.querySelector("#sound-btn");
  const viewerBtn = root.querySelector("#viewer-btn");
  const exportBtn = root.querySelector("#export-btn");
  const arcProbeBtn = root.querySelector("#arc-probe-btn");
  const status = root.querySelector("#status");
  const behaviorRole = root.querySelector("#behavior-role");
  const traitA = root.querySelector("#trait-a");
  const traitB = root.querySelector("#trait-b");
  const traitC = root.querySelector("#trait-c");
  const traitALabel = root.querySelector("#trait-a-label");
  const traitBLabel = root.querySelector("#trait-b-label");
  const traitCLabel = root.querySelector("#trait-c-label");
  const traitAValue = root.querySelector("#trait-a-value");
  const traitBValue = root.querySelector("#trait-b-value");
  const traitCValue = root.querySelector("#trait-c-value");
  const loadSettingsBtn = root.querySelector("#load-settings-btn");
  const saveSettingsBtn = root.querySelector("#save-settings-btn");

  let autoMode = false;
  let soundMode = false;
  let viewerMode = "night";
  let cachedBehavior = {};

  const roleTraits = {
    worker: ["effort", "efficiency", "reliability"],
    thief: ["aggression", "bank_bias", "stealth"],
    cop: ["api_reliance", "persistence", "decisiveness"],
    banker: ["strictness", "liquidity_bias", "generosity"],
    bank: ["security", "fee_rate", "reserve_bias"],
  };
  const traitDescriptions = {
    effort: "How hard workers push each cycle.",
    efficiency: "How effectively effort converts into earnings.",
    reliability: "How consistently workers act each loop.",
    aggression: "How frequently thieves attempt theft.",
    bank_bias: "Preference for robbing banks over agents.",
    stealth: "How hidden thief actions are from enforcement.",
    api_reliance: "How often cops buy API intelligence.",
    persistence: "How long cops sustain pursuit pressure.",
    decisiveness: "How quickly cops commit to action.",
    strictness: "How heavily bankers enforce economic controls.",
    liquidity_bias: "How strongly bankers preserve reserves.",
    generosity: "How often bankers reward productive workers.",
    security: "Bank defensive posture against theft pressure.",
    fee_rate: "Base fee intensity in bank policy.",
    reserve_bias: "How much value bank keeps as reserves.",
  };

  function setStatus(message, type = "info") {
    status.textContent = message;
    status.className = "";
    if (type === "ok") {
      status.classList.add("ok");
    } else if (type === "bad") {
      status.classList.add("bad");
    } else if (type === "warn") {
      status.classList.add("warn");
    }
  }

  function renderTraitLabels(role) {
    const [a, b, c] = roleTraits[role] || ["trait_a", "trait_b", "trait_c"];
    traitALabel.textContent = a;
    traitBLabel.textContent = b;
    traitCLabel.textContent = c;
    traitA.title = traitDescriptions[a] || "Trait slider";
    traitB.title = traitDescriptions[b] || "Trait slider";
    traitC.title = traitDescriptions[c] || "Trait slider";
  }

  function loadRoleIntoSliders(role) {
    renderTraitLabels(role);
    const roleSettings = cachedBehavior[role] || {};
    const [a, b, c] = roleTraits[role] || [];
    traitA.value = Math.round((Number(roleSettings[a] ?? 0.6)) * 100);
    traitB.value = Math.round((Number(roleSettings[b] ?? 0.55)) * 100);
    traitC.value = Math.round((Number(roleSettings[c] ?? 0.7)) * 100);
    traitAValue.textContent = String(traitA.value);
    traitBValue.textContent = String(traitB.value);
    traitCValue.textContent = String(traitC.value);
  }

  function sliderPayloadForRole(role) {
    const [a, b, c] = roleTraits[role] || [];
    if (!a || !b || !c) return {};
    return {
      [role]: {
        [a]: Number(traitA.value) / 100,
        [b]: Number(traitB.value) / 100,
        [c]: Number(traitC.value) / 100,
      },
    };
  }

  spawnBtn.addEventListener("click", async () => {
    const desiredRole = role.value;
    const desiredCount = Math.max(1, Number(count.value || 1));
    const startBalance = Number(balance.value || 0);
    try {
      spawnBtn.disabled = true;
      setStatus(`Spawning ${desiredCount} ${desiredRole}(s)...`);
      await handlers.onSpawn(desiredRole, desiredCount, startBalance);
      setStatus(`Spawned ${desiredCount} ${desiredRole}(s).`, "ok");
    } catch (error) {
      setStatus(`Spawn failed: ${error.message}`, "bad");
    } finally {
      spawnBtn.disabled = false;
    }
  });

  stepBtn.addEventListener("click", async () => {
    try {
      stepBtn.disabled = true;
      await handlers.onStep();
      setStatus("Step complete.", "ok");
    } catch (error) {
      setStatus(`Step failed: ${error.message}`, "bad");
    } finally {
      stepBtn.disabled = false;
    }
  });

  autoBtn.addEventListener("click", async () => {
    autoMode = !autoMode;
    autoBtn.textContent = autoMode ? "Stop Auto" : "Start Auto";
    handlers.onAutoToggle(autoMode, Math.max(250, Number(tickRate.value || 1500)));
    setStatus(autoMode ? "Auto mode running." : "Auto mode stopped.", autoMode ? "warn" : "ok");
  });

  arcProbeBtn.addEventListener("click", async () => {
    if (!handlers.onArcProbe) return;
    try {
      arcProbeBtn.disabled = true;
      setStatus("Probing Arc (USDC)…", "warn");
      const res = await handlers.onArcProbe();
      const hash = res && res.tx_hash != null ? String(res.tx_hash) : "";
      const real = Boolean(res && res.is_real_hash);
      if (real && hash.startsWith("0x")) {
        setStatus(`Arc probe: REAL tx ${hash.slice(0, 18)}…`, "ok");
      } else if (hash) {
        setStatus(`Arc probe: no on-chain hash (sim / fallback): ${hash.slice(0, 48)}`, "warn");
      } else {
        setStatus("Arc probe: empty response — check backend logs.", "bad");
      }
    } catch (error) {
      setStatus(`Arc probe failed: ${error.message}`, "bad");
    } finally {
      arcProbeBtn.disabled = false;
    }
  });

  syncBtn.addEventListener("click", async () => {
    try {
      await handlers.onSync();
      setStatus("State refreshed.", "ok");
    } catch (error) {
      setStatus(`Refresh failed: ${error.message}`, "bad");
    }
  });

  passBtn.addEventListener("click", () => {
    handlers.onPassChange(visualPass.value);
    setStatus(`Visual pass switched to ${visualPass.options[visualPass.selectedIndex].text}.`, "ok");
  });

  soundBtn.addEventListener("click", async () => {
    soundMode = !soundMode;
    soundBtn.textContent = soundMode ? "Sound On" : "Sound Off";
    try {
      await handlers.onSoundToggle(soundMode);
      setStatus(soundMode ? "Sound enabled." : "Sound disabled.", soundMode ? "ok" : "warn");
    } catch (error) {
      soundMode = false;
      soundBtn.textContent = "Sound Off";
      setStatus(`Sound failed: ${error.message}`, "bad");
    }
  });

  viewerBtn.addEventListener("click", () => {
    viewerMode = viewerMode === "night" ? "day" : "night";
    viewerBtn.textContent = viewerMode === "day" ? "Viewer: Day" : "Viewer: Night";
    handlers.onViewerToggle(viewerMode);
    setStatus(`Viewer mode set to ${viewerMode}.`, "ok");
  });

  exportBtn.addEventListener("click", async () => {
    try {
      await handlers.onExportReplay();
      setStatus("Replay exported.", "ok");
    } catch (error) {
      setStatus(`Replay export failed: ${error.message}`, "bad");
    }
  });

  tickRate.addEventListener("change", () => {
    if (autoMode) {
      handlers.onAutoToggle(true, Math.max(250, Number(tickRate.value || 1500)));
      setStatus(`Auto interval updated to ${tickRate.value} ms.`, "warn");
    }
  });

  speedMultiplier.addEventListener("change", () => {
    const speed = Math.max(1, Number(speedMultiplier.value || 1));
    handlers.onSpeedChange(speed, Math.max(250, Number(tickRate.value || 1500)));
    setStatus(`Speed set to ${speed}x.`, speed > 1 ? "warn" : "ok");
  });

  behaviorRole.addEventListener("change", () => {
    loadRoleIntoSliders(behaviorRole.value);
  });

  [traitA, traitB, traitC].forEach((slider, idx) => {
    slider.addEventListener("input", () => {
      const labels = [traitAValue, traitBValue, traitCValue];
      labels[idx].textContent = String(slider.value);
    });
  });

  loadSettingsBtn.addEventListener("click", async () => {
    try {
      cachedBehavior = await handlers.onLoadBehaviorSettings();
      loadRoleIntoSliders(behaviorRole.value);
      setStatus(`Loaded profile for ${behaviorRole.value}.`, "ok");
    } catch (error) {
      setStatus(`Load profile failed: ${error.message}`, "bad");
    }
  });

  saveSettingsBtn.addEventListener("click", async () => {
    try {
      const role = behaviorRole.value;
      const payload = sliderPayloadForRole(role);
      cachedBehavior = await handlers.onSaveBehaviorSettings(payload);
      loadRoleIntoSliders(role);
      setStatus(`Saved ${role} profile. New agents will use this doctrine.`, "ok");
    } catch (error) {
      setStatus(`Save profile failed: ${error.message}`, "bad");
    }
  });

  handlers
    .onLoadBehaviorSettings()
    .then((settings) => {
      cachedBehavior = settings || {};
      loadRoleIntoSliders(behaviorRole.value);
    })
    .catch(() => {
      loadRoleIntoSliders(behaviorRole.value);
    });

  return { setStatus };
}
