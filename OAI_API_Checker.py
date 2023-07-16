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
from math import ceil

colorama.init()

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

def get_total_usage(api_key, plan_id, retry_count=3):
    if plan_id == "free":
        start_date = (datetime.now() - timedelta(days=99)).strftime('%Y-%m-%d')
    elif plan_id == "payg":
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    else:
        raise ValueError(f"Invalid plan ID: {plan_id}")

    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
  
    usage_endpoint = 'https://api.openai.com/dashboard/billing/usage'
    auth_header = {'Authorization': f'Bearer {api_key}'}
    
    for attempt in range(retry_count):
        try:
            response = requests.get(usage_endpoint, headers=auth_header, params={'start_date': start_date, 'end_date': end_date})
            response.raise_for_status()
            usage_data = response.json()
            total_usage = usage_data.get('total_usage', 0) / 100
            total_usage_formatted = '{:.2f}'.format(total_usage)
            return total_usage_formatted
        except requests.exceptions.HTTPError as http_err:
            if '500 Server Error' in str(http_err) or '429 Client Error' in str(http_err):
                logging.info(f'Error encountered at getting usage on attempt {attempt+1}: {str(http_err)}. Retrying...')
                time.sleep(5)
                continue
            else:
                raise http_err
        except Exception as err:
            raise err
    raise Exception(f"Failed to retrieve total usage after {retry_count} attempts")

def is_glitched(api_key, usage_and_limits, plan_id, total_usage_formatted):
    current_timestamp = datetime.now().timestamp()
    
    if plan_id == "payg":
        access_expired = False
    else:
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

RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLINK = "\033[5m"
RESET = "\033[0m"

def check_key(api_key, retry_count=3):
    result = f"{api_key}\n"
    has_gpt_4_32k = False
    glitched = False
    model_ids = []
    errors = []
    
    usage_and_limits = get_limits(api_key)
    plan_title = usage_and_limits.get('plan', {}).get('title')
    plan_id = usage_and_limits.get('plan', {}).get('id')
    if not plan_id:
        raise ValueError("Plan ID not found in usage_and_limits")
    total_usage_formatted = get_total_usage(api_key, plan_id)
    access_until = datetime.fromtimestamp(usage_and_limits['access_until'])
    org_id = usage_and_limits.get('account_name', '')
    
    models = list_models(api_key)
    filtered_models = filter_models(models, desired_models)

    if filtered_models:
        for model_id in filtered_models:
            result += f"  - {model_id}\n"
            model_ids.append(model_id)
    else:
        result += "  No desired models available.\n"
    
    has_gpt_4 = "gpt-4" in model_ids
    has_gpt_4_32k = "gpt-4-32k" in model_ids
    has_only_turbo = "gpt-3.5-turbo" in model_ids and not has_gpt_4
    
    try:
        for attempts in range(retry_count):
            try:
                try_complete(api_key)
                break
            except Exception as e:
                error_message = str(e)
                if "The server is overloaded or not ready yet" in error_message:
                    logging.info(f'Error encountered when generating a completion on attempt {attempts+1}: {error_message}. Retrying...')
                    time.sleep(5)
                    continue
                else:
                    raise e

        glitched = is_glitched(api_key, usage_and_limits, plan_id, total_usage_formatted)
        if glitched:
            result += f"{GREEN}{BLINK}**!!!Possibly Glitched Key!!!**{RESET}\n"

        result += f"  Access valid until: {access_until.strftime('%Y-%m-%d %H:%M:%S')}\n"
        result += f"  Soft limit USD: {usage_and_limits['soft_limit_usd']}\n"
        result += f"  Hard limit USD: {usage_and_limits['hard_limit_usd']}\n"
        result += f"  System hard limit USD: {usage_and_limits['system_hard_limit_usd']}\n"
        result += f"  Plan: {plan_title}, {plan_id}\n"
        result += f"  OrgID: {org_id}\n"
        result += f"  Total usage USD: {total_usage_formatted}\n"
    except Exception as e:
        error_message = str(e)
        if "You exceeded your current quota" in error_message:
            result += f"{YELLOW}  This key has exceeded its current quota{RESET}\n"
            result += f"  Access valid until: {access_until.strftime('%Y-%m-%d %H:%M:%S')}\n"
            result += f"  Hard limit USD: {usage_and_limits['hard_limit_usd']}\n"
            result += f"  System hard limit USD: {usage_and_limits['system_hard_limit_usd']}\n"
            result += f"  Plan: {plan_title}, {plan_id}\n"
            result += f"  OrgID: {org_id}\n"
            result += f"  Total usage USD: {total_usage_formatted}\n"
        elif "Your account is not active" in error_message:
            result += f"{RED} Error: Your account is not active, please check your billing details on our website.{RESET}\n"
        else:
            result += f"{RED} Unexpected Error at check_key: {error_message}{RESET}\n"
            errors.append((api_key, error_message))

    return result, glitched, has_gpt_4, has_gpt_4_32k, has_only_turbo, org_id, float(usage_and_limits['hard_limit_usd']), float(total_usage_formatted), errors

