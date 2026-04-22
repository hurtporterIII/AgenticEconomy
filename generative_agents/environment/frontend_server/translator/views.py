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
BRIDGE_STEP_ON_POLL = os.getenv("SMALLVILLE_BRIDGE_STEP_ON_POLL", "1") == "1"
SMALLVILLE_MODE = os.getenv("SMALLVILLE_MODE", "native").strip().lower()
BRIDGE_ENABLED = SMALLVILLE_MODE == "bridge"
TILE_SIZE = 32
# Keep backend destination labels verbatim so role hubs match on-map building titles.
LOCATION_ALIASES = {}


def _bridge_step_once(url):
  try:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    step_url = f"{base}/api/step"
    requests.post(step_url, timeout=2.0)
  except Exception:
    pass


def _bridge_fetch():
  if not BRIDGE_ENABLED:
    return {"actors": [], "events": [], "metrics": {}, "world": {}}
  if BRIDGE_STEP_ON_POLL:
    _bridge_step_once(BRIDGE_URL)
    _bridge_step_once(BRIDGE_FALLBACK_URL)
  for idx, url in enumerate([BRIDGE_URL, BRIDGE_FALLBACK_URL]):
    try:
      res = requests.get(url, timeout=2.5)
      if res.status_code == 200:
        payload = res.json()
        actors = payload.get("actors", [])
        # If primary responds but is effectively empty, try fallback once.
        if idx == 0 and not actors:
          continue
        return payload
    except Exception:
      continue
  return {"actors": [], "events": [], "metrics": {}, "world": {}}


def _bridge_persona_lists(bridge_data):
  persona_names = []
  persona_init_pos = []
  for actor in bridge_data.get("actors", []):
    actor_id = str(actor.get("id", "")).strip()
    if not actor_id:
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
    # Use live current position for rendering movement.
    px_x = int(float(actor.get("x", 0.0) or 0.0))
    px_y = int(float(actor.get("y", 0.0) or 0.0))
    action = str(actor.get("action", "idle"))
    role = str(actor.get("role", "resident"))
    reflection = str(actor.get("reflection", "neutral"))
    raw_dest_zone = str(actor.get("dest_zone", "district"))
    dest_zone = LOCATION_ALIASES.get(raw_dest_zone, raw_dest_zone)
    # In bridge mode, renderer pathing must follow backend movement target,
    # otherwise it fights role destination hints and causes "walk-by" behavior.
    dest_x = float(actor.get("target_x", actor.get("dest_x", actor.get("x", 0.0))) or 0.0)
    dest_y = float(actor.get("target_y", actor.get("dest_y", actor.get("y", 0.0))) or 0.0)
    persona[actor_id] = {
      "movement": [px_x, px_y],
      "pronunciatio": reflection,
      "description": f"{action}@{dest_zone}",
      "chat": None,
      "dest_zone": dest_zone,
      "dest_x": int(dest_x),
      "dest_y": int(dest_y),
      "role": role,
    }

  return {
    "<step>": int(step),
    "meta": {
      "curr_time": now,
      "bridge_tick": world.get("tick", 0),
      "regime": world.get("regime", "balanced"),
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
  memory = f"storage/{sim_code}/personas/{persona_name}/bootstrap_memory"
  if not os.path.exists(memory): 
    memory = f"compressed_storage/{sim_code}/personas/{persona_name}/bootstrap_memory"

  with open(memory + "/scratch.json") as json_file:  
    scratch = json.load(json_file)

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
