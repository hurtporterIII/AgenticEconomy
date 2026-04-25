"""
Author: Joon Sung Park (joonspk@stanford.edu)
File: views.py
"""
import os
import string
import random
import json
from os import listdir
import os
import requests
from urllib.parse import urlparse

import datetime
from django.shortcuts import render, redirect, HttpResponseRedirect
from django.http import HttpResponse, JsonResponse
from global_methods import *

from django.contrib.staticfiles.templatetags.staticfiles import static
from .models import *

BRIDGE_SIM_CODE = "bridge_smallville"
BRIDGE_URL = os.getenv("SMALLVILLE_BRIDGE_URL", "http://127.0.0.1:8000/api/bridge/smallville")
BRIDGE_FALLBACK_URL = os.getenv("SMALLVILLE_BRIDGE_FALLBACK_URL", "http://127.0.0.1:8002/api/bridge/smallville")
# Default off: this repo's FastAPI enables AUTO_TICK (see backend/main.py). Polling should only fetch state.
# Set SMALLVILLE_BRIDGE_STEP_ON_POLL=1 only if your bridge backend does not run its own tick loop.
BRIDGE_STEP_ON_POLL = os.getenv("SMALLVILLE_BRIDGE_STEP_ON_POLL", "0") == "1"
# Append ?trace=1 to economy /bridge/smallville GET (adds sprite_trace for HUD / debugging).
# Default OFF for smoother load/render unless explicitly enabled.
BRIDGE_TRACE = os.getenv("SMALLVILLE_BRIDGE_TRACE", "0").strip().lower() in {"1", "true", "yes"}
SMALLVILLE_MODE = os.getenv("SMALLVILLE_MODE", "native").strip().lower()
BRIDGE_ENABLED = SMALLVILLE_MODE == "bridge"
TILE_SIZE = 32
BRIDGE_LAST_GOOD_PAYLOAD = None
# Keep backend destination labels verbatim so role hubs match on-map building titles.
LOCATION_ALIASES = {}


def _bridge_step_once(base_url):
  """Advance exactly one economy server (scheme://host:port only)."""
  try:
    parsed = urlparse((base_url or "").split("?", 1)[0].strip())
    if not parsed.netloc:
      return
    base = f"{parsed.scheme}://{parsed.netloc}"
    step_url = f"{base}/api/step"
    requests.post(step_url, timeout=2.0)
  except Exception:
    pass


def _bridge_api_base(base_url):
  try:
    parsed = urlparse((base_url or "").split("?", 1)[0].strip())
    if not parsed.netloc:
      return ""
    return f"{parsed.scheme}://{parsed.netloc}"
  except Exception:
    return ""


def _bridge_fetch_url(base_url, trace):
  u = (base_url or "").strip()
  if not u:
    return ""
  if not trace:
    return u
  join = "&" if "?" in u else "?"
  return f"{u}{join}trace=1"


def _bridge_payload_is_agentic_economy_bridge(payload):
  """True if JSON looks like *this* repo’s FastAPI bridge (not another app on :8000).

  Django tries BRIDGE_URL first; a random service there can return 200 + actors with
  balance but no lifetime_* keys, which makes the UI look “stuck” while the real API
  on BRIDGE_FALLBACK_URL is never queried.
  """
  if not isinstance(payload, dict):
    return False
  world = payload.get("world") or {}
  if str(world.get("bridge_revision", "")).strip():
    return True
  for a in payload.get("actors") or []:
    if isinstance(a, dict) and (
        "lifetime_collected" in a or "lifetime_net" in a or "lifetime_lost" in a
    ):
      return True
  # Empty actors (bootstrapping) is still usable.
  if not (payload.get("actors") or []):
    return True
  return False


