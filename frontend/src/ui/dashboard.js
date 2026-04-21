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

export function initDashboard(root) {
  root.innerHTML = `
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
      <div class="panel-help">Settlement cost, throughput, and reliability indicators.</div>
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
  const storyLines = [];
  const feedEntries = [];
  const traceEntries = [];
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
    if (event.type === "steal_bank") return `${event.thief_id || "thief"} hit the central vault.`;
    if (event.type === "steal_agent") return `${event.thief_id || "thief"} robbed ${event.target_id || "an agent"}.`;
    if (event.type === "cop_chase") return `${event.cop_id || "cop"} is pursuing ${event.target_id || "a target"}.`;
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

  function update(snapshot, newEvents, storyMap = {}, traceSnapshot = {}) {
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
      });
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

    const entities = Object.values(snapshot.entities || {}).sort((a, b) => a.id.localeCompare(b.id));
    const balances = snapshot.balances || {};
    const maxBalance = Math.max(
      1,
      ...entities.map((entity) => Number(balances[entity.id] ?? 0)),
    );

    entityBars.innerHTML = entities
      .map((entity) => {
        const balance = Number(balances[entity.id] ?? 0);
        const pct = Math.max(0, Math.min(100, (balance / maxBalance) * 100));
        const story = storyMap[entity.id]?.line || "Awaiting next action";
        return `
          <div class="entity-row" title="${entity.id} (${entity.type}) balance ${balance.toFixed(2)}">
            <div class="entity-header">
              <span>${entity.id} (${entity.type})</span>
              <span>${balance.toFixed(2)}</span>
            </div>
            <div class="bar-track" title="Relative balance level versus richest entity in current view."><div class="bar-fill" style="width:${pct}%"></div></div>
            <div class="entity-story" title="${story.replace(/"/g, "&quot;")}">${story}</div>
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

  return { update };
}
