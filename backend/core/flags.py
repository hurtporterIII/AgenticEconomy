"""
Central feature flags for controlling which agents are allowed to mutate balances.

MASTER FLAG: NON_WORKER_ECONOMICS
    When False (default), ONLY the worker FSM is allowed to mutate balances.
    Banker, thief, and cop still run their spatial / decision logic but any
    branch that would call debit() / credit() / transfer() is short-circuited
    and logged as `<agent>_disabled` for audit.

    When True, full original behavior is restored (all agents mutate
    balances as designed).

    Flip at runtime via env var `NON_WORKER_ECONOMICS=on` (or 1/true/yes).

PER-AGENT OVERRIDES
    `BANKER_ECONOMIC_ACTIONS` still exists for granular banker-only control.
    The *master* flag wins: if NON_WORKER_ECONOMICS is False, no agent
    (including banker) mutates balances regardless of its per-agent flag.

WHY THIS EXISTS
    The nano-purchasing worker loop requires the invariant
    EARN == DEPOSIT + HOME (0.0001 == 0.00001 + 0.00009). If any other
    agent drains worker balance mid-cycle, the `liquid < HOME` guard
    trips and `worker_store_home` never fires. This flag keeps the
    ledger clean: `worker_earn → worker_bank_deposit → worker_store_home`
    on repeat, with no interference.
"""

import os


def _env_truthy(name: str, default: str = "off") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "on", "true", "yes"}


# Master switch. Default OFF (nano-demo isolation).
NON_WORKER_ECONOMICS: bool = _env_truthy("NON_WORKER_ECONOMICS", "off")

# Per-agent override for the banker. Only consulted when the master flag
# is ON; when master is OFF, banker is always disabled.
BANKER_ECONOMIC_ACTIONS: bool = _env_truthy("BANKER_ECONOMIC_ACTIONS", "off")

# Nano-economy hooks: reactive banker-fee / thief-steal / cop-recover layer
# that produces balanced, nano-scale transactions around the worker FSM.
# Independent of NON_WORKER_ECONOMICS — the nano hooks are meant to REPLACE
# the old drain-at-scale economic code, not coexist with it. Default ON so
# the demo produces many small transactions out of the box.
NANO_ECONOMY_HOOKS: bool = _env_truthy("NANO_ECONOMY_HOOKS", "on")


def banker_economics_enabled() -> bool:
    """True only if the master flag AND the banker-specific flag are on."""
    return NON_WORKER_ECONOMICS and BANKER_ECONOMIC_ACTIONS


def thief_economics_enabled() -> bool:
    """True only if the master flag is on (no per-agent thief override yet)."""
    return NON_WORKER_ECONOMICS


def cop_economics_enabled() -> bool:
    """True only if the master flag is on (no per-agent cop override yet)."""
    return NON_WORKER_ECONOMICS
