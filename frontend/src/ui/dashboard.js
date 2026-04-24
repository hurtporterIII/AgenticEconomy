function metricClass(value, lowGood = true) {
  if (lowGood) {
    if (value <= 0.01) return "ok";
    if (value <= 0.03) return "warn";
    return "bad";
  }
  if (value >= 0.6) return "ok";
  if (value >= 0.3) return "warn";
  return "bad";
}

console.log("🔥 DASHBOARD RENDER ACTIVE");

const NAME_POOLS = {
  worker: ["Nyx Vale", "Orin Kade", "Lyra Voss", "Tarek Sol", "Mira Quin"],
  thief: ["Raze Korr", "Vex Hollow", "Kael Strix"],
  cop: ["Arden Pike", "Juno Hal", "Cass Rook"],
  spy: ["Cipher Lux"],
  banker: ["Helix Morn"],
  bank: ["Reserve Node"],
};

function hashId(input) {
  let hash = 0;
  for (let i = 0; i < String(input || "").length; i += 1) {
    hash = ((hash << 5) - hash) + String(input).charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function roleKey(entity) {
  const persona = String(entity?.persona_role || "").toLowerCase();
  if (persona === "spy") return "spy";
  return String(entity?.type || "worker").toLowerCase();
}

function entityDisplayName(entity) {
  const key = roleKey(entity);
  const pool = NAME_POOLS[key] || NAME_POOLS.worker;
  const suffix = String(entity?.id || "").match(/_(\d+)$/);
  const idx = suffix ? (Math.max(1, Number(suffix[1])) - 1) % pool.length : hashId(entity?.id || key) % pool.length;
  return pool[idx] || `${key}_agent`;
}

function humanizeAction(action) {
  if (!action) return "Idle";
  return String(action)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function classifyFlowEvent(event, entityId) {
  const type = String(event?.type || "");
  const n = (v) => Number(v || 0);
  if (type === "worker_earn" && event.worker_id === entityId) return { key: "earn", amount: Math.abs(n(event.amount)) };
  if (type === "worker_bank_deposit" && event.worker_id === entityId) return { key: "deposit", amount: -Math.abs(n(event.amount)) };
  if ((type === "worker_home_store" || type === "worker_stash") && event.worker_id === entityId) return { key: "store", amount: Math.abs(n(event.amount)) };
  if (type === "steal_agent") {
    if (event.thief_id === entityId) return { key: "steal", amount: Math.abs(n(event.amount)) };
    if (event.target_id === entityId || event.worker_id === entityId) return { key: "robbed", amount: -Math.abs(n(event.amount)) };
  }
  if (type === "cop_recover") {
    if (event.cop_id === entityId) return { key: "recover", amount: Math.abs(n(event.amount)) };
    if (event.thief_id === entityId) return { key: "lost", amount: -Math.abs(n(event.amount)) };
  }
  if (type === "spy_sell_info") {
    const price = Math.abs(n(event.price || event.amount || 0.000005));
    if (event.buyer_id === entityId) return { key: "intel_payment", amount: -price };
    if (event.spy_id === entityId) return { key: "intel_sale", amount: price };
  }
  if (type === "redistribution" && event.cop_id === entityId) {
    const kept = Math.abs(n(event.cop_amount || event.kept_amount || 0));
    if (kept > 0) return { key: "kept", amount: kept };
  }
  return null;
}

function formatMoneySigned(value) {
  const v = Number(value || 0);
  const sign = v >= 0 ? "+" : "-";
  return `${sign}${Math.abs(v).toFixed(6)}`;
}

function buildFlowSummary(entityId, recentEvents) {
  const totals = {
    earn: 0, deposit: 0, store: 0, robbed: 0, steal: 0,
    recover: 0, intel_payment: 0, intel_sale: 0, lost: 0, kept: 0,
  };
  for (const event of recentEvents) {
    const row = classifyFlowEvent(event, entityId);
    if (!row) continue;
    totals[row.key] += Number(row.amount || 0);
  }
  const order = [
    ["earn", "Worked"],
    ["deposit", "Deposited"],
    ["store", "Stored"],
    ["robbed", "Robbed"],
    ["intel_payment", "Bought intel"],
    ["steal", "Stole"],
    ["recover", "Recovered"],
    ["lost", "Lost"],
    ["kept", "Kept"],
    ["intel_sale", "Sold intel"],
  ];
  const parts = order
    .filter(([key]) => Math.abs(totals[key]) > 0)
    .map(([key, label]) => `${label} ${formatMoneySigned(totals[key])}`);
  return {
    line: parts.length ? parts.join(" -> ") : "No recent financial flow",
    totals,
  };
}

export function initDashboard(root) {
  root.innerHTML = `
    <div class="panel-block">
      <div class="panel-title">Live Nano-Economy</div>
      <div class="panel-help">Aggregate counters from /api/economy/health. Transactions is every ledger-moving debit/credit.</div>
      <div id="nano-summary" class="nano-summary">
        <div class="nano-cell nano-cell--primary">
          <div class="nano-label">Transactions</div>
          <div class="nano-value" id="nano-tx-count">0</div>
          <div class="nano-sub" id="nano-health">awaiting data</div>
        </div>
        <div class="nano-cell">
          <div class="nano-label">Intel sold</div>
          <div class="nano-value" id="nano-intel">0</div>
        </div>
        <div class="nano-cell">
          <div class="nano-label">Thefts</div>
          <div class="nano-value" id="nano-theft">0</div>
        </div>
        <div class="nano-cell">
          <div class="nano-label">Recoveries</div>
          <div class="nano-value" id="nano-recov">0</div>
        </div>
      </div>
    </div>
    <div class="panel-block">
      <div class="panel-title">City Narrative</div>
      <div class="panel-help">Story feed that translates raw events into plain language.</div>
      <div id="story-ticker"></div>
    </div>
    <div class="panel-block">
      <div class="panel-title">Economy Phase</div>
      <div class="panel-help">Current macro regime and why it is active.</div>
      <div id="phase-card" class="phase-card">
        <div id="phase-title" class="phase-title">Bootstrapping</div>
        <div id="phase-note" class="phase-note">Waiting for enough activity.</div>
      </div>
    </div>
    <div class="panel-block">
      <div class="panel-title">Population Guide</div>
      <div class="panel-help">Recommended role mix to move toward a stable economy.</div>
      <div id="guide-notes"></div>
    </div>
    <div class="panel-block">
      <div class="panel-title">Economy Metrics</div>
      <div class="panel-help">On-chain Arc/Circle counters: successful_tx / total_spent count completed real transfers, not every in-sim debit. cost_per_action is average USDC per successful on-chain submit.</div>
      <div class="metric-grid" id="metric-grid"></div>
    </div>
    <div class="panel-block">
      <div class="panel-title">Entity Bars</div>
      <div class="panel-help">Per-agent balance bars and current intent line.</div>
      <div id="entity-bars"></div>
    </div>
    <div class="panel-block" style="min-height:0">
      <div class="panel-title">Live Events</div>
      <div class="panel-help">Most recent raw events from the simulation engine.</div>
      <div id="event-feed"></div>
    </div>
    <div class="panel-block" style="min-height:0">
      <div class="panel-title">Action Trace</div>
      <div class="panel-help">Persistent backend action log stream with sequence IDs.</div>
      <div id="trace-stats"></div>
      <div id="trace-feed"></div>
    </div>
  `;

  const metricGrid = root.querySelector("#metric-grid");
  const entityBars = root.querySelector("#entity-bars");
  const eventFeed = root.querySelector("#event-feed");
  const storyTicker = root.querySelector("#story-ticker");
  const traceStats = root.querySelector("#trace-stats");
  const traceFeed = root.querySelector("#trace-feed");
  const phaseCard = root.querySelector("#phase-card");
  const phaseTitle = root.querySelector("#phase-title");
  const phaseNote = root.querySelector("#phase-note");
  const guideNotes = root.querySelector("#guide-notes");
  const nanoTxCount = root.querySelector("#nano-tx-count");
  const nanoHealth = root.querySelector("#nano-health");
  const nanoIntel = root.querySelector("#nano-intel");
  const nanoTheft = root.querySelector("#nano-theft");
  const nanoRecov = root.querySelector("#nano-recov");
  const storyLines = [];
  const feedEntries = [];
  const traceEntries = [];
  const recentEconomicEvents = [];
  const counters = {
    workerEarn: 0,
    stealAgent: 0,
    stealBank: 0,
    apiCall: 0,
    copChase: 0,
  };

  function narrativeLine(event) {
    if (event.type === "regime_shift") return `Regime shift: ${event.regime} - ${event.narration || "economic pressure changed."}`;
    if (event.type === "economic_guidance") return `Guidance update: stability ${event.stability_score ?? "n/a"} / 100.`;
    if (event.type === "worker_earn") return `${event.worker_id || "worker"} extracted value and got paid.`;
    if (event.type === "worker_commute_bank") return `${event.worker_id || "worker"} is heading to the bank (B12).`;
    if (event.type === "worker_commute_home") return `${event.worker_id || "worker"} is heading home (B08).`;
    if (event.type === "worker_bank_deposit")
      return `${event.worker_id || "worker"} deposited ${Number(event.amount || 0).toFixed(3)} USDC at the bank.`;
    if (event.type === "steal_bank") return `${event.thief_id || "thief"} hit the central vault.`;
    if (event.type === "steal_agent") return `${event.thief_id || "thief"} robbed ${event.target_id || event.worker_id || "an agent"}.`;
    if (event.type === "cop_chase") return `${event.cop_id || "cop"} is pursuing ${event.target_id || "a target"}.`;
    // Info-driven nano-economy events: spy brokers intel, cop recovers stolen funds.
    if (event.type === "spy_sell_info") {
      const buyer = event.buyer_type || event.buyer_id || "agent";
      return `Spy sold intel to ${buyer}.`;
    }
    if (event.type === "cop_recover") {
      return `${event.cop_id || "cop"} recovered funds from ${event.thief_id || "thief"}.`;
    }
    if (event.type === "spy_intel_created") {
      return `Spy spotted stash at ${event.target_worker || "worker"}.`;
    }
    if (event.type === "api_call") return `${event.agent || "agent"} paid for intelligence.`;
    if (event.type === "ai_decision") return `AI selected ${event.target || event.thief_id || "a target"} via ${event.provider || "fallback"}.`;
    return `${event.type} executed.`;
  }

  function computePhase({ successful, failed, costPerAction, entities }) {
    const totalActions = counters.workerEarn + counters.stealAgent + counters.stealBank + counters.apiCall;
    const theftPressure = counters.stealAgent + counters.stealBank * 2;
    const enforcement = counters.copChase;
    const failureRate = (successful + failed) > 0 ? failed / (successful + failed) : 0;

    if (entities < 4 || totalActions < 6) {
      return { key: "boot", title: "Bootstrapping", note: "Population and market activity are still ramping." };
    }
    if (theftPressure > counters.workerEarn + 3 && enforcement < theftPressure * 0.6) {
      return { key: "crime", title: "Crime Spike", note: "Theft volume is outpacing productive value creation." };
    }
    if (failureRate > 0.72 || (costPerAction > 0.008 && failed > successful)) {
      return { key: "stress", title: "Bank Stress", note: "Settlement friction is high; invalid or failed tx is dominant." };
    }
    if (successful >= 10 && costPerAction <= 0.01 && enforcement >= counters.stealBank) {
      return { key: "stable", title: "City Stable", note: "Productive flow and enforcement are in healthy balance." };
    }
    return { key: "flux", title: "Market Flux", note: "The economy is active but still oscillating between risk and growth." };
  }

  function update(snapshot, newEvents, storyMap = {}, traceSnapshot = {}, demoLive = {}) {
    // Final demo pass: live nano-economy counters from /api/economy/health.
    // If the endpoint is unreachable we leave the existing DOM numbers
    // alone so the panel doesn't flash "0" during a transient fetch error.
    const health = demoLive?.health;
    if (health && typeof health === "object") {
      const txCount = Number(health.total_transactions || 0);
      nanoTxCount.textContent = txCount.toLocaleString();
      const isHealthy = Boolean(health.healthy);
      nanoHealth.textContent = isHealthy
        ? "economy invariants: OK"
        : "invariant drift detected";
      nanoHealth.className = isHealthy ? "nano-sub nano-sub--ok" : "nano-sub nano-sub--warn";
      nanoIntel.textContent = Number(health.intel_sold_count ?? health.intel_count ?? 0).toLocaleString();
      nanoTheft.textContent = Number(health.theft_count || 0).toLocaleString();
      nanoRecov.textContent = Number(health.recovery_count || 0).toLocaleString();
    }

    const metrics = snapshot.metrics || {};
    const totalSpent = Number(metrics.total_spent || 0);
    const successful = Number(metrics.successful_tx || 0);
    const failed = Number(metrics.failed_tx || 0);
    const costPerAction = Number(metrics.cost_per_action || 0);
    const successRate = Number(metrics.success_rate || 0);
    const entitiesTotal = Object.keys(snapshot.entities || {}).length;
    const economy = snapshot.economy || {};

    if (newEvents?.length) {
      newEvents.forEach((event) => {
        if (event.type === "worker_earn") counters.workerEarn += 1;
        if (event.type === "steal_agent") counters.stealAgent += 1;
        if (event.type === "steal_bank") counters.stealBank += 1;
        if (event.type === "api_call") counters.apiCall += 1;
        if (event.type === "cop_chase") counters.copChase += 1;
        storyLines.unshift(narrativeLine(event));
        recentEconomicEvents.push(event);
      });
      if (recentEconomicEvents.length > 400) {
        recentEconomicEvents.splice(0, recentEconomicEvents.length - 400);
      }
      if (storyLines.length > 18) {
        storyLines.length = 18;
      }
      storyTicker.innerHTML = storyLines
        .slice(0, 8)
        .map((line) => `<div class="story-item" title="${line.replace(/"/g, "&quot;")}">${line}</div>`)
        .join("");
    }

    const phase = economy.regime
      ? {
        key:
            economy.regime === "police_state"
              ? "police"
              : economy.regime === "decline"
                ? "crime"
                : economy.regime === "growth"
                  ? "stable"
                  : economy.regime === "bootstrapping"
                    ? "boot"
                    : "flux",
        title: String(economy.regime || "balanced").replaceAll("_", " ").toUpperCase(),
        note: economy.narration || "Macro economy policy active.",
      }
      : computePhase({
        successful,
        failed,
        costPerAction,
        entities: entitiesTotal,
      });
    phaseTitle.textContent = phase.title;
    phaseNote.textContent = phase.note;
    phaseCard.className = `phase-card ${phase.key}`;

    const guidance = economy.guidance || {};
    const notes = Array.isArray(guidance.notes) ? guidance.notes : [];
    const counts = guidance.recommended_counts || {};
    guideNotes.innerHTML = `
      <div class="guide-line" title="Higher is healthier population balance."><b>Stability:</b> ${Number(economy.stability_score || 0).toFixed(1)} / 100</div>
      <div class="guide-line" title="Recommended counts based on current total active population."><b>Target mix:</b> W ${counts.worker ?? "-"} | C ${counts.cop ?? "-"} | T ${counts.thief ?? "-"} | B ${counts.banker ?? "-"}</div>
      ${notes.slice(0, 3).map((line) => `<div class="guide-line" title="${line.replace(/"/g, "&quot;")}">${line}</div>`).join("")}
    `;

    metricGrid.innerHTML = `
      <div class="metric" title="Total economic spend tracked by the simulation.">
        <div class="metric-label">Total Spent</div>
        <div class="metric-value">$${totalSpent.toFixed(4)}</div>
      </div>
      <div class="metric" title="Count of successful settlement attempts.">
        <div class="metric-label">Successful TX</div>
        <div class="metric-value ok">${successful}</div>
      </div>
      <div class="metric" title="Count of failed settlement attempts.">
        <div class="metric-label">Failed TX</div>
        <div class="metric-value bad">${failed}</div>
      </div>
      <div class="metric" title="Average spend per successful action. Lower is better.">
        <div class="metric-label">Cost / Action</div>
        <div class="metric-value ${metricClass(costPerAction, true)}">$${costPerAction.toFixed(4)}</div>
      </div>
      <div class="metric" title="Successful transactions divided by all attempts.">
        <div class="metric-label">Success Rate</div>
        <div class="metric-value ${metricClass(successRate, false)}">${(successRate * 100).toFixed(1)}%</div>
      </div>
      <div class="metric" title="Current number of entities in simulation state.">
        <div class="metric-label">Total Agents</div>
        <div class="metric-value">${entitiesTotal}</div>
      </div>
    `;

    const entities = Object.values(snapshot.entities || {})
      .filter((entity) => String(entity?.persona_role || entity?.type || "").toLowerCase() !== "bank")
      .sort((a, b) => a.id.localeCompare(b.id));
    const balances = snapshot.balances || {};
    const maxBalance = Math.max(
      1,
      ...entities.map((entity) => Number(balances[entity.id] ?? 0)),
    );

    const liveActions = demoLive?.currentActions || {};
    entityBars.innerHTML = entities
      .map((entity) => {
        const balance = Number(balances[entity.id] ?? 0);
        const pct = Math.max(0, Math.min(100, (balance / maxBalance) * 100));
        const story = storyMap[entity.id]?.line || "Awaiting next action";
        const liveLabel = liveActions[entity.id] || "idle";
        const badge = liveLabel
          ? `<span class="entity-chip" title="Backend current_action (PASS 4)">${String(liveLabel).replaceAll("_", " ")}</span>`
          : "";
        const displayName = entityDisplayName(entity);
        const displayRole = roleKey(entity);
        const flow = buildFlowSummary(entity.id, recentEconomicEvents.slice(-160));
        const homeStorage = Number(entity.home_storage || 0);
        const x = Math.round(Number(entity.x || 0));
        const y = Math.round(Number(entity.y || 0));
        const tx = Math.round(Number(entity.target_x ?? entity.x ?? 0));
        const ty = Math.round(Number(entity.target_y ?? entity.y ?? 0));
        const extra =
          displayRole === "worker"
            ? `<div class="entity-section"><strong>Storage:</strong> ${homeStorage.toFixed(6)}</div>`
            : displayRole === "cop"
              ? `<div class="entity-section"><strong>Recovered:</strong> ${Math.max(0, Number(flow.totals.recover || 0)).toFixed(6)}</div>`
              : displayRole === "thief"
                ? `<div class="entity-section"><strong>Stolen:</strong> ${Math.max(0, Number(flow.totals.steal || 0)).toFixed(6)}</div>`
                : "";
        return `
          <div class="entity-row" data-entity-id="${entity.id}" title="${entity.id} (${entity.type}) balance ${balance.toFixed(6)}">
            <div class="entity-header">
              <span>${displayName} (${displayRole})</span>
              <span>${balance.toFixed(6)}</span>
            </div>
            <div class="bar-track" title="Relative balance level versus richest entity in current view."><div class="bar-fill" style="width:${pct}%"></div></div>
            <div class="entity-section"><strong>Flow:</strong> ${flow.line}</div>
            <div class="entity-section"><strong>Action:</strong> ${humanizeAction(liveLabel)}</div>
            <div class="entity-section"><strong>Location:</strong> (${x}, ${y}) -> (${tx}, ${ty})</div>
            ${extra}
            <div class="entity-story" title="${story.replace(/"/g, "&quot;")}">${story}</div>
            ${badge}
          </div>
        `;
      })
      .join("");

    if (newEvents?.length) {
      const latest = newEvents
        .filter((event) => !["debit", "credit"].includes(event.type))
        .slice(-12)
        .reverse();
      const html = latest
        .map((event) => {
          const details = Object.entries(event)
            .filter(([key]) => key !== "type")
            .slice(0, 3)
            .map(([key, value]) => `${key}:${String(value).slice(0, 18)}`)
            .join(" | ");
          const title = `${event.type}${details ? ` | ${details}` : ""}`.replace(/"/g, "&quot;");
          return `<div class="event-item" title="${title}"><b>${event.type}</b><br>${details}</div>`;
        })
        .filter(Boolean);
      feedEntries.unshift(...html);
      if (feedEntries.length > 120) {
        feedEntries.length = 120;
      }
      eventFeed.innerHTML = feedEntries.join("");
    }

    const traceRows = Array.isArray(traceSnapshot.rows) ? traceSnapshot.rows : [];
    const stats = traceSnapshot.stats || {};
    if (traceRows.length) {
      const html = traceRows
        .slice(-40)
        .reverse()
        .map((row) => {
          const seq = row?._seq ?? "-";
          const type = row?.type || "event";
          const ts = String(row?._ts || "").replace("T", " ").slice(0, 19);
          const details = Object.entries(row || {})
            .filter(([key]) => !["_seq", "_ts", "_ts_epoch", "_session", "type"].includes(key))
            .slice(0, 3)
            .map(([key, value]) => `${key}:${String(value).slice(0, 18)}`)
            .join(" | ");
          return `<div class="event-item" title="${type} #${seq} ${details}"><b>#${seq} ${type}</b><br>${ts}${details ? ` | ${details}` : ""}</div>`;
        });
      traceEntries.unshift(...html);
      if (traceEntries.length > 150) {
        traceEntries.length = 150;
      }
      traceFeed.innerHTML = traceEntries.join("");
    }

    const sizeKb = Number(stats.size_bytes || 0) / 1024;
    traceStats.innerHTML = `
      <div class="guide-line" title="Backend action log file path."><b>Log File:</b> ${stats.path || "-"}</div>
      <div class="guide-line" title="Total persisted rows written this run."><b>Rows Written:</b> ${Number(stats.total_written || 0)}</div>
      <div class="guide-line" title="Current in-memory event buffer size."><b>Memory Buffer:</b> ${Number(stats.memory_events || 0)}</div>
      <div class="guide-line" title="Persisted action log file size on disk."><b>Disk Size:</b> ${sizeKb.toFixed(1)} KB</div>
    `;
  }

  /**
   * Lightweight refresh used by the 300ms demo poll. Only touches the
   * nano-economy summary panel so judges see transaction count tick in
   * real time without paying for a full /state + logs re-fetch.
   */
  function updateLive({ health, currentActions } = {}) {
    if (health && typeof health === "object") {
      const txCount = Number(health.total_transactions || 0);
      nanoTxCount.textContent = txCount.toLocaleString();
      const isHealthy = Boolean(health.healthy);
      nanoHealth.textContent = isHealthy
        ? "economy invariants: OK"
        : "invariant drift detected";
      nanoHealth.className = isHealthy ? "nano-sub nano-sub--ok" : "nano-sub nano-sub--warn";
      nanoIntel.textContent = Number(health.intel_sold_count ?? health.intel_count ?? 0).toLocaleString();
      nanoTheft.textContent = Number(health.theft_count || 0).toLocaleString();
      nanoRecov.textContent = Number(health.recovery_count || 0).toLocaleString();
    }
    // Refresh the chip on each entity row in-place without rebuilding the
    // whole list (keeps scroll position and avoids layout thrash).
    if (currentActions && typeof currentActions === "object") {
      const rows = entityBars.querySelectorAll(".entity-row");
      rows.forEach((row) => {
        const id = row.getAttribute("data-entity-id");
        if (!id) return;
        const label = currentActions[id] || "idle";
        let chip = row.querySelector(".entity-chip");
        if (!chip) {
          chip = document.createElement("span");
          chip.className = "entity-chip";
          chip.title = "Backend current_action (PASS 4)";
          row.appendChild(chip);
        }
        chip.textContent = String(label).replaceAll("_", " ");
      });
    }
  }

  return { update, updateLive };
}