def _bridge_fetch():
  global BRIDGE_LAST_GOOD_PAYLOAD
  if not BRIDGE_ENABLED:
    return {"actors": [], "events": [], "metrics": {}, "world": {}}
  bases = [BRIDGE_URL, BRIDGE_FALLBACK_URL]
  last_empty = None
  for idx, base in enumerate(bases):
    base = (base or "").strip()
    if not base:
      continue
    fetch_url = _bridge_fetch_url(base, BRIDGE_TRACE)
    try:
      if BRIDGE_STEP_ON_POLL:
        _bridge_step_once(base)
      res = requests.get(fetch_url, timeout=2.5)
      if res.status_code != 200:
        continue
      payload = res.json()
      if not _bridge_payload_is_agentic_economy_bridge(payload):
        continue
      actors = payload.get("actors", [])
      if actors:
        BRIDGE_LAST_GOOD_PAYLOAD = payload
      if idx == 0 and not actors:
        last_empty = payload
        continue
      return payload
    except Exception:
      continue
  if BRIDGE_LAST_GOOD_PAYLOAD:
    return BRIDGE_LAST_GOOD_PAYLOAD
  return last_empty or {"actors": [], "events": [], "metrics": {}, "world": {}}


def _bridge_persona_lists(bridge_data):
  persona_names = []
  persona_init_pos = []
  for actor in bridge_data.get("actors", []):
    actor_id = str(actor.get("id", "")).strip()
    if not actor_id:
      continue
    # Keep bank as a location/account concept in backend, not a visible persona.
    if str(actor.get("role", actor.get("type", ""))).lower() == "bank":
      continue
    # Bridge mode uses pixel coordinates to preserve fine-grained movement.
    px_x = int(float(actor.get("x", 0.0) or 0.0))
    px_y = int(float(actor.get("y", 0.0) or 0.0))
    persona_names += [[actor_id, actor_id]]
    persona_init_pos += [[actor_id, px_x, px_y]]
  return persona_names, persona_init_pos


def _bridge_update_payload(step):
  bridge_data = _bridge_fetch()
  world = bridge_data.get("world", {})
  actors = bridge_data.get("actors", [])
  persona = {}
  now = datetime.datetime.now().strftime("%B %d, %Y, %H:%M:%S")
  for actor in actors:
    actor_id = str(actor.get("id", "")).strip()
    if not actor_id:
      continue
    # Do not render a standalone "bank person" in bridge UI.
    if str(actor.get("role", actor.get("type", ""))).lower() == "bank":
      continue
    # Use live current position for rendering movement.
    px_x = int(float(actor.get("x", 0.0) or 0.0))
    px_y = int(float(actor.get("y", 0.0) or 0.0))
    # Prefer backend-authored queue label when present; fallback to legacy action.
    action = str(actor.get("current_action", actor.get("action", "idle")) or "idle")
    # Workers often have empty current_action (queue is for non-workers) while
    # still moving deterministically through shift phases. Avoid misleading
    # "idle" cards by mapping worker phase to a readable action label.
    role_hint = str(actor.get("role", "")).lower()
    if role_hint == "worker" and action == "idle":
      phase = str(actor.get("worker_shift_phase", "") or "").strip().lower()
      if phase == "to_mine":
        action = "commuting_to_work"
      elif phase == "to_bank":
        action = "commuting_to_bank"
      elif phase == "to_home":
        action = "returning_home"
    elif role_hint == "cop" and action == "idle":
      # Cop may move under default behavior without a queued current_action label.
      # If target differs from current position, expose a readable active state.
      cx = float(actor.get("x", 0.0) or 0.0)
      cy = float(actor.get("y", 0.0) or 0.0)
      tx_hint = float(actor.get("target_x", cx) or cx)
      ty_hint = float(actor.get("target_y", cy) or cy)
      if abs(tx_hint - cx) > 8.0 or abs(ty_hint - cy) > 8.0:
        top = str(actor.get("top_action", "") or "").lower()
        if top in {"chase", "call_service"}:
          action = "responding"
        else:
          action = "patrolling"
    role = str(actor.get("role", "resident"))
    reflection = str(actor.get("reflection", "neutral"))
    raw_dest_zone = str(actor.get("dest_zone", "district"))
    dest_zone = LOCATION_ALIASES.get(raw_dest_zone, raw_dest_zone)
    # In bridge mode, renderer pathing must follow backend movement target,
    # otherwise it fights role destination hints and causes "walk-by" behavior.
    dest_x = float(actor.get("target_x", actor.get("dest_x", actor.get("x", 0.0))) or 0.0)
    dest_y = float(actor.get("target_y", actor.get("dest_y", actor.get("y", 0.0))) or 0.0)
    bal = round(float(actor.get("balance", 0.0) or 0.0), 6)
    hs = round(float(actor.get("home_storage", 0.0) or 0.0), 6)
    lc = round(float(actor.get("lifetime_collected", 0.0) or 0.0), 6)
    ll = round(float(actor.get("lifetime_lost", 0.0) or 0.0), 6)
    ln = round(float(actor.get("lifetime_net", lc - ll) or (lc - ll)), 6)
    fl = str(actor.get("flow") or "No recent financial flow").strip() or "No recent financial flow"
    rc = actor.get("recent")
    if not isinstance(rc, list):
      rc = []
    persona[actor_id] = {
      "movement": [px_x, px_y],
      "pronunciatio": reflection,
      "description": f"{action}@{dest_zone}",
      "chat": None,
      "dest_zone": dest_zone,
      "dest_x": int(dest_x),
      "dest_y": int(dest_y),
      "role": role,
      "shift": str(actor.get("worker_shift_phase", "") or ""),
      "work_route": str(actor.get("work_route", "") or ""),
      # Economy + flow (from FastAPI bridge actors; used by persona panel, not movement)
      "balance": bal,
      "home_storage": hs,
      "lifetime_collected": lc,
      "lifetime_lost": ll,
      "lifetime_net": ln,
      "carried_cash": round(float(actor.get("carried_cash", 0.0) or 0.0), 6),
      # `action` includes worker/cop phase-derived labels when API sends idle.
      "current_action": action,
      "flow": fl,
      "recent": rc,
      "cop_stats": actor.get("cop_stats") if isinstance(actor.get("cop_stats"), dict) else {},
    }

  return {
    "<step>": int(step),
    "meta": {
      "curr_time": now,
      "bridge_tick": world.get("tick", 0),
      "regime": world.get("regime", "balanced"),
      "sprite_trace": bridge_data.get("sprite_trace"),
      "bridge_trace_enabled": bool(BRIDGE_TRACE),
    },
    "persona": persona,
  }


