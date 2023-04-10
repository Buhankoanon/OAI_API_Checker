import discord
import openai
import aiohttp
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from discord.ext import commands

TOKEN = 'Your bot token here'

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')


@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')


@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(
        title="Bot Commands Help",
        description="These are the available commands for the bot:",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="!checkkeys",
        value="Usage:\n !checkkeys\n<API Key 1>\n<API Key 2>\n<API Key 3>\n...\n\nThis command checks the status and details of the OAI API keys. It can also detect keys with GPT-4 model and glitched keys.",
        inline=False
    )

    await ctx.send(embed=embed)


class OAIKeyChecker:
    desired_models = ["gpt-3.5-turbo", "gpt-3.5-turbo-0301", "gpt-4", "gpt-4-0314"]
    usage_endpoint = 'https://api.openai.com/dashboard/billing/usage'
    subscription_endpoint = 'https://api.openai.com/dashboard/billing/subscription'

    @staticmethod
    def list_models(api_key):
        openai.api_key = api_key
        models = openai.Model.list()
        return [model.id for model in models['data']]

    @staticmethod
    def filter_models(models):
        return [model for model in models if model in OAIKeyChecker.desired_models]

    @staticmethod
    async def get_limits(api_key):
        headers = {
            "authorization": f"Bearer {api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(OAIKeyChecker.subscription_endpoint, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Error fetching usage and limits: {response.text}")

    @staticmethod
    def is_glitched(access_until, total_usage, hard_limit_usd):
        current_timestamp = datetime.now().timestamp()
        return current_timestamp > access_until or float(total_usage) >= (hard_limit_usd + 1)

    @staticmethod
    async def get_usage(api_key, start_date, end_date):
        headers = {
            "authorization": f"Bearer {api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(OAIKeyChecker.usage_endpoint, headers=headers, params={'start_date': start_date, 'end_date': end_date}) as response:
                response.raise_for_status()
                usage_data = await response.json()
                total_usage = usage_data.get('total_usage', 0) / 100
                return '{:.2f}'.format(total_usage)


@bot.command(name='checkkeys')
async def checkkeys(ctx, *, keys_input: str = None):
    if keys_input:
        api_keys = [key.strip() for key in keys_input.splitlines() if key.strip()]
    else:
        api_keys = []

    # Add the start_date and end_date for the usage period
    start_date = (datetime.now() - timedelta(days=99)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    # Send a message to let the user know their request is being processed
    await ctx.send(f'{ctx.author.mention} Processing request...')

    # Initialize the lists to store API keys with "gpt-4" models and glitched keys
    gpt_4_keys = []
    glitched_keys = []

    # Run the API key checks and store the results in a string
    result = ''
    
    async def process_api_key(idx, api_key):
        result = f"API Key {idx}:\n"
        try:
            result += f"{api_key}\n"
            usage_and_limits = await OAIKeyChecker.get_limits(api_key)
            access_until = datetime.fromtimestamp(usage_and_limits['access_until'])
            total_usage_formatted = await OAIKeyChecker.get_usage(api_key, start_date, end_date)

            if OAIKeyChecker.is_glitched(usage_and_limits['access_until'], total_usage_formatted, usage_and_limits['hard_limit_usd']):
                result += "**!!!Possibly Glitched Key!!!**\n"
                glitched_keys.append(api_key)

            models = OAIKeyChecker.list_models(api_key)
            filtered_models = OAIKeyChecker.filter_models(models)

            if filtered_models:
                for model_id in filtered_models:
                    result += f"  - {model_id}\n"

                    if model_id == "gpt-4":
                        gpt_4_keys.append(api_key)
            else:
                result += "  No desired models available.\n"

            result += f"  Access valid until: {access_until.strftime('%Y-%m-%d %H:%M:%S')}\n"
            result += f"  Soft limit: {usage_and_limits['soft_limit']}\n"
            result += f"  Soft limit USD: {usage_and_limits['soft_limit_usd']}\n"
            result += f"  Hard limit: {usage_and_limits['hard_limit']}\n"
            result += f"  Hard limit USD: {usage_and_limits['hard_limit_usd']}\n"
            result += f"  System hard limit: {usage_and_limits['system_hard_limit']}\n"
            result += f"  System hard limit USD: {usage_and_limits['system_hard_limit_usd']}\n"
            result += f"  Total usage USD: {total_usage_formatted}\n"
        except Exception as e:
            result += f"  This key is invalid or revoked\n"
        result += '\n'
        return result

    async def run_concurrently(api_keys):
        with ThreadPoolExecutor() as executor:
            tasks = [asyncio.ensure_future(process_api_key(idx, api_key)) for idx, api_key in enumerate(api_keys, start=1)]
            results = await asyncio.gather(*tasks)
            return "".join(results)

    result = await run_concurrently(api_keys)

    result += f"\nNumber of API keys with 'gpt-4' model: {len(gpt_4_keys)}\n"
    for key in gpt_4_keys:
        result += f"  - {key}\n"

    result += f"\nNumber of possibly glitched API keys: {len(glitched_keys)}\n"
    for key in glitched_keys:
        result += f"  - {key}\n"

    # Group the information for each key
    key_information = result.split('\n\n')

    # Send the result to the Discord channel
    result_chunks = []
    current_chunk = ''

    for info in key_information:
        # Check if the info can be added to the current_chunk without exceeding the limit
        if len(current_chunk) + len(info) + 2 <= 1950:
            current_chunk += f"{info}\n\n"
        else:
            # If not, add the current_chunk to result_chunks and start a new chunk
            result_chunks.append(current_chunk)
            current_chunk = f"{info}\n\n"
    # Add the last chunk to result_chunks
    result_chunks.append(current_chunk)

    # Send the chunks to the Discord channel
    for idx, chunk in enumerate(result_chunks):
        if idx == 0:
            await ctx.send(f'{ctx.author.mention}\n```{chunk}```')
        else:
            await ctx.send(f'```{chunk}```')
            
# Run the bot
bot.run(TOKEN)