def checkkeys(api_keys):
    working_gpt_4_keys = set()
    no_quota_gpt_4_keys = set()
    working_gpt_4_32k_keys = set()
    no_quota_gpt_4_32k_keys = set()
    working_only_turbo_keys = set()
    no_quota_only_turbo_keys = set()
    glitched_gpt4_keys = set()
    glitched_gpt4_32k_keys = set()
    glitched_turbo_keys = set()
    result = ''
    balances = []
    keys_by_limit = {}
    total_errors = []
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(check_key, api_key) for api_key in api_keys]

        for idx, future in enumerate(futures, start=1):
            result += f"API Key {idx}:\n"
            key = api_keys[idx - 1]
            try:
                key_result, glitched, has_gpt_4, has_gpt_4_32k, has_only_turbo, org_id, limit, usage, errors = future.result()
                total_errors.extend(errors)
                balance = max(limit - usage, 0)
                balances.append(balance)

                limit = ceil(limit / 10) * 10
                
                result += key_result

                if has_only_turbo and "Error" not in key_result and "This key has exceeded its current quota" not in key_result and "This key is invalid or revoked" not in key_result:
                    working_only_turbo_keys.add(key)
                if has_gpt_4 and not has_gpt_4_32k and "Error" not in key_result and "This key has exceeded its current quota" not in key_result and "This key is invalid or revoked" not in key_result:
                    working_gpt_4_keys.add(key)
                if has_gpt_4_32k and "Error" not in key_result and "This key has exceeded its current quota" not in key_result and "This key is invalid or revoked" not in key_result:
                    working_gpt_4_32k_keys.add(key)

                if has_only_turbo and "This key has exceeded its current quota" in key_result:
                    no_quota_only_turbo_keys.add(key)
                if has_gpt_4 and "This key has exceeded its current quota" in key_result:
                    no_quota_gpt_4_keys.add(key)
                if has_gpt_4_32k and "This key has exceeded its current quota" in key_result:
                    no_quota_gpt_4_32k_keys.add(key)

                if "Error" not in key_result and "This key has exceeded its current quota" not in key_result and "This key is invalid or revoked" not in key_result:
                    limit_key = limit * 10 + (4 if has_gpt_4 else 3)
                    same_limit_keys = keys_by_limit.get(limit_key, [])
                    same_limit_keys.append(key)
                    keys_by_limit[limit_key] = same_limit_keys

                if glitched and has_gpt_4:
                    glitched_gpt4_keys.add(key)
                if glitched and has_gpt_4 and has_gpt_4_32k:
                    glitched_gpt4_32k_keys.add(key)
                if glitched and has_only_turbo:
                    glitched_turbo_keys.add(key)

            except Exception as e:
                error_message = str(e)
                if "Incorrect API key provided" in error_message:
                    result += f"{key}\n"
                    result += f"{RED}  This key is invalid or revoked{RESET}\n"
                elif "You must be a member of an organization to use the API" in error_message:
                    result += f"{key}\n"
                    result += f"{RED} Error: You must be a member of an organization to use the API. Please contact us through our help center at help.openai.com.{RESET}\n"
                elif "This key is associated with a deactivated account" in error_message:
                    result += f"{key}\n"
                    result += f"{RED} Error: This key is associated with a deactivated account. If you feel this is an error, contact us through our help center at help.openai.com.{RESET}\n"
                else:
                    result += f"{RED} Unexpected Error at checkkeys: {error_message}{RESET}\n"
                    total_errors.append((api_keys[idx - 1], error_message))
            result += '\n'

    with open('turbo.txt', 'w') as f:
        if len(glitched_turbo_keys) > 0:
            f.write('Glitched API keys with GPT-3.5-Turbo model:\n')
            f.write('\n'.join(glitched_turbo_keys) + '\n\n')
        if len(working_only_turbo_keys) > 0:
            f.write('Working API keys with GPT-3.5-Turbo model:\n')
            f.write('\n'.join(working_only_turbo_keys) + '\n\n')
        if len(no_quota_only_turbo_keys) > 0:    
            f.write('Valid API keys with GPT-3.5-Turbo model and no quota left:\n')
            f.write('\n'.join(no_quota_only_turbo_keys) + '\n\n')

    with open('gpt4.txt', 'w') as f:
        if len(glitched_gpt4_32k_keys) > 0:
            f.write('Glitched API keys with GPT-4-32K model:\n')
            f.write('\n'.join(glitched_gpt4_32k_keys) + '\n\n')
        if len(glitched_gpt4_keys) > 0:
            f.write('Glitched API keys with GPT-4 model:\n')
            f.write('\n'.join(glitched_gpt4_keys) + '\n\n')
        if len(working_gpt_4_32k_keys) > 0:
            f.write('Working API keys with GPT-4-32k model:\n')
            f.write('\n'.join(working_gpt_4_32k_keys) + '\n\n')
        if len(no_quota_gpt_4_32k_keys) > 0:
            f.write('Valid API keys with GPT-4-32k model and no quota left:\n')
            f.write('\n'.join(no_quota_gpt_4_32k_keys) + '\n\n')
        if len(working_gpt_4_keys) > 0:
            f.write('Working API keys with GPT-4 model:\n')
            f.write('\n'.join(working_gpt_4_keys) + '\n\n')
        if len(no_quota_gpt_4_keys) > 0:
            f.write('Valid API keys with GPT-4 model and no quota left:\n')
            f.write('\n'.join(no_quota_gpt_4_keys) + '\n\n')

    with open('limits.txt', 'w') as f:
        for limit, same_limit_keys in sorted(keys_by_limit.items(), key=lambda x: x[0]):
            f.write(f'{limit}:\n')
            f.write('\n'.join(same_limit_keys))
            f.write(f'\n\n')

    with open('unexpected_errors.txt', 'w') as f:
        for i, (api_key, error) in enumerate(total_errors, start=1):
            f.write(f"Error #{i}:\n")
            f.write(f"API Key: {api_key}\n")
            f.write(f"Error Message: {error}\n\n")

    result += f"\nNumber of working API keys with only 'gpt-3.5-turbo' model: {len(working_only_turbo_keys)}\n"
    for key in working_only_turbo_keys:
        result += f"{key}\n"
    result += f"\nNumber of working API keys with 'gpt-4' model: {len(working_gpt_4_keys)}\n"
    for key in working_gpt_4_keys:
        result += f"{key}\n"
    result += f"\nNumber of working API keys with 'gpt-4-32k' model: {len(working_gpt_4_32k_keys)}\n"
    for key in working_gpt_4_32k_keys:
        result += f"{key}\n"
    result += f"\nNumber of possibly glitched API keys with only 'gpt-3.5-turbo' model: {len(glitched_turbo_keys)}\n"
    for key in glitched_turbo_keys:
        result += f"{key}\n"
    result += f"\nNumber of possibly glitched API keys with 'gpt-4' model: {len(glitched_gpt4_keys)}\n"
    for key in glitched_gpt4_keys:
        result += f"{key}\n"
    result += f"\nNumber of possibly glitched API keys with 'gpt-4-32k' model: {len(glitched_gpt4_32k_keys)}\n"
    for key in glitched_gpt4_32k_keys:
        result += f"{key}\n"
    result += f"\nNumber of valid API keys with only 'gpt-3.5-turbo' model and NO quota left: {len(no_quota_only_turbo_keys)}\n"
    for key in no_quota_only_turbo_keys:
        result += f"{key}\n"
    result += f"\nNumber of valid API keys with 'gpt-4' model and NO quota left: {len(no_quota_gpt_4_keys)}\n"
    for key in no_quota_gpt_4_keys:
        result += f"{key}\n"
    result += f"\nNumber of valid API keys with 'gpt-4-32k' model and NO quota left: {len(no_quota_gpt_4_32k_keys)}\n"
    for key in no_quota_gpt_4_32k_keys:
        result += f"{key}\n"    
    great_total = sum(balances)
    result += f"\nTotal limit: {great_total:.2f}\n"
    
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
    desired_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4-32k"]
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