def _mode_hint_response():
  return HttpResponseRedirect("/simulator_home")


def landing(request): 
  context = {}
  template = "landing/landing.html"
  return render(request, template, context)


def demo(request, sim_code, step, play_speed="2"): 
  if sim_code == BRIDGE_SIM_CODE:
    if not BRIDGE_ENABLED:
      return _mode_hint_response()
    bridge_data = _bridge_fetch()
    persona_names, persona_init_pos = _bridge_persona_lists(bridge_data)
    context = {"sim_code": sim_code,
               "step": int(step),
               "persona_names": persona_names,
               "persona_init_pos": persona_init_pos,
               "mode": "replay"}
    template = "home/home.html"
    return render(request, template, context)

  move_file = f"compressed_storage/{sim_code}/master_movement.json"
  meta_file = f"compressed_storage/{sim_code}/meta.json"
  if not check_if_file_exists(meta_file) or not check_if_file_exists(move_file):
    return HttpResponse(
      f"Demo '{sim_code}' not found in compressed_storage. "
      "Use an existing compressed simulation name or run native mode at /simulator_home.",
      status=404,
    )
  step = int(step)
  play_speed_opt = {"1": 1, "2": 2, "3": 4,
                    "4": 8, "5": 16, "6": 32}
  if play_speed not in play_speed_opt: play_speed = 2
  else: play_speed = play_speed_opt[play_speed]

  # Loading the basic meta information about the simulation.
  meta = dict() 
  with open (meta_file) as json_file: 
    meta = json.load(json_file)

  sec_per_step = meta["sec_per_step"]
  start_datetime = datetime.datetime.strptime(meta["start_date"] + " 00:00:00", 
                                              '%B %d, %Y %H:%M:%S')
  for i in range(step): 
    start_datetime += datetime.timedelta(seconds=sec_per_step)
  start_datetime = start_datetime.strftime("%Y-%m-%dT%H:%M:%S")

  # Loading the movement file
  raw_all_movement = dict()
  with open(move_file) as json_file: 
    raw_all_movement = json.load(json_file)
 
  # Loading all names of the personas
  persona_names = dict()
  persona_names = []
  persona_names_set = set()
  for p in list(raw_all_movement["0"].keys()): 
    persona_names += [{"original": p, 
                       "underscore": p.replace(" ", "_"), 
                       "initial": p[0] + p.split(" ")[-1][0]}]
    persona_names_set.add(p)

  # <all_movement> is the main movement variable that we are passing to the 
  # frontend. Whereas we use ajax scheme to communicate steps to the frontend
  # during the simulation stage, for this demo, we send all movement 
  # information in one step. 
  all_movement = dict()

  # Preparing the initial step. 
  # <init_prep> sets the locations and descriptions of all agents at the
  # beginning of the demo determined by <step>. 
  init_prep = dict() 
  for int_key in range(step+1): 
    key = str(int_key)
    val = raw_all_movement[key]
    for p in persona_names_set: 
      if p in val: 
        init_prep[p] = val[p]
  persona_init_pos = dict()
  for p in persona_names_set: 
    persona_init_pos[p.replace(" ","_")] = init_prep[p]["movement"]
  all_movement[step] = init_prep

  # Finish loading <all_movement>
  for int_key in range(step+1, len(raw_all_movement.keys())): 
    all_movement[int_key] = raw_all_movement[str(int_key)]

  context = {"sim_code": sim_code,
             "step": step,
             "persona_names": persona_names,
             "persona_init_pos": json.dumps(persona_init_pos), 
             "all_movement": json.dumps(all_movement), 
             "start_datetime": start_datetime,
             "sec_per_step": sec_per_step,
             "play_speed": play_speed,
             "mode": "demo"}
  template = "demo/demo.html"

  return render(request, template, context)


