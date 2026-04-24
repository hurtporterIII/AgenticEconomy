from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MAX_BATCH_COMMANDS = 50
MAX_RUN_STEPS = 500


@dataclass
class LegacyHandlers:
    step: Callable[[], dict]
    state: Callable[[], dict]
    spawn: Callable[[str, str | None, float], dict]
    spawn_types: Callable[[], dict]
    current_time: Callable[[], dict] | None = None
    persona_tile: Callable[[str], dict] | None = None
    tile_events: Callable[[int, int], dict] | None = None
    persona_schedule: Callable[[str], dict] | None = None
    all_persona_schedules: Callable[[], dict] | None = None


def _as_command_list(payload: dict) -> tuple[list[str], bool]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    has_command = "command" in payload
    has_commands = "commands" in payload
    if has_command and has_commands:
        raise ValueError("Provide either 'command' or 'commands', not both")
    if not has_command and not has_commands:
        raise ValueError("Missing 'command' or 'commands'")

    if has_command:
        cmd = str(payload.get("command", "") or "").strip()
        if not cmd:
            raise ValueError("'command' must be a non-empty string")
        return [cmd], False

    raw_commands = payload.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        raise ValueError("'commands' must be a non-empty array")
    if len(raw_commands) > MAX_BATCH_COMMANDS:
        raise ValueError(f"'commands' exceeds max batch size ({MAX_BATCH_COMMANDS})")

    out: list[str] = []
    for idx, item in enumerate(raw_commands):
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("command", "") or "").strip()
        else:
            raise ValueError(f"commands[{idx}] must be a string or object with 'command'")
        if not text:
            raise ValueError(f"commands[{idx}] is empty")
        out.append(text)
    return out, True


def _parse_spawn_tokens(tokens: list[str]) -> tuple[str, str | None, float]:
    if len(tokens) < 2:
        raise ValueError("spawn requires an entity type, e.g. 'spawn worker balance=5'")
    if tokens[1].lower() == "types":
        raise ValueError("spawn types is handled separately")

    entity_type = tokens[1].strip().lower()
    entity_id: str | None = None
    balance = 0.0
    for token in tokens[2:]:
        key, sep, value = token.partition("=")
        if sep != "=":
            continue
        k = key.strip().lower()
        v = value.strip()
        if k == "entity_id":
            entity_id = v or None
        elif k == "balance":
            try:
                balance = float(v)
            except ValueError as exc:
                raise ValueError("spawn balance must be a number") from exc
    return entity_type, entity_id, balance


def _run_single_command(command: str, handlers: LegacyHandlers) -> tuple[bool, dict]:
    trimmed = command.strip()
    lowered = trimmed.lower()
    tokens = trimmed.split()

    if lowered == "print current time":
        if handlers.current_time is None:
            return False, {"code": "unsupported_legacy_command", "message": "print current time is not mapped"}
        return True, {"status": "ok", "time": handlers.current_time()}

    if lowered == "print all persona schedule":
        if handlers.all_persona_schedules is None:
            return False, {"code": "unsupported_legacy_command", "message": "print all persona schedule is not mapped"}
        return True, {"status": "ok", "schedules": handlers.all_persona_schedules()}

    if lowered.startswith("print persona schedule "):
        if handlers.persona_schedule is None:
            return False, {"code": "unsupported_legacy_command", "message": "print persona schedule is not mapped"}
        persona_id = trimmed[len("print persona schedule ") :].strip()
        if not persona_id:
            return False, {"code": "invalid_persona_id", "message": "Use: print persona schedule <persona_id>"}
        return True, {"status": "ok", "schedule": handlers.persona_schedule(persona_id)}

    if lowered.startswith("print persona current tile "):
        if handlers.persona_tile is None:
            return False, {"code": "unsupported_legacy_command", "message": "print persona current tile is not mapped"}
        persona_id = trimmed[len("print persona current tile ") :].strip()
        if not persona_id:
            return False, {"code": "invalid_persona_id", "message": "Use: print persona current tile <persona_id>"}
        return True, {"status": "ok", "tile": handlers.persona_tile(persona_id)}

    if lowered.startswith("print tile event "):
        if handlers.tile_events is None:
            return False, {"code": "unsupported_legacy_command", "message": "print tile event is not mapped"}
        coords = trimmed[len("print tile event ") :].strip()
        parts = [part.strip() for part in coords.split(",")]
        if len(parts) != 2:
            return False, {"code": "invalid_tile_coordinates", "message": "Use: print tile event <x>, <y>"}
        try:
            tx = int(parts[0])
            ty = int(parts[1])
        except ValueError:
            return False, {"code": "invalid_tile_coordinates", "message": "Tile coordinates must be integers"}
        return True, {"status": "ok", "tile_events": handlers.tile_events(tx, ty)}

    if lowered in {"state", "get state"}:
        return True, {"status": "ok", "state": handlers.state()}

    if lowered in {"step", "tick"}:
        return True, {"status": "ok", "step": handlers.step()}

    if lowered in {"spawn types", "spawn/type", "spawn_types"}:
        return True, {"status": "ok", "spawn_types": handlers.spawn_types()}

    if lowered.startswith("run "):
        if len(tokens) != 2:
            return False, {
                "code": "invalid_run_syntax",
                "message": "Use: run <steps>",
            }
        try:
            steps_requested = int(tokens[1])
        except ValueError:
            return False, {
                "code": "invalid_run_steps",
                "message": "run requires an integer step count",
            }
        if steps_requested < 1:
            return False, {
                "code": "invalid_run_steps",
                "message": "run step count must be >= 1",
            }
        steps = min(steps_requested, MAX_RUN_STEPS)
        last_step = None
        for _ in range(steps):
            last_step = handlers.step()
        return True, {
            "status": "ok",
            "steps_requested": steps_requested,
            "steps_completed": steps,
            "clamped": steps != steps_requested,
            "last_step": last_step,
        }

    if lowered.startswith("spawn "):
        try:
            entity_type, entity_id, balance = _parse_spawn_tokens(tokens)
            spawned = handlers.spawn(entity_type, entity_id, balance)
            return True, {"status": "ok", "spawn": spawned}
        except ValueError as exc:
            return False, {"code": "spawn_error", "message": str(exc)}

    return False, {
        "code": "unsupported_legacy_command",
        "message": (
            "Command is not mapped yet. Supported now: state, step, run <n>, "
            "spawn <type> [entity_id=...] [balance=...], spawn types, "
            "print current time, print persona schedule <id>, print all persona schedule, "
            "print persona current tile <id>, print tile event <x>, <y>."
        ),
    }


def execute_legacy_command_request(payload: dict, handlers: LegacyHandlers) -> dict:
    commands, is_batch = _as_command_list(payload)
    continue_on_error = bool(payload.get("continue_on_error", is_batch))

    results = []
    failed = 0
    succeeded = 0

    for idx, command in enumerate(commands):
        ok, info = _run_single_command(command, handlers)
        row = {"index": idx, "command": command, "ok": ok}
        row.update({"result": info} if ok else {"error": info})
        results.append(row)
        if ok:
            succeeded += 1
        else:
            failed += 1
            if not continue_on_error:
                break

    return {
        "status": "ok" if failed == 0 else "partial_failure",
        "mode": "batch" if is_batch else "single",
        "accepted": len(commands),
        "succeeded": succeeded,
        "failed": failed,
        "continue_on_error": continue_on_error,
        "results": results,
    }
