const API_BASE = "/api";

async function parseResponse(res) {
  const text = await res.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!res.ok) {
    const detail = payload.detail || payload.message || JSON.stringify(payload);
    throw new Error(detail);
  }
  return payload;
}

export async function getState() {
  const res = await fetch(`${API_BASE}/state`);
  return parseResponse(res);
}

export async function getSmallvilleFrame(limitEvents = 250) {
  const query = new URLSearchParams();
  query.set("limit_events", String(limitEvents));
  const res = await fetch(`${API_BASE}/bridge/smallville?${query.toString()}`);
  return parseResponse(res);
}

export async function getEvents() {
  const res = await fetch(`${API_BASE}/events`);
  return parseResponse(res);
}

export async function getTxDiagnostics() {
  const res = await fetch(`${API_BASE}/tx/diagnostics`);
  return parseResponse(res);
}

/** Small USDC transfer via Circle dev wallets — proves Arc path (uses test amount). */
export async function probeArcTransaction(amount = 0.001) {
  const q = new URLSearchParams();
  q.set("amount", String(amount));
  const res = await fetch(`${API_BASE}/tx/probe?${q.toString()}`, { method: "POST" });
  return parseResponse(res);
}

export async function getActionLogs(limit = 200, afterSeq = null) {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  if (afterSeq !== null && afterSeq !== undefined) {
    query.set("after_seq", String(afterSeq));
  }
  const res = await fetch(`${API_BASE}/logs?${query.toString()}`);
  return parseResponse(res);
}

export async function getActionLogStats() {
  const res = await fetch(`${API_BASE}/logs/stats`);
  return parseResponse(res);
}

export async function stepSimulation() {
  const res = await fetch(`${API_BASE}/step`, { method: "POST" });
  return parseResponse(res);
}

export async function getSpawnTypes() {
  const res = await fetch(`${API_BASE}/spawn/types`);
  return parseResponse(res);
}

export async function spawnAgent(entityType, options = {}) {
  const query = new URLSearchParams();
  query.set("entity_type", entityType);
  if (options.entityId) {
    query.set("entity_id", options.entityId);
  }
  if (typeof options.balance === "number") {
    query.set("balance", String(options.balance));
  }
  const res = await fetch(`${API_BASE}/spawn?${query.toString()}`, { method: "POST" });
  return parseResponse(res);
}

export async function getBehaviorSettings() {
  const res = await fetch(`${API_BASE}/settings`);
  return parseResponse(res);
}

export async function updateBehaviorSettings(settings) {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return parseResponse(res);
}

// Final demo pass: surface the already-built economy + action layer to the UI.

/** Live economy health + invariants. See /api/economy/health. */
export async function getEconomyHealth() {
  const res = await fetch(`${API_BASE}/economy/health`);
  return parseResponse(res);
}

/** Compact { entity_id: human_action_label } map. See /api/agents/current. */
export async function getAgentsCurrent() {
  const res = await fetch(`${API_BASE}/agents/current`);
  return parseResponse(res);
}

/** Total ledger-moving transactions count. See /api/transactions/count. */
export async function getTransactionsCount() {
  const res = await fetch(`${API_BASE}/transactions/count`);
  return parseResponse(res);
}
