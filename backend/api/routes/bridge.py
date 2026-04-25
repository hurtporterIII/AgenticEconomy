"""Smallville bridge frame construction and bridge API routes."""

from __future__ import annotations

import math
from pathlib import Path

from fastapi import APIRouter, Query

from core.state import default_economy_state, state_lock
from api.routes.common import (
    BRIDGE_CODE_REVISION,
    ROLE_TO_SMALLVILLE,
    _compute_cop_stats,
    _flow_n,
    _hub_destination,
    _sector_nav_point,
    get_events,
    get_state,
)

bridge_router = APIRouter(tags=["demo"])
_BRIDGE_FRAME_CACHE: dict[tuple[int, int, bool, bool], dict] = {}

def _bridge_roam_goal(
    entity: dict,
    actor_id: str,
    tick: int,
    sectors: list[str],
    label: str,
    hold_ticks: int = 18,
    force_retarget: bool = False,
) -> tuple[str, float, float]:
    """
    Sticky map-wide roaming target for bridge visualization.
    Prevents rapid per-tick retargeting that causes circular jitter.
    """
    if not sectors:
        sx, sy = _sector_nav_point("Johnson Park", actor_id)
        return "Johnson Park", sx, sy

    key_prefix = f"bridge_goal_{label}"
    idx_key = f"{key_prefix}_idx"
    until_key = f"{key_prefix}_until"
    zone_key = f"{key_prefix}_zone"
    x_key = f"{key_prefix}_x"
    y_key = f"{key_prefix}_y"

    idx = int(entity.get(idx_key, sum(ord(ch) for ch in actor_id) % len(sectors)))
    until_tick = int(entity.get(until_key, -1))

    if force_retarget or tick >= until_tick or zone_key not in entity:
        idx = (idx + 1) % len(sectors)
        zone = sectors[idx]
        x, y = _sector_nav_point(zone, actor_id)
        entity[idx_key] = idx
        entity[until_key] = tick + max(6, int(hold_ticks))
        entity[zone_key] = zone
        entity[x_key] = float(x)
        entity[y_key] = float(y)

    return (
        str(entity.get(zone_key)),
        float(entity.get(x_key, 0.0) or 0.0),
        float(entity.get(y_key, 0.0) or 0.0),
    )


def _bridge_stuck_retarget(entity: dict, actor_id: str, action: str, tick: int) -> bool:
    """
    Detect agents that are effectively parked and request a new roam goal.
    Exempts active interaction states to avoid interrupting real actions.
    """
    active_actions = {"chase", "steal", "bank", "scan", "work"}
    if action in active_actions:
        entity["bridge_stuck_count"] = 0
        entity["bridge_stuck_last_tick"] = tick
        entity["bridge_stuck_last_x"] = float(entity.get("x", 0.0) or 0.0)
        entity["bridge_stuck_last_y"] = float(entity.get("y", 0.0) or 0.0)
        return False

    x = float(entity.get("x", 0.0) or 0.0)
    y = float(entity.get("y", 0.0) or 0.0)
    prev_tick = int(entity.get("bridge_stuck_last_tick", tick))
    prev_x = float(entity.get("bridge_stuck_last_x", x) or x)
    prev_y = float(entity.get("bridge_stuck_last_y", y) or y)

    # Ignore duplicate checks inside the same tick.
    if tick == prev_tick:
        return False

    delta = abs(x - prev_x) + abs(y - prev_y)
    stuck_count = int(entity.get("bridge_stuck_count", 0))
    if delta <= 3.0:
        stuck_count += 1
    else:
        stuck_count = 0

    entity["bridge_stuck_count"] = stuck_count
    entity["bridge_stuck_last_tick"] = tick
    entity["bridge_stuck_last_x"] = x
    entity["bridge_stuck_last_y"] = y

    if stuck_count >= 4:
        entity["bridge_stuck_count"] = 0
        return True
    return False


