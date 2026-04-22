"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: gpt_structure.py
Description: Wrapper functions for calling OpenAI APIs.
"""
import json
import random
import openai
import time 
import hashlib
import numpy as np

from utils import *

DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE)

SUPPORTED_PROVIDERS = {"deepseek", "openai", "local"}
RAW_PROVIDER = (llm_provider or "").strip().lower()
if RAW_PROVIDER not in SUPPORTED_PROVIDERS:
  RAW_PROVIDER = "deepseek" if DEEPSEEK_API_KEY else "local"
PROVIDER = RAW_PROVIDER

if PROVIDER == "deepseek":
  API_KEY = DEEPSEEK_API_KEY or llm_api_key
  BASE_URL = llm_base_url or DEEPSEEK_BASE_URL
  CHAT_MODEL = llm_chat_model or "deepseek-chat"
elif PROVIDER == "openai":
  API_KEY = openai_api_key or llm_api_key
  BASE_URL = llm_base_url or ""
  CHAT_MODEL = llm_chat_model or "gpt-3.5-turbo"
else:
  API_KEY = ""
  BASE_URL = ""
  CHAT_MODEL = "local-sim"

FORCE_REMOTE_EMBEDDINGS = os.getenv("FORCE_REMOTE_EMBEDDINGS", "0") == "1"

openai.api_key = API_KEY
if BASE_URL:
  openai.api_base = BASE_URL


def _provider_chat_model(requested_model):
  if PROVIDER == "openai" and requested_model and str(requested_model).strip():
    return requested_model
  return CHAT_MODEL


def _chat_completion(model, prompt):
  """
  Compatibility wrapper for both legacy openai<1 and modern openai>=1 SDKs.
  """
  if PROVIDER == "local":
    return "..."
  if not API_KEY:
    raise ValueError(f"Missing API key for provider '{PROVIDER}'")
  # Legacy SDK path.
  if hasattr(openai, "ChatCompletion") and hasattr(openai.ChatCompletion, "create"):
    model = _provider_chat_model(model)
    completion = openai.ChatCompletion.create(
      model=model,
      messages=[{"role": "user", "content": prompt}]
    )
    return completion["choices"][0]["message"]["content"]

  # Modern SDK path.
  try:
    from openai import OpenAI
    api_key = API_KEY
    base_url = BASE_URL or None
    client = OpenAI(api_key=api_key, base_url=base_url)
    model = _provider_chat_model(model)
    completion = client.chat.completions.create(
      model=model,
      messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content
  except Exception:
    raise

def temp_sleep(seconds=0.1):
  time.sleep(seconds)

def ChatGPT_single_request(prompt): 
  temp_sleep()
  return _chat_completion("gpt-3.5-turbo", prompt)


# ============================================================================
# #####################[SECTION 1: CHATGPT-3 STRUCTURE] ######################
# ============================================================================

def GPT4_request(prompt): 
  """
  Given a prompt and a dictionary of GPT parameters, make a request to OpenAI
  server and returns the response. 
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  temp_sleep()

  try: 
    return _chat_completion("gpt-4", prompt)
  
  except: 
    print ("ChatGPT ERROR")
    return "ChatGPT ERROR"


def ChatGPT_request(prompt): 
  """
  Given a prompt and a dictionary of GPT parameters, make a request to OpenAI
  server and returns the response. 
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  # temp_sleep()
  try: 
    return _chat_completion("gpt-3.5-turbo", prompt)
  
  except: 
    print ("ChatGPT ERROR")
    return "ChatGPT ERROR"


def GPT4_safe_generate_response(prompt, 
                                   example_output,
                                   special_instruction,
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  prompt = 'GPT-3 Prompt:\n"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'

  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 

    try: 
      curr_gpt_response = GPT4_request(prompt).strip()
      end_index = curr_gpt_response.rfind('}') + 1
      curr_gpt_response = curr_gpt_response[:end_index]
      curr_gpt_response = json.loads(curr_gpt_response)["output"]
      
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      
      if verbose: 
        print ("---- repeat count: \n", i, curr_gpt_response)
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass

  return False


def ChatGPT_safe_generate_response(prompt, 
                                   example_output,
                                   special_instruction,
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  # prompt = 'GPT-3 Prompt:\n"""\n' + prompt + '\n"""\n'
  prompt = '"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'

  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 

    try: 
      curr_gpt_response = ChatGPT_request(prompt).strip()
      end_index = curr_gpt_response.rfind('}') + 1
      curr_gpt_response = curr_gpt_response[:end_index]
      curr_gpt_response = json.loads(curr_gpt_response)["output"]

      # print ("---ashdfaf")
      # print (curr_gpt_response)
      # print ("000asdfhia")
      
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      
      if verbose: 
        print ("---- repeat count: \n", i, curr_gpt_response)
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass

  return False


def ChatGPT_safe_generate_response_OLD(prompt, 
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 
    try: 
      curr_gpt_response = ChatGPT_request(prompt).strip()
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      if verbose: 
        print (f"---- repeat count: {i}")
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass
  print ("FAIL SAFE TRIGGERED") 
  return fail_safe_response


# ============================================================================
# ###################[SECTION 2: ORIGINAL GPT-3 STRUCTURE] ###################
# ============================================================================

def GPT_request(prompt, gpt_parameter): 
  """
  Given a prompt and a dictionary of GPT parameters, make a request to OpenAI
  server and returns the response. 
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  temp_sleep()
  try:
    model = _provider_chat_model(gpt_parameter.get("engine", CHAT_MODEL))
    completion = openai.ChatCompletion.create(
      model=model,
      messages=[{"role": "user", "content": prompt}],
      temperature=gpt_parameter.get("temperature", 0.7),
      max_tokens=gpt_parameter.get("max_tokens", 256),
      top_p=gpt_parameter.get("top_p", 1),
      frequency_penalty=gpt_parameter.get("frequency_penalty", 0),
      presence_penalty=gpt_parameter.get("presence_penalty", 0),
      stop=gpt_parameter.get("stop", None),
    )
    return completion["choices"][0]["message"]["content"]
  except Exception:
    print("TOKEN LIMIT EXCEEDED")
    # Return empty so callers fall back to fail-safe planners instead of
    # trying to parse a literal error string.
    return ""


