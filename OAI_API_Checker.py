# -*- coding: utf-8 -*-
import openai
import requests
from datetime import datetime, timedelta
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import colorama
import logging

colorama.init()

# Configure logging settings
logging.basicConfig(filename='OAI_API_Checker_logs.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def log_and_print(message, log_level=logging.INFO):
    print(message)
    logging.log(log_level, message)    

def list_models(api_key):
    openai.api_key = api_key
    models = openai.Model.list()
    return [model.id for model in models['data']]

def filter_models(models, desired_models):
    return [model for model in models if model in desired_models]

def get_limits(api_key):
    headers = {
        "authorization": f"Bearer {api_key}",
    }
    response = requests.get("https://api.openai.com/dashboard/billing/subscription", headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error fetching limits: {response.text}")

def get_total_usage(api_key, plan_id):
    if plan_id == "free":
        start_date = (datetime.now() - timedelta(days=99)).strftime('%Y-%m-%d')
    elif plan_id == "payg":
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    else:
        raise ValueError(f"Invalid plan ID: {plan_id}")

    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    usage_endpoint = 'https://api.openai.com/dashboard/billing/usage'
    auth_header = {'Authorization': f'Bearer {api_key}'}
    response = requests.get(usage_endpoint, headers=auth_header, params={'start_date': start_date, 'end_date': end_date})
    response.raise_for_status()
    usage_data = response.json()
    total_usage = usage_data.get('total_usage', 0) / 100
    total_usage_formatted = '{:.2f}'.format(total_usage)
    return total_usage_formatted

def is_glitched(api_key, usage_and_limits, plan_id):
    current_timestamp = datetime.now().timestamp()
    access_expired = current_timestamp > usage_and_limits['access_until']
    total_usage_formatted = get_total_usage(api_key, plan_id)
    usage_exceeded = float(total_usage_formatted) > float(usage_and_limits['hard_limit_usd']) + 10
    return access_expired or usage_exceeded
      
def try_complete(api_key):
    openai.api_key = api_key
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        max_tokens=1,
        messages=[{'role':'user', 'content': ''}]
    )

def check_key(api_key):
    result = f"{api_key}\n"
    glitched = False
    model_ids = []
    try:
        try_complete(api_key)
        usage_and_limits = get_limits(api_key)
        plan_title = usage_and_limits.get('plan', {}).get('title')
        plan_id = usage_and_limits.get('plan', {}).get('id')
        if not plan_id:
            raise ValueError("Plan ID not found in usage_and_limits")
        total_usage_formatted = get_total_usage(api_key, plan_id)
        access_until = datetime.fromtimestamp(usage_and_limits['access_until'])
        
        RED = "\033[31m"
        BLINK = "\033[5m"
        RESET = "\033[0m"

        glitched = is_glitched(api_key, usage_and_limits, plan_id)
        if glitched:
            result += f"{RED}{BLINK}**!!!Possibly Glitched Key!!!**{RESET}\n"

        models = list_models(api_key)
        filtered_models = filter_models(models, desired_models)

        if filtered_models:
            for model_id in filtered_models:
                result += f"  - {model_id}\n"
                model_ids.append(model_id)
        else:
            result += "  No desired models available.\n"

        result += f"  Access valid until: {access_until.strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"  Soft limit: {usage_and_limits['soft_limit']}\n"
        result += f"  Soft limit USD: {usage_and_limits['soft_limit_usd']}\n"
        result += f"  Hard limit: {usage_and_limits['hard_limit']}\n"
        result += f"  Hard limit USD: {usage_and_limits['hard_limit_usd']}\n"
        result += f"  System hard limit: {usage_and_limits['system_hard_limit']}\n"
        result += f"  System hard limit USD: {usage_and_limits['system_hard_limit_usd']}\n"
        result += f"  Plan: {plan_title}, {plan_id}\n"
        result += f"  Total usage USD: {total_usage_formatted}\n"
    except Exception as e:
        error_message = str(e)
        if "You exceeded your current quota" in error_message:
            result += f"  This key has exceeded its current quota\n"
        else:
            result += f"  This key is invalid or revoked\n"

    return result, glitched, "gpt-4" in model_ids    

def checkkeys(api_keys):
    gpt_4_keys = set()
    glitched_keys = set()
    valid_keys = set()
    no_quota_keys = set()

    result = ''
    with ThreadPoolExecutor(max_workers=len(api_keys)) as executor:
        futures = [executor.submit(check_key, api_key) for api_key in api_keys]

        for idx, future in enumerate(futures, start=1):
            result += f"API Key {idx}:\n"
            try:
                key_result, glitched, has_gpt_4 = future.result()
                result += key_result

                if "This key is invalid or revoked" not in key_result and "This key has exceeded its current quota" not in key_result:
                    valid_keys.add(api_keys[idx - 1])

                if "This key has exceeded its current quota" in key_result:
                    no_quota_keys.add(api_keys[idx - 1])

                if glitched:
                    glitched_keys.add(api_keys[idx - 1])
                if has_gpt_4:
                    gpt_4_keys.add(api_keys[idx - 1])
            except Exception as e:
                error_message = str(e)
                if "You exceeded your current quota" in error_message:
                    result += f"  This key has exceeded its current quota\n"
                else:
                    result += f"  This key is invalid or revoked\n"
            result += '\n'
            
    with open('valid.txt', 'w') as f: f.write('\n'.join(valid_keys))
    with open('glitch.txt', 'w') as f: f.write('\n'.join(glitched_keys))
    with open('gpt4.txt', 'w') as f: f.write('\n'.join(gpt_4_keys))

    result += f"\nNumber of API keys with 'gpt-4' model: {len(gpt_4_keys)}\n"
    for key in gpt_4_keys:
        result += f"{key}\n"

    result += f"\nNumber of possibly glitched API keys: {len(glitched_keys)}\n"
    for key in glitched_keys:
        result += f"{key}\n"

    result += f"\nNumber of valid API keys: {len(valid_keys)}\n"
    for key in valid_keys:
        result += f"{key}\n"
    
    result += f"\nNumber of valid API keys with no quota left: {len(no_quota_keys)}\n"
    for key in no_quota_keys:
        result += f"{key}\n"
    
    return result

def animate_processing_request():
    while not processing_done:
        sys.stdout.write("\rProcessing... |")
        time.sleep(0.1)
        sys.stdout.write("\rProcessing... /")
        time.sleep(0.1)
        sys.stdout.write("\rProcessing... -")
        time.sleep(0.1)
        sys.stdout.write("\rProcessing... \\")
        time.sleep(0.1)
    sys.stdout.write("\rDone!          \n")

if __name__ == '__main__':
    api_keys = []
    desired_models = ["gpt-3.5-turbo", "gpt-3.5-turbo-0301", "gpt-4", "gpt-4-0314"]
    log_and_print("Enter the API keys (one key per line). Press Enter twice when you're done:")
    while True:
        try:
            api_key = input()
        except:
            break

        if not api_key:
            break
        api_keys.append(api_key.strip())

    processing_done = False
    animation_thread = threading.Thread(target=animate_processing_request)
    animation_thread.start()

    result = checkkeys(api_keys)

    processing_done = True
    animation_thread.join()
    
    log_and_print("\n" + result)

    input("Press Enter to exit...")