def _resolve_destination(
    shared: dict,
    entity: dict,
    latest_event: dict | None,
    entities: dict,
    tick: int,
) -> tuple[str, float, float]:
    role = str(entity.get("persona_role", entity.get("type", "resident"))).lower()
    action = _infer_actor_action(entity, latest_event)
    entity_id = str(entity.get("id", ""))
    _bridge_stuck_retarget(entity, entity_id, action, tick)

    if role == "worker":
        shift = str(entity.get("worker_shift_phase", "to_mine")).strip() or "to_mine"
        if shift == "to_bank" or action in {"commute_bank", "bank"}:
            return _hub_destination(shared, "bank_home", "Bank", anchor="entry")
        if shift == "to_home" or action in {"return_home", "store_home"}:
            return _hub_destination(shared, "worker_home", "Worker Home", anchor="entry")
        return _hub_destination(shared, "worker_work", "Worker Work", anchor="entry")

    if role == "spy":
        return _hub_destination(shared, "spy_home", "Spy Home", anchor="center")

    if role in {"bank", "banker"}:
        return _hub_destination(shared, "bank_home", "Bank Home", anchor="center")

    if role == "thief":
        target_id = entity.get("target") or (latest_event or {}).get("target_id")
        target = entities.get(target_id) if target_id else None
        if action == "chase" and target:
            return "target", float(target.get("x", 0.0) or 0.0), float(target.get("y", 0.0) or 0.0)
        if action == "steal":
            target = entities.get((latest_event or {}).get("target_id"))
            if target:
                tx = float(target.get("x", 0.0) or 0.0)
                ty = float(target.get("y", 0.0) or 0.0)
                return "target", tx, ty
            return _hub_destination(shared, "thief_home", "Thief Home", anchor="center")
        if action == "bank":
            return _hub_destination(shared, "bank_home", "Bank Home", anchor="center")
        return _hub_destination(shared, "thief_home", "Thief Home", anchor="center")

    if role == "cop":
        target_id = entity.get("target") or (latest_event or {}).get("target_id")
        target = entities.get(target_id) if target_id else None
        if action == "chase" and target:
            return "target", float(target.get("x", 0.0) or 0.0), float(target.get("y", 0.0) or 0.0)
        return _hub_destination(shared, "cop_home", "Cop Home", anchor="center")

    return _hub_destination(shared, "worker_home", "Worker Home", anchor="center")


def _infer_actor_action(entity: dict, latest_event: dict | None) -> str:
    role = str(entity.get("type", "resident"))
    top_action = str(entity.get("top_action", "")).strip().lower()
    event_type = str((latest_event or {}).get("type", ""))
    if role == "cop" and entity.get("target"):
        return "chase"

    if role == "worker":
        shift = str(entity.get("worker_shift_phase", "to_mine")).strip() or "to_mine"
        if shift == "to_bank":
            return "bank"
        if shift == "to_home":
            return "return_home"
        if top_action in {"commute_mine", "work", "return_home", "store_home", "commute_bank"}:
            return top_action
        if event_type == "worker_store_home":
            return "store_home"
        if event_type == "worker_commute_home":
            return "return_home"
        if event_type == "worker_commute_mine":
            return "commute_mine"
        if event_type == "worker_commute_bank":
            return "commute_bank"
        if event_type == "worker_bank_deposit":
            return "bank"
        if event_type == "worker_earn":
            return "work"
        if event_type.startswith("bank_"):
            return "bank"
        return "idle"

    if role == "thief":
        if event_type in {"steal_agent", "steal_bank"}:
            return "steal"
        if event_type == "thief_deposit":
            return "bank"
        if entity.get("target"):
            return "chase"
        return "idle"

    if role == "cop":
        if event_type in {"cop_chase"}:
            return "chase"
        if event_type in {"api_call", "cop_scan"}:
            return "scan"
        return "patrol"

    if role in {"bank", "banker"}:
        if event_type.startswith("bank_") or event_type in {"debit", "credit"}:
            return "bank"
        return "idle"

    if event_type.startswith("bank_") or event_type in {"debit", "credit"}:
        return "bank"
    return "idle"


