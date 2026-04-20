const API_BASE = "http://localhost:8000/api";

export async function fetchSnapshot() {
  const res = await fetch(`${API_BASE}/snapshot`);
  return res.json();
}

export async function runTick() {
  const res = await fetch(`${API_BASE}/tick`, { method: "POST" });
  return res.json();
}