def UIST_Demo(request): 
  return demo(request, "March20_the_ville_n25_UIST_RUN-step-1-141", 2160, play_speed="3")


def home(request):
  f_curr_sim_code = "temp_storage/curr_sim_code.json"
  f_curr_step = "temp_storage/curr_step.json"

  # In bridge mode there is no native reverie step file; send users straight
  # to the live bridge scene instead of showing "start backend" error page.
  if BRIDGE_ENABLED and not check_if_file_exists(f_curr_step):
    return HttpResponseRedirect(f"/demo/{BRIDGE_SIM_CODE}/0/2/")

  if not check_if_file_exists(f_curr_step): 
    context = {}
    template = "home/error_start_backend.html"
    return render(request, template, context)

  with open(f_curr_sim_code) as json_file:  
    sim_code = json.load(json_file)["sim_code"]

  if BRIDGE_ENABLED and sim_code == BRIDGE_SIM_CODE:
    with open(f_curr_step) as json_file:  
      step = json.load(json_file)["step"]
    os.remove(f_curr_step)
    bridge_data = _bridge_fetch()
    persona_names, persona_init_pos = _bridge_persona_lists(bridge_data)
    context = {"sim_code": sim_code,
               "step": step,
               "persona_names": persona_names,
               "persona_init_pos": persona_init_pos,
               "mode": "simulate"}
    template = "home/home.html"
    return render(request, template, context)

  sim_storage_dir = f"storage/{sim_code}"
  if not os.path.exists(sim_storage_dir):
    # Stale temp pointer (e.g., deleted/renamed simulation). Recover cleanly.
    context = {}
    template = "landing/landing.html"
    return render(request, template, context)
  
  with open(f_curr_step) as json_file:  
    step = json.load(json_file)["step"]

  os.remove(f_curr_step)

  persona_names = []
  persona_names_set = set()
  for i in find_filenames(f"storage/{sim_code}/personas", ""): 
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      persona_names += [[x, x.replace(" ", "_")]]
      persona_names_set.add(x)

  persona_init_pos = []
  file_count = []
  for i in find_filenames(f"storage/{sim_code}/environment", ".json"):
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      file_count += [int(x.split(".")[0])]
  curr_json = f'storage/{sim_code}/environment/{str(max(file_count))}.json'
  with open(curr_json) as json_file:  
    persona_init_pos_dict = json.load(json_file)
    for key, val in persona_init_pos_dict.items(): 
      if key in persona_names_set: 
        persona_init_pos += [[key, val["x"], val["y"]]]

  context = {"sim_code": sim_code,
             "step": step, 
             "persona_names": persona_names,
             "persona_init_pos": persona_init_pos,
             "mode": "simulate"}
  template = "home/home.html"
  return render(request, template, context)