def _classify_flow_event(entity_id: str, event: dict) -> tuple[str, float] | None:
    """Mirror frontend/src/ui/dashboard.js classifyFlowEvent for bridge/UI parity."""
    et = str(event.get("type") or "")
    n = _flow_n
    eid = str(entity_id).strip()
    if et == "worker_earn" and str(event.get("worker_id", "")).strip() == eid:
        return ("earn", abs(n(event.get("amount"))))
    if et == "bank_fee_nano":
        if str(event.get("worker_id", "")).strip() == eid:
            return ("bank_fee", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("fee_in", abs(n(event.get("amount"))))
    if et == "worker_bank_deposit":
        if str(event.get("worker_id", "")).strip() == eid:
            return ("deposit", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("deposit_in", abs(n(event.get("amount"))))
    if et == "thief_deposit":
        if str(event.get("thief_id", "")).strip() == eid:
            return ("deposit", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("deposit_in", abs(n(event.get("amount"))))
    if et in {"worker_home_store", "worker_stash", "worker_store_home"} and str(
        event.get("worker_id", "")
    ).strip() == eid:
        return ("store", abs(n(event.get("amount"))))
    if et == "steal_agent":
        if str(event.get("thief_id", "")).strip() == eid:
            return ("steal", abs(n(event.get("amount"))))
        if str(event.get("target_id", "")).strip() == eid or str(event.get("worker_id", "")).strip() == eid:
            return ("robbed", -abs(n(event.get("amount"))))
    if et == "cop_recover":
        if str(event.get("cop_id", "")).strip() == eid:
            amt = event.get("amount")
            if amt is None:
                amt = event.get("recovered")
            return ("recover", abs(n(amt)))
        if str(event.get("thief_id", "")).strip() == eid:
            amt = event.get("amount")
            if amt is None:
                amt = event.get("recovered")
            return ("lost", -abs(n(amt)))
    if et == "bank_zone_confiscation":
        amt = event.get("amount")
        if str(event.get("cop_id", "")).strip() == eid:
            return ("confiscate", abs(n(amt)))
        if str(event.get("thief_id", "")).strip() == eid:
            return ("confiscated_loss", -abs(n(amt)))
    if et == "spy_sell_info":
        price = abs(n(event.get("price") or event.get("amount") or 0.000005))
        if str(event.get("buyer_id", "")).strip() == eid:
            return ("intel_payment", -price)
        if str(event.get("spy_id", "")).strip() == eid:
            return ("intel_sale", price)
    if et == "redistribution" and str(event.get("cop_id", "")).strip() == eid:
        kept = abs(n(event.get("cop_amount") or event.get("kept_amount") or event.get("cop_share") or 0.0))
        if kept > 0:
            return ("kept", kept)
    return None


def _format_money_signed(value: float) -> str:
    v = float(value or 0.0)
    sign = "+" if v >= 0 else "-"
    return f"{sign}{abs(v):.6f}"


def _format_money_abs(value: float) -> str:
    return f"{abs(float(value or 0.0)):.6f}"


def _entity_flow_role(entity: dict | None) -> str:
    if not isinstance(entity, dict):
        return "agent"
    pr = str(entity.get("persona_role", "") or "").strip().lower()
    if pr in {"spy"}:
        return "spy"
    t = str(entity.get("type", "") or "").strip().lower()
    if t in {"worker", "thief", "cop", "bank", "banker"}:
        return t
    return pr or t or "agent"


def _flow_segment_final(role: str, key: str, total_signed: float) -> str | None:
    """One clause per bucket; amounts use explicit + / - (STEP 2 verb lock)."""
    v = float(total_signed or 0.0)
    if abs(v) < 1e-21:
        return None
    amt = _format_money_signed(v)
    r = (role or "agent").strip().lower()

    if key == "earn":
        if r != "worker":
            return None
        return f"Earned {amt} at work"

    if key == "bank_fee":
        if r == "worker":
            return f"Lost {amt} to fees"
        return None

    if key == "deposit":
        if r == "worker" or r == "cop":
            return f"Deposited {amt} to bank"
        if r == "thief":
            return f"Paid {amt} to bank"
        return None

    if key == "store" and r == "worker":
        return f"Stored {amt} at home"

    if key == "robbed" and r == "worker":
        return f"Lost {amt} to theft"

    if key == "intel_payment":
        if r in {"thief", "cop"}:
            return f"Paid {amt} for intel"
        if r == "worker":
            return f"Lost {amt} to intel"
        return None

    if key == "intel_sale" and r == "spy":
        return f"Received {amt} for intel"

    if key == "steal" and r == "thief":
        return f"Stole {amt} from worker"

    if key == "recover" and r == "cop":
        return f"Recovered {amt} from thief"

    if key == "lost" and r == "thief":
        return f"Lost {amt} to recovery"

    if key == "kept" and r == "cop":
        return f"Kept {amt} after split"

    if key == "confiscate" and r == "cop":
        return f"Confiscated {amt} from bank robbery"

    if key == "confiscated_loss" and r == "thief":
        return f"Confiscated {amt} after bank robbery"

    if key == "fee_in" and r in {"bank", "banker"}:
        return f"Collected {_format_money_signed(abs(v))} in fees"

    if key == "deposit_in" and r in {"bank", "banker"}:
        return f"Received {_format_money_signed(abs(v))} in deposits"

    return None


def _build_flow_summary_line(entity_id: str, entity: dict | None, recent_events: list) -> str:
    totals = {
        "earn": 0.0,
        "bank_fee": 0.0,
        "deposit": 0.0,
        "store": 0.0,
        "robbed": 0.0,
        "steal": 0.0,
        "recover": 0.0,
        "intel_payment": 0.0,
        "intel_sale": 0.0,
        "lost": 0.0,
        "kept": 0.0,
        "confiscate": 0.0,
        "confiscated_loss": 0.0,
        "fee_in": 0.0,
        "deposit_in": 0.0,
    }
    for ev in recent_events:
        row = _classify_flow_event(entity_id, ev)
        if not row:
            continue
        key, amt = row
        totals[key] = totals.get(key, 0.0) + float(amt or 0.0)
    role = _entity_flow_role(entity)
    order = [
        "earn",
        "bank_fee",
        "deposit",
        "store",
        "robbed",
        "intel_payment",
        "steal",
        "recover",
        "lost",
        "kept",
        "confiscate",
        "confiscated_loss",
        "intel_sale",
        "fee_in",
        "deposit_in",
    ]
    parts: list[str] = []
    for k in order:
        seg = _flow_segment_final(role, k, float(totals.get(k, 0.0) or 0.0))
        if seg:
            parts.append(seg)
    return " · ".join(parts) if parts else "No recent financial flow"


def _event_touches_actor(entity_id: str, event: dict) -> bool:
    eid = str(entity_id).strip()
    if _classify_flow_event(eid, event) is not None:
        return True
    keys = (
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "agent",
        "agent_id",
    )
    return any(str(event.get(k, "")).strip() == eid for k in keys)


def _narrate_recent_line(entity_id: str, role: str, event: dict) -> str:
    """Single-line narrative: Verb signed_amount context (last-5 list; STEP 3)."""
    et = str(event.get("type") or "")
    n = _flow_n
    eid = str(entity_id).strip()
    role = (role or "agent").lower()
    amt = event.get("amount")

    if et == "worker_earn" and str(event.get("worker_id", "")).strip() == eid:
        return f"Earned {_format_money_signed(abs(n(amt)))} at work"
    if et == "bank_fee_nano" and str(event.get("worker_id", "")).strip() == eid:
        return f"Lost {_format_money_signed(-abs(n(amt)))} to fees"
    if et == "bank_fee_nano":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Collected {_format_money_signed(abs(n(amt)))} in fees"
    if et == "worker_bank_deposit" and str(event.get("worker_id", "")).strip() == eid:
        return f"Deposited {_format_money_signed(-abs(n(amt)))} to bank"
    if et == "worker_bank_deposit":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Received {_format_money_signed(abs(n(amt)))} in deposits"
    if et == "thief_deposit" and str(event.get("thief_id", "")).strip() == eid:
        return f"Paid {_format_money_signed(-abs(n(amt)))} to bank"
    if et == "thief_deposit":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Received {_format_money_signed(abs(n(amt)))} in deposits"
    if et in {"worker_home_store", "worker_stash", "worker_store_home"} and str(
        event.get("worker_id", "")
    ).strip() == eid:
        return f"Stored {_format_money_signed(abs(n(amt)))} at home"
    if et == "steal_agent":
        if str(event.get("thief_id", "")).strip() == eid:
            wid = str(event.get("target_id") or event.get("worker_id") or "worker").strip()
            return f"Stole {_format_money_signed(abs(n(amt)))} from {wid}"
        if str(event.get("target_id", "")).strip() == eid or str(event.get("worker_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-abs(n(amt)))} to theft"
    if et == "spy_sell_info":
        price = abs(n(event.get("price") or event.get("amount") or 0.000005))
        if str(event.get("buyer_id", "")).strip() == eid:
            return f"Paid {_format_money_signed(-price)} for intel"
        if str(event.get("spy_id", "")).strip() == eid:
            return f"Received {_format_money_signed(price)} for intel"
    if et == "cop_recover":
        rec = event.get("amount")
        if rec is None:
            rec = event.get("recovered")
        if str(event.get("cop_id", "")).strip() == eid:
            return f"Recovered {_format_money_signed(abs(n(rec)))} from thief"
        if str(event.get("thief_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-abs(n(rec)))} to recovery"
    if et == "bank_zone_confiscation":
        conf = abs(n(event.get("amount")))
        if str(event.get("cop_id", "")).strip() == eid:
            return f"Confiscated {_format_money_signed(conf)} from bank robbery"
        if str(event.get("thief_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-conf)} to bank confiscation"
    if et == "redistribution" and str(event.get("cop_id", "")).strip() == eid:
        share = event.get("cop_share") or event.get("cop_amount") or event.get("kept_amount")
        return f"Kept {_format_money_signed(abs(n(share)))} after split"
    if et == "spy_intel_created" and str(event.get("spy_id", "")).strip() == eid:
        return "Created intel report for the market"
    if et == "spy_intel_discarded":
        return f"Intel discarded ({event.get('reason', 'unknown')})"
    if et == "spy_sell_info_skipped" and str(event.get("buyer_id", "")).strip() == eid:
        return f"Skipped intel purchase ({event.get('reason', 'unknown')})"
    if et == "worker_earn_skipped" and str(event.get("worker_id", "")).strip() == eid:
        return f"Earn skipped ({event.get('reason', 'unknown')})"
    if et == "bank_fee_skipped" and str(event.get("worker_id", "")).strip() == eid:
        return f"Bank fee skipped ({event.get('reason', 'unknown')})"
    return f"{et.replace('_', ' ').strip() or 'event'}"


def _slim_bridge_event(entity_id: str, role: str, event: dict) -> dict:
    out = {"type": str(event.get("type") or "")}
    for k in (
        "amount",
        "price",
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "recovered",
        "cop_share",
        "bank_share",
        "reason",
    ):
        if k in event and event.get(k) is not None:
            out[k] = event.get(k)
    out["summary"] = _narrate_recent_line(entity_id, role, event)
    return out


def _normalize_bridge_recent(items: list) -> list[dict]:
    """Bridge `recent`: max 5 entries, each dict has type + summary strings (no nulls)."""
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for ev in items:
        if not isinstance(ev, dict):
            continue
        typ = str(ev.get("type") or "")
        summ = str(ev.get("summary") or typ or "event").strip() or "event"
        out.append({"type": typ, "summary": summ})
    return out[-5:]


def _event_actor_ids(event: dict) -> set[str]:
    out: set[str] = set()
    for k in (
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "agent",
        "agent_id",
    ):
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            out.add(v.strip())
    return out


def _collect_actor_events_map(actor_ids: list[str], events: list, per_actor_limit: int = 50) -> dict[str, list]:
    """Collect latest linked events per actor in one reverse scan."""
    if per_actor_limit <= 0:
        return {aid: [] for aid in actor_ids}
    actor_set = {str(a).strip() for a in actor_ids if str(a).strip()}
    out: dict[str, list] = {aid: [] for aid in actor_set}
    if not actor_set:
        return out
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        linked = _event_actor_ids(ev)
        if not linked:
            continue
        touched = linked.intersection(actor_set)
        if not touched:
            continue
        for aid in touched:
            rows = out[aid]
            if len(rows) < per_actor_limit:
                rows.append(ev)
        if all(len(out[aid]) >= per_actor_limit for aid in actor_set):
            break
    for aid in actor_set:
        out[aid].reverse()
    return out


def _collect_actor_events(entity_id: str, events: list, limit: int = 40, max_scan: int = 5000) -> list:
    """Collect the latest events that touch one actor.

    This avoids global-tail starvation where noisy roles (e.g. cop patrol/chase)
    can hide worker events from small fixed windows.
    """
    if limit <= 0:
        return []
    picked: list = []
    scanned = 0
    for ev in reversed(events):
        scanned += 1
        if scanned > max_scan:
            break
        if not isinstance(ev, dict):
            continue
        if _event_touches_actor(entity_id, ev):
            picked.append(ev)
            if len(picked) >= limit:
                break
    picked.reverse()
    return picked


def _build_recent_for_actor(entity_id: str, role: str, events: list, limit: int = 5) -> list:
    return [
        _slim_bridge_event(entity_id, role, ev)
        for ev in _collect_actor_events(entity_id, events, limit=limit)
    ]


def _lifetime_from_event_stream(entity_id: str, events) -> tuple[float, float]:
    """Reconcile cumulative collected/lost from the ledger stream (bounded buffer).

    Counts credits/debits for the entity, backs out internal moves mirrored by typed
    events (bank deposit, home stash, thief deposit), and adds **typed fallbacks**
    when matching ledger rows have rolled out of the ring buffer ahead of the
    higher-level economy event (so UI lifetimes stay aligned with balances).
    """
    eid = str(entity_id).strip()
    collected = 0.0
    lost_debits = 0.0
    internal_moves = 0.0
    home_stash_theft = 0.0
    credit_hashes: set[str] = set()
    debit_hashes: set[str] = set()

    def _hash_chains(ev: dict) -> set[str]:
        hs: set[str] = set()
        th = ev.get("tx_hash")
        if th is not None and str(th).strip():
            hs.add(str(th).strip())
        steps = ev.get("tx_steps")
        if isinstance(steps, (list, tuple)):
            for s in steps:
                if s is not None and str(s).strip():
                    hs.add(str(s).strip())
        return hs

    for raw in events:
        if not isinstance(raw, dict):
            continue
        ev = raw
        t = str(ev.get("type") or "")
        aid = str(ev.get("agent_id", "")).strip() if ev.get("agent_id") is not None else ""
        if t == "credit" and aid == eid:
            amt = float(ev.get("amount", 0) or 0.0)
            if amt > 0:
                collected += amt
                credit_hashes.update(_hash_chains(ev))
        if t == "debit" and aid == eid:
            amt = float(ev.get("amount", 0) or 0.0)
            if amt > 0:
                lost_debits += amt
                debit_hashes.update(_hash_chains(ev))
        if t == "worker_bank_deposit" and str(ev.get("worker_id", "")).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t in {"worker_store_home", "worker_stash", "worker_home_store"} and str(
            ev.get("worker_id", "")
        ).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t == "thief_deposit" and str(ev.get("thief_id", "")).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t == "steal_agent" and ev.get("intel_id"):
            wid = str(ev.get("worker_id") or ev.get("target_id") or "").strip()
            if wid == eid:
                home_stash_theft += float(ev.get("amount", 0) or 0.0)

    def _chains_hit_any(ev: dict, pool: set[str]) -> bool:
        return bool(_hash_chains(ev).intersection(pool))

    for raw in events:
        if not isinstance(raw, dict):
            continue
        ev = raw
        t = str(ev.get("type") or "")
        if t == "worker_earn" and str(ev.get("worker_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("amount", 0) or 0.0)
        elif t == "steal_agent" and str(ev.get("thief_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("amount", 0) or 0.0)
        elif t == "cop_recover" and str(ev.get("cop_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                rec = ev.get("amount")
                if rec is None:
                    rec = ev.get("recovered")
                collected += float(rec or 0.0)
        elif t == "spy_sell_info" and str(ev.get("spy_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("price") or ev.get("amount") or 0.0)
        elif t == "bank_fee_nano" and str(ev.get("worker_id", "")).strip() == eid:
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("amount", 0) or 0.0)
        elif t == "spy_sell_info" and str(ev.get("buyer_id", "")).strip() == eid:
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("price") or ev.get("amount") or 0.0)
        elif t == "steal_agent":
            wid = str(ev.get("target_id") or ev.get("worker_id") or "").strip()
            if wid != eid or ev.get("intel_id"):
                continue
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("amount", 0) or 0.0)

    lost = max(0.0, lost_debits - internal_moves + home_stash_theft)
    return round(max(0.0, collected), 10), round(lost, 10)


def _sync_lifetime_counters(entity_id: str, entity: dict, events) -> tuple[float, float]:
    """Keep entity counters monotonic vs stream-derived floor (covers missed bumps / old sessions)."""
    c_evt, l_evt = _lifetime_from_event_stream(entity_id, events)
    c_ent = float(entity.get("lifetime_collected", 0.0) or 0.0)
    l_ent = float(entity.get("lifetime_lost", 0.0) or 0.0)
    c = max(c_ent, c_evt)
    l = max(l_ent, l_evt)
    entity["lifetime_collected"] = c
    entity["lifetime_lost"] = l
    return c, l


def build_smallville_frame(
    limit_events: int = 250,
    include_debug: bool = False,
    emit_sprite_trace: bool = False,
):
    with state_lock:
        shared = get_state()
        entities = shared.setdefault("entities", {})
        balances = shared.setdefault("balances", {})
        events = get_events()
        metrics = shared.setdefault("metrics", {})
        tick = int(shared.setdefault("economy", {}).get("tick", 0))
        cache_key = (tick, int(limit_events), bool(include_debug), bool(emit_sprite_trace))
        cached = _BRIDGE_FRAME_CACHE.get(cache_key)
        if cached is not None:
            return cached
        last_event_by_actor = {}
        for event in reversed(events):
            for key in ("worker_id", "thief_id", "cop_id", "bank_id", "target_id", "agent"):
                actor_id = event.get(key)
                if actor_id and actor_id not in last_event_by_actor:
                    last_event_by_actor[actor_id] = event
        # Larger tail so noisy roles do not evict per-actor flow/recent rows before 50 slots fill.
        actor_event_map = _collect_actor_events_map(list(entities.keys()), events, per_actor_limit=150)

        actors = []
        for entity_id, entity in entities.items():
            latest_event = last_event_by_actor.get(entity_id)
            action = _infer_actor_action(entity, latest_event)
            dest_zone, dest_x, dest_y = _resolve_destination(shared, entity, latest_event, entities, tick)
            lc, ll = _sync_lifetime_counters(entity_id, entity, events)
            lc_r = round(float(lc), 6)
            ll_r = round(float(ll), 6)
            ln_r = round(lc_r - ll_r, 6)
            flow_line = _build_flow_summary_line(
                entity_id, entity, actor_event_map.get(entity_id, [])
            )
            flow_s = (
                flow_line.strip()
                if isinstance(flow_line, str) and flow_line.strip()
                else "No recent financial flow"
            )
            raw_recent = [
                _slim_bridge_event(entity_id, _entity_flow_role(entity), ev)
                for ev in actor_event_map.get(entity_id, [])[-5:]
            ]
            ca_val = str(entity.get("current_action", action) or action).strip() or "idle"
            actor = {
                "id": entity_id,
                "persona_type": ROLE_TO_SMALLVILLE.get(entity.get("type"), "resident"),
                "role": entity.get("persona_role", entity.get("type")),
                "x": float(entity.get("x", 0.0) or 0.0),
                "y": float(entity.get("y", 0.0) or 0.0),
                "target_x": float(entity.get("target_x", entity.get("x", 0.0)) or 0.0),
                "target_y": float(entity.get("target_y", entity.get("y", 0.0)) or 0.0),
                "target_id": entity.get("target"),
                "action": action,
                # PASS 4 queue label (buying_intel / chasing_thief / etc.).
                # Keep alongside legacy `action` so bridge clients can prefer this
                # when available without breaking older renderers.
                "current_action": ca_val,
                "dest_zone": dest_zone,
                "dest_x": float(dest_x),
                "dest_y": float(dest_y),
                "top_action": entity.get("top_action"),
                "reflection": entity.get("reflection", "neutral"),
                "balance": round(float(balances.get(entity_id, 0.0) or 0.0), 6),
                "status_line": (
                    f"{action} | {entity.get('reflection', 'neutral')} | {dest_zone}"
                ),
                "home_storage": round(float(entity.get("home_storage", 0.0) or 0.0), 6),
                "carried_cash": round(float(entity.get("carried_cash", 0.0) or 0.0), 6),
                "lifetime_collected": lc_r,
                "lifetime_lost": ll_r,
                "lifetime_net": ln_r,
                "flow": flow_s,
                "recent": _normalize_bridge_recent(raw_recent),
            }
            if entity.get("type") == "worker":
                actor["worker_shift_phase"] = str(entity.get("worker_shift_phase", "to_mine") or "to_mine")
                actor["work_route"] = str(entity.get("work_route", "") or "")
            if entity.get("type") == "cop":
                # Cop ledger should be richer and long-lived; compute against full
                # event stream (not just the trimmed actor tail).
                actor["cop_stats"] = _compute_cop_stats(entity_id, events)
            actors.append(actor)

        payload = {
            "world": {
                "name": "AgenticEconomy-SmallvilleBridge",
                # Sentinel for Django / curl: proves this process is running this repo’s bridge.
                "bridge_revision": BRIDGE_CODE_REVISION,
                "tick": int(shared.setdefault("economy", {}).get("tick", 0)),
                "regime": shared.setdefault("economy", {}).get("regime", "balanced"),
                "narration": shared.setdefault("economy", {}).get("narration", ""),
            },
            "actors": actors,
            "metrics": {
                "total_spent": float(metrics.get("total_spent", 0.0) or 0.0),
                "successful_tx": int(metrics.get("successful_tx", 0) or 0),
                "failed_tx": int(metrics.get("failed_tx", 0) or 0),
                "cost_per_action": float(metrics.get("cost_per_action", 0.0) or 0.0),
                "success_rate": float(metrics.get("success_rate", 0.0) or 0.0),
            },
        }
        if include_debug:
            event_limit = max(1, min(int(limit_events), 1000))
            payload["events"] = events[-event_limit:]
            payload["state"] = {
                "entities": entities,
                "balances": balances,
                "metrics": metrics,
                "economy": shared.setdefault("economy", default_economy_state()),
            }
        if emit_sprite_trace:
            rows = []
            for a in actors:
                ax = float(a.get("x", 0.0) or 0.0)
                ay = float(a.get("y", 0.0) or 0.0)
                tx = float(a.get("target_x", ax) or ax)
                ty = float(a.get("target_y", ay) or ay)
                rows.append(
                    {
                        "id": a.get("id"),
                        "type": entities.get(str(a.get("id", "")), {}).get("type"),
                        "x": round(ax, 1),
                        "y": round(ay, 1),
                        "target": [round(tx, 1), round(ty, 1)],
                        "dest": [round(float(a.get("dest_x", tx) or tx), 1), round(float(a.get("dest_y", ty) or ty), 1)],
                        "action": a.get("action"),
                        "shift": a.get("worker_shift_phase"),
                        "route": a.get("work_route"),
                        "dist_to_target": round(math.hypot(tx - ax, ty - ay), 1),
                    }
                )
            payload["sprite_trace"] = rows
        _BRIDGE_FRAME_CACHE.clear()
        _BRIDGE_FRAME_CACHE[cache_key] = payload
        return payload


def build_smallville_frame_fast(
    limit_events: int = 250,
    include_debug: bool = False,
    emit_sprite_trace: bool = False,
):
    with state_lock:
        shared = get_state()
        tick = int(shared.setdefault("economy", {}).get("tick", 0))
        cache_key = (tick, int(limit_events), bool(include_debug), bool(emit_sprite_trace))
        cached = _BRIDGE_FRAME_CACHE.get(cache_key)
        if cached is not None:
            return cached
        entities = {
            entity_id: dict(entity or {})
            for entity_id, entity in shared.setdefault("entities", {}).items()
        }
        balances = dict(shared.setdefault("balances", {}))
        metrics = dict(shared.setdefault("metrics", {}))
        economy = dict(shared.setdefault("economy", default_economy_state()))
        events = list(get_events())

    heavy_mode = bool(include_debug or emit_sprite_trace)
    last_event_by_actor = {}
    for event in reversed(events):
        for key in ("worker_id", "thief_id", "cop_id", "bank_id", "target_id", "agent"):
            actor_id = event.get(key)
            if actor_id and actor_id not in last_event_by_actor:
                last_event_by_actor[actor_id] = event

    actor_event_map = {}
    if heavy_mode:
        actor_event_map = _collect_actor_events_map(list(entities.keys()), events, per_actor_limit=150)

    state_snapshot = {
        "entities": entities,
        "balances": balances,
        "metrics": metrics,
        "economy": economy,
    }

    actors = []
    for entity_id, entity in entities.items():
        latest_event = last_event_by_actor.get(entity_id)
        action = _infer_actor_action(entity, latest_event)
        dest_zone, dest_x, dest_y = _resolve_destination(
            state_snapshot, entity, latest_event, entities, tick
        )
        ca_val = str(entity.get("current_action", action) or action).strip() or "idle"
        lc_r = round(float(entity.get("lifetime_collected", 0.0) or 0.0), 6)
        ll_r = round(float(entity.get("lifetime_lost", 0.0) or 0.0), 6)
        actor = {
            "id": entity_id,
            "persona_type": ROLE_TO_SMALLVILLE.get(entity.get("type"), "resident"),
            "role": entity.get("persona_role", entity.get("type")),
            "x": float(entity.get("x", 0.0) or 0.0),
            "y": float(entity.get("y", 0.0) or 0.0),
            "target_x": float(entity.get("target_x", entity.get("x", 0.0)) or 0.0),
            "target_y": float(entity.get("target_y", entity.get("y", 0.0)) or 0.0),
            "current_action": ca_val,
            "dest_zone": dest_zone,
            "dest_x": float(dest_x),
            "dest_y": float(dest_y),
            "balance": round(float(balances.get(entity_id, 0.0) or 0.0), 6),
            "home_storage": round(float(entity.get("home_storage", 0.0) or 0.0), 6),
            "lifetime_collected": lc_r,
            "lifetime_lost": ll_r,
            "lifetime_net": round(lc_r - ll_r, 6),
        }
        if entity.get("type") == "worker":
            actor["worker_shift_phase"] = str(
                entity.get("worker_shift_phase", "to_mine") or "to_mine"
            )
        if heavy_mode:
            lc, ll = _sync_lifetime_counters(entity_id, entity, events)
            actor["lifetime_collected"] = round(float(lc), 6)
            actor["lifetime_lost"] = round(float(ll), 6)
            actor["lifetime_net"] = round(
                actor["lifetime_collected"] - actor["lifetime_lost"], 6
            )
            flow_line = _build_flow_summary_line(
                entity_id, entity, actor_event_map.get(entity_id, [])
            )
            actor["target_id"] = entity.get("target")
            actor["action"] = action
            actor["top_action"] = entity.get("top_action")
            actor["reflection"] = entity.get("reflection", "neutral")
            actor["status_line"] = (
                f"{action} | {entity.get('reflection', 'neutral')} | {dest_zone}"
            )
            actor["carried_cash"] = round(float(entity.get("carried_cash", 0.0) or 0.0), 6)
            actor["flow"] = (
                flow_line.strip()
                if isinstance(flow_line, str) and flow_line.strip()
                else "No recent financial flow"
            )
            actor["recent"] = _normalize_bridge_recent(
                [
                    _slim_bridge_event(entity_id, _entity_flow_role(entity), ev)
                    for ev in actor_event_map.get(entity_id, [])[-5:]
                ]
            )
            if entity.get("type") == "worker":
                actor["work_route"] = str(entity.get("work_route", "") or "")
            if entity.get("type") == "cop":
                actor["cop_stats"] = _compute_cop_stats(entity_id, events)
        actors.append(actor)

    payload = {
        "world": {
            "name": "AgenticEconomy-SmallvilleBridge",
            "bridge_revision": BRIDGE_CODE_REVISION,
            "tick": tick,
            "regime": economy.get("regime", "balanced"),
            "narration": economy.get("narration", ""),
        },
        "actors": actors,
        "metrics": {
            "total_spent": float(metrics.get("total_spent", 0.0) or 0.0),
            "successful_tx": int(metrics.get("successful_tx", 0) or 0),
            "failed_tx": int(metrics.get("failed_tx", 0) or 0),
            "cost_per_action": float(metrics.get("cost_per_action", 0.0) or 0.0),
            "success_rate": float(metrics.get("success_rate", 0.0) or 0.0),
        },
    }
    if include_debug:
        event_limit = max(1, min(int(limit_events), 1000))
        payload["events"] = events[-event_limit:]
        payload["state"] = state_snapshot
    if emit_sprite_trace:
        rows = []
        for a in actors:
            ax = float(a.get("x", 0.0) or 0.0)
            ay = float(a.get("y", 0.0) or 0.0)
            tx = float(a.get("target_x", ax) or ax)
            ty = float(a.get("target_y", ay) or ay)
            rows.append(
                {
                    "id": a.get("id"),
                    "type": entities.get(str(a.get("id", "")), {}).get("type"),
                    "x": round(ax, 1),
                    "y": round(ay, 1),
                    "target": [round(tx, 1), round(ty, 1)],
                    "dest": [round(float(a.get("dest_x", tx) or tx), 1), round(float(a.get("dest_y", ty) or ty), 1)],
                    "action": a.get("action", a.get("current_action")),
                    "shift": a.get("worker_shift_phase"),
                    "route": a.get("work_route"),
                    "dist_to_target": round(math.hypot(tx - ax, ty - ay), 1),
                }
            )
        payload["sprite_trace"] = rows
    _BRIDGE_FRAME_CACHE.clear()
    _BRIDGE_FRAME_CACHE[cache_key] = payload
    return payload


@bridge_router.get("/bridge/smallville")
def get_smallville_bridge_frame(
    limit_events: int = Query(250, ge=1, le=2000),
    include_debug: bool = False,
    trace: bool = Query(False, description="Include sprite_trace[] for tooling / debugging"),
):
    return build_smallville_frame_fast(
        limit_events=limit_events,
        include_debug=include_debug,
        emit_sprite_trace=trace,
    )


@bridge_router.get("/bridge/manifest")
def get_bridge_manifest():
    """Lightweight probe: if this 404s or revision mismatches, port 8000 is not this codebase."""
    return {
        "bridge_revision": BRIDGE_CODE_REVISION,
        "endpoints_py": str(Path(__file__).resolve()),
    }