def generate_prompt(curr_input, prompt_lib_file): 
  """
  Takes in the current input (e.g. comment that you want to classifiy) and 
  the path to a prompt file. The prompt file contains the raw str prompt that
  will be used, which contains the following substr: !<INPUT>! -- this 
  function replaces this substr with the actual curr_input to produce the 
  final promopt that will be sent to the GPT3 server. 
  ARGS:
    curr_input: the input we want to feed in (IF THERE ARE MORE THAN ONE
                INPUT, THIS CAN BE A LIST.)
    prompt_lib_file: the path to the promopt file. 
  RETURNS: 
    a str prompt that will be sent to OpenAI's GPT server.  
  """
  if type(curr_input) == type("string"): 
    curr_input = [curr_input]
  curr_input = [str(i) for i in curr_input]

  f = open(prompt_lib_file, "r")
  prompt = f.read()
  f.close()
  for count, i in enumerate(curr_input):   
    prompt = prompt.replace(f"!<INPUT {count}>!", i)
  if "<commentblockmarker>###</commentblockmarker>" in prompt: 
    prompt = prompt.split("<commentblockmarker>###</commentblockmarker>")[1]
  return prompt.strip()


def safe_generate_response(prompt, 
                           gpt_parameter,
                           repeat=5,
                           fail_safe_response="error",
                           func_validate=None,
                           func_clean_up=None,
                           verbose=False): 
  if verbose: 
    print (prompt)

  for i in range(repeat): 
    curr_gpt_response = GPT_request(prompt, gpt_parameter)
    try:
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
    except Exception:
      # Badly formatted model outputs should never crash the simulation loop.
      pass
    if verbose: 
      print ("---- repeat count: ", i, curr_gpt_response)
      print (curr_gpt_response)
      print ("~~~~")
  return fail_safe_response


def _local_deterministic_embedding(text, dims=256):
  """
  Stable fallback embedding for non-OpenAI providers.
  """
  digest = hashlib.sha256(text.encode("utf-8")).digest()
  seed = int.from_bytes(digest[:8], "big", signed=False)
  rng = np.random.default_rng(seed)
  vec = rng.normal(0.0, 1.0, size=dims)
  norm = np.linalg.norm(vec)
  if norm == 0:
    return vec.tolist()
  return (vec / norm).tolist()


def get_embedding(text, model="text-embedding-ada-002"):
  text = text.replace("\n", " ")
  if not text: 
    text = "this is blank"
  # Use local deterministic embeddings by default for stability and provider neutrality.
  # Only use remote embeddings when explicitly enabled on OpenAI provider.
  if (not FORCE_REMOTE_EMBEDDINGS) or PROVIDER != "openai":
    return _local_deterministic_embedding(text)
  if not API_KEY:
    return _local_deterministic_embedding(text)
  return openai.Embedding.create(input=[text], model=model)['data'][0]['embedding']


if __name__ == '__main__':
  gpt_parameter = {"engine": "text-davinci-003", "max_tokens": 50, 
                   "temperature": 0, "top_p": 1, "stream": False,
                   "frequency_penalty": 0, "presence_penalty": 0, 
                   "stop": ['"']}
  curr_input = ["driving to a friend's house"]
  prompt_lib_file = "prompt_template/test_prompt_July5.txt"
  prompt = generate_prompt(curr_input, prompt_lib_file)

  def __func_validate(gpt_response): 
    if len(gpt_response.strip()) <= 1:
      return False
    if len(gpt_response.strip().split(" ")) > 1: 
      return False
    return True
  def __func_clean_up(gpt_response):
    cleaned_response = gpt_response.strip()
    return cleaned_response

  output = safe_generate_response(prompt, 
                                 gpt_parameter,
                                 5,
                                 "rest",
                                 __func_validate,
                                 __func_clean_up,
                                 True)

  print (output)