def replay(request, sim_code, step): 
  sim_code = sim_code
  step = int(step)

  if sim_code == BRIDGE_SIM_CODE:
    if not BRIDGE_ENABLED:
      return _mode_hint_response()
    bridge_data = _bridge_fetch()
    persona_names, persona_init_pos = _bridge_persona_lists(bridge_data)
    context = {"sim_code": sim_code,
               "step": step,
               "persona_names": persona_names,
               "persona_init_pos": persona_init_pos,
               "mode": "replay"}
    template = "home/home.html"
    return render(request, template, context)

  if not os.path.exists(f"storage/{sim_code}"):
    return HttpResponse(
      f"Simulation '{sim_code}' not found in storage. "
      "Start reverie.py and create/load a simulation first.",
      status=404,
    )

  persona_names = []
  persona_names_set = set()
  for i in find_filenames(f"storage/{sim_code}/personas", ""): 
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      persona_names += [[x, x.replace(" ", "_")]]
      persona_names_set.add(x)

  persona_init_pos = []
  file_count = []
  for i in find_filenames(f"storage/{sim_code}/environment", ".json"):
    x = i.split("/")[-1].strip()
    if x[0] != ".": 
      file_count += [int(x.split(".")[0])]
  curr_json = f'storage/{sim_code}/environment/{str(max(file_count))}.json'
  with open(curr_json) as json_file:  
    persona_init_pos_dict = json.load(json_file)
    for key, val in persona_init_pos_dict.items(): 
      if key in persona_names_set: 
        persona_init_pos += [[key, val["x"], val["y"]]]

  context = {"sim_code": sim_code,
             "step": step,
             "persona_names": persona_names,
             "persona_init_pos": persona_init_pos, 
             "mode": "replay"}
  template = "home/home.html"
  return render(request, template, context)


def replay_persona_state(request, sim_code, step, persona_name): 
  sim_code = sim_code
  step = int(step)

  persona_name_underscore = persona_name
  persona_name = " ".join(persona_name.split("_"))

  # Bridge mode has no reverie bootstrap_memory tree on disk.
  # Serve a live "state details" view from current bridge actor payload.
  if BRIDGE_ENABLED and sim_code == BRIDGE_SIM_CODE:
    bridge_data = _bridge_fetch()
    actor = None
    for a in bridge_data.get("actors", []):
      if str(a.get("id", "")).strip() == persona_name_underscore:
        actor = a
        break

    # Safe defaults so template always renders.
    role = str((actor or {}).get("role", "agent") or "agent")
    action = str((actor or {}).get("current_action", (actor or {}).get("action", "idle")) or "idle")
    role_hint = str((actor or {}).get("role", "")).lower()
    if role_hint == "worker" and action == "idle":
      phase = str((actor or {}).get("worker_shift_phase", "") or "").strip().lower()
      if phase == "to_mine":
        action = "commuting_to_work"
      elif phase == "to_bank":
        action = "commuting_to_bank"
      elif phase == "to_home":
        action = "returning_home"
    elif role_hint == "cop" and action == "idle":
      cx = float((actor or {}).get("x", 0.0) or 0.0)
      cy = float((actor or {}).get("y", 0.0) or 0.0)
      tx_hint = float((actor or {}).get("target_x", cx) or cx)
      ty_hint = float((actor or {}).get("target_y", cy) or cy)
      if abs(tx_hint - cx) > 8.0 or abs(ty_hint - cy) > 8.0:
        top = str((actor or {}).get("top_action", "") or "").lower()
        if top in {"chase", "call_service"}:
          action = "responding"
        else:
          action = "patrolling"
    balance = float((actor or {}).get("balance", 0.0) or 0.0)
    home_storage = float((actor or {}).get("home_storage", 0.0) or 0.0)
    lifetime_collected = float((actor or {}).get("lifetime_collected", 0.0) or 0.0)
    lifetime_lost = float((actor or {}).get("lifetime_lost", 0.0) or 0.0)
    lifetime_net = float((actor or {}).get("lifetime_net", lifetime_collected - lifetime_lost) or (lifetime_collected - lifetime_lost))
    flow = str((actor or {}).get("flow", "No recent financial flow") or "No recent financial flow").strip() or "No recent financial flow"
    recent = (actor or {}).get("recent") if isinstance((actor or {}).get("recent"), list) else []
    recent_display = []
    for ev in recent[-5:]:
      if isinstance(ev, dict):
        summ = str(ev.get("summary") or ev.get("type") or "event").strip() or "event"
        recent_display.append(summ)
      elif isinstance(ev, str) and ev.strip():
        recent_display.append(ev.strip())

    dest_zone = str((actor or {}).get("dest_zone", "Unknown") or "Unknown")
    x = int(float((actor or {}).get("x", 0.0) or 0.0))
    y = int(float((actor or {}).get("y", 0.0) or 0.0))
    now = datetime.datetime.now().strftime("%B %d, %Y, %H:%M:%S")

    # Keep persona page schema compatible with existing template keys.
    first_name = persona_name_underscore.split("_")[0].capitalize() if persona_name_underscore else "Agent"
    last_name = persona_name_underscore.split("_")[-1] if "_" in persona_name_underscore else role.capitalize()
    scratch = {
      "first_name": first_name,
      "last_name": last_name,
      "age": "-",
      "curr_time": now,
      "curr_tile": f"({x}, {y}) -> {dest_zone}",
      "vision_r": "-",
      "att_bandwidth": "-",
      "retention": "-",
      "innate": role,
      "learned": "bridge-live",
      "currently": f"{action}",
      "lifestyle": f"Destination: {dest_zone}",
      "role": role,
      "action": action,
      "balance": round(balance, 6),
      "stored": round(home_storage, 6),
      "lifetime_collected": round(lifetime_collected, 6),
      "lifetime_lost": round(lifetime_lost, 6),
      "lifetime_net": round(lifetime_net, 6),
      "flow": flow,
      "recent_display": recent_display,
      "activity_location": f"({x}, {y}) -> {dest_zone}",
      "act_address": dest_zone,
      "act_start_time": now,
      "act_duration": "-",
      "act_description": action,
      "act_pronunciatio": role,
    }

    context = {
      "sim_code": sim_code,
      "step": step,
      "persona_name": persona_name,
      "persona_name_underscore": persona_name_underscore,
      "scratch": scratch,
      "spatial": {"bridge_live": True, "position": [x, y], "target": [x, y]},
      "a_mem_event": [],
      "a_mem_chat": [],
      "a_mem_thought": [],
    }
    template = "persona_state/persona_state.html"
    return render(request, template, context)

  memory = f"storage/{sim_code}/personas/{persona_name}/bootstrap_memory"
  if not os.path.exists(memory): 
    memory = f"compressed_storage/{sim_code}/personas/{persona_name}/bootstrap_memory"

  with open(memory + "/scratch.json") as json_file:  
    scratch = json.load(json_file)

  try:
    lc0 = float(scratch.get("lifetime_collected", 0) or 0)
    ll0 = float(scratch.get("lifetime_lost", 0) or 0)
    scratch["lifetime_net"] = round(float(scratch.get("lifetime_net", lc0 - ll0)), 6)
  except (TypeError, ValueError):
    scratch["lifetime_net"] = 0.0
  scratch.setdefault("activity_location", scratch.get("curr_tile") or "")
  rl = scratch.get("recent_lines")
  if isinstance(rl, list) and rl:
    scratch.setdefault("recent_display", [str(x) for x in rl if str(x).strip()])
  else:
    scratch.setdefault("recent_display", [])

  with open(memory + "/spatial_memory.json") as json_file:  
    spatial = json.load(json_file)

  with open(memory + "/associative_memory/nodes.json") as json_file:  
    associative = json.load(json_file)

  a_mem_event = []
  a_mem_chat = []
  a_mem_thought = []

  for count in range(len(associative.keys()), 0, -1): 
    node_id = f"node_{str(count)}"
    node_details = associative[node_id]

    if node_details["type"] == "event":
      a_mem_event += [node_details]

    elif node_details["type"] == "chat":
      a_mem_chat += [node_details]

    elif node_details["type"] == "thought":
      a_mem_thought += [node_details]
  
  context = {"sim_code": sim_code,
             "step": step,
             "persona_name": persona_name, 
             "persona_name_underscore": persona_name_underscore, 
             "scratch": scratch,
             "spatial": spatial,
             "a_mem_event": a_mem_event,
             "a_mem_chat": a_mem_chat,
             "a_mem_thought": a_mem_thought}
  template = "persona_state/persona_state.html"
  return render(request, template, context)


def path_tester(request):
  context = {}
  template = "path_tester/path_tester.html"
  return render(request, template, context)


def process_environment(request): 
  """
  <FRONTEND to BACKEND> 
  This sends the frontend visual world information to the backend server. 
  It does this by writing the current environment representation to 
  "storage/environment.json" file. 

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse: string confirmation message. 
  """
  # f_curr_sim_code = "temp_storage/curr_sim_code.json"
  # with open(f_curr_sim_code) as json_file:  
  #   sim_code = json.load(json_file)["sim_code"]

  data = json.loads(request.body)
  step = data["step"]
  sim_code = data["sim_code"]
  environment = data["environment"]

  with open(f"storage/{sim_code}/environment/{step}.json", "w") as outfile:
    outfile.write(json.dumps(environment, indent=2))

  return HttpResponse("received")


def bridge_smallville_snapshot(request):
  """Same-origin GET for Phaser boot: raw economy bridge JSON (actor x/y for spawns).

  The browser cannot call FastAPI on another port without CORS; this proxies the
  same payload Django already uses for bridge mode.
  """
  if request.method != "GET":
    return JsonResponse({"error": "method not allowed"}, status=405)
  if not BRIDGE_ENABLED:
    return JsonResponse({"actors": [], "events": [], "metrics": {}, "world": {}, "bridge_disabled": True})
  return JsonResponse(_bridge_fetch())


def bridge_force_cop_cycle(request):
  """Trigger backend demo cycle from in-sim UI button."""
  if request.method != "POST":
    return JsonResponse({"error": "method not allowed"}, status=405)
  if not BRIDGE_ENABLED:
    return JsonResponse({"ok": False, "error": "bridge mode disabled"}, status=400)

  raw_steps = request.GET.get("steps", "30")
  try:
    steps = int(raw_steps)
  except Exception:
    steps = 30
  steps = max(1, min(steps, 300))

  for base_url in [BRIDGE_URL, BRIDGE_FALLBACK_URL]:
    base = _bridge_api_base(base_url)
    if not base:
      continue
    try:
      trigger_url = f"{base}/api/demo/force-cop-cycle?steps={steps}"
      res = requests.post(trigger_url, timeout=45.0)
      if res.status_code == 200:
        payload = res.json()
        payload["ok"] = True
        payload["steps"] = steps
        return JsonResponse(payload)
    except Exception:
      continue
  return JsonResponse({"ok": False, "error": "force cycle trigger failed"}, status=502)


def bridge_tx_diagnostics(request):
  """Proxy tx diagnostics to frontend for judge bank panel."""
  if request.method != "GET":
    return JsonResponse({"error": "method not allowed"}, status=405)
  if not BRIDGE_ENABLED:
    return JsonResponse({"ok": False, "error": "bridge mode disabled"}, status=400)
  for base_url in [BRIDGE_URL, BRIDGE_FALLBACK_URL]:
    base = _bridge_api_base(base_url)
    if not base:
      continue
    try:
      res = requests.get(f"{base}/api/tx/diagnostics", timeout=8.0)
      if res.status_code == 200:
        payload = res.json()
        payload["ok"] = True
        return JsonResponse(payload)
    except Exception:
      continue
  return JsonResponse({"ok": False, "error": "tx diagnostics unavailable"}, status=502)


def bridge_tx_recent(request):
  """Proxy paginated on-chain tx rows for bank panel ledger."""
  if request.method != "GET":
    return JsonResponse({"error": "method not allowed"}, status=405)
  if not BRIDGE_ENABLED:
    return JsonResponse({"ok": False, "error": "bridge mode disabled"}, status=400)

  raw_page = request.GET.get("page", "1")
  raw_page_size = request.GET.get("page_size", "10")
  raw_max_records = request.GET.get("max_records", "50")
  try:
    page = max(1, int(raw_page))
  except Exception:
    page = 1
  try:
    page_size = max(1, min(50, int(raw_page_size)))
  except Exception:
    page_size = 10
  try:
    max_records = max(10, min(200, int(raw_max_records)))
  except Exception:
    max_records = 50

  for base_url in [BRIDGE_URL, BRIDGE_FALLBACK_URL]:
    base = _bridge_api_base(base_url)
    if not base:
      continue
    try:
      url = f"{base}/api/tx/recent?page={page}&page_size={page_size}&max_records={max_records}"
      res = requests.get(url, timeout=8.0)
      if res.status_code == 200:
        payload = res.json()
        payload["ok"] = True
        return JsonResponse(payload)
    except Exception:
      continue
  return JsonResponse({"ok": False, "error": "tx recent unavailable"}, status=502)


def bridge_reset_economy(request):
  """Reset baseline economy population + balances for demos."""
  if request.method != "POST":
    return JsonResponse({"error": "method not allowed"}, status=405)
  if not BRIDGE_ENABLED:
    return JsonResponse({"ok": False, "error": "bridge mode disabled"}, status=400)

  raw_start = request.GET.get("start_balance", "5")
  try:
    start_balance = float(raw_start)
  except Exception:
    start_balance = 5.0
  start_balance = max(0.0, min(start_balance, 100.0))

  for base_url in [BRIDGE_URL, BRIDGE_FALLBACK_URL]:
    base = _bridge_api_base(base_url)
    if not base:
      continue
    try:
      reset_url = f"{base}/api/demo/reset-economy?start_balance={start_balance}"
      res = requests.post(reset_url, timeout=45.0)
      if res.status_code == 200:
        payload = res.json()
        payload["ok"] = True
        return JsonResponse(payload)
    except Exception:
      continue
  return JsonResponse({"ok": False, "error": "reset failed"}, status=502)


def update_environment(request): 
  """
  <BACKEND to FRONTEND> 
  This sends the backend computation of the persona behavior to the frontend
  visual server. 
  It does this by reading the new movement information from 
  "storage/movement.json" file.

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse
  """
  # f_curr_sim_code = "temp_storage/curr_sim_code.json"
  # with open(f_curr_sim_code) as json_file:  
  #   sim_code = json.load(json_file)["sim_code"]

  data = json.loads(request.body)
  step = data["step"]
  sim_code = data["sim_code"]

  if BRIDGE_ENABLED and sim_code == BRIDGE_SIM_CODE:
    return JsonResponse(_bridge_update_payload(step))

  response_data = {"<step>": -1}
  if (check_if_file_exists(f"storage/{sim_code}/movement/{step}.json")):
    with open(f"storage/{sim_code}/movement/{step}.json") as json_file: 
      response_data = json.load(json_file)
      response_data["<step>"] = step

  return JsonResponse(response_data)


def path_tester_update(request): 
  """
  Processing the path and saving it to path_tester_env.json temp storage for 
  conducting the path tester. 

  ARGS:
    request: Django request
  RETURNS: 
    HttpResponse: string confirmation message. 
  """
  data = json.loads(request.body)
  camera = data["camera"]

  with open(f"temp_storage/path_tester_env.json", "w") as outfile:
    outfile.write(json.dumps(camera, indent=2))

  return HttpResponse("received")
