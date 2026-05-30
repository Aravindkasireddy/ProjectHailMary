#!/usr/bin/env python3
"""
Discord Bot command listener for MAAS jobsearch.
Listens for commands like !scrape, !status, and !check-stale to trigger pipeline actions.
"""
import os
import sys
import json
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path

# Resolve pathing
_scripts_dir = Path(__file__).resolve().parent
_repo_root = _scripts_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from jobsearch_paths import workspace_root

WORKSPACE = workspace_root()
load_dotenv(dotenv_path=str(WORKSPACE / ".env"))

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_LIMIT = os.getenv("DISCORD_CHANNEL_ID", "").strip()
PORT = os.getenv("JOBSEARCH_DASHBOARD_PORT", "8080")
API_BASE = f"http://localhost:{PORT}"

if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable not set in .env.", file=sys.stderr)
    print("Please set DISCORD_BOT_TOKEN and rerun.", file=sys.stderr)
    sys.exit(1)

# Configure bot intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.check
async def restrict_channel(ctx):
    """Globally restrict bot commands to the specified channel if DISCORD_CHANNEL_ID is set."""
    if CHANNEL_LIMIT:
        is_allowed = str(ctx.channel.id) == CHANNEL_LIMIT
        if not is_allowed:
            # Silently ignore commands outside target channel
            return False
    return True

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})", flush=True)
    print(f"Connecting to backend dashboard server at: {API_BASE}", flush=True)
    if CHANNEL_LIMIT:
        print(f"Commands are locked strictly to channel ID: {CHANNEL_LIMIT}", flush=True)

@bot.command(name="help")
async def help_cmd(ctx):
    """Show available commands."""
    help_text = (
        "⚙️ **MAAS Job Sourcing Agent Commands**\n"
        "• `!scrape` — Trigger the background job scraper (discover and parse new jobs).\n"
        "• `!status` — Check the current status of the scraper and stale checker.\n"
        "• `!check-stale` — Start verification scan of approved postings for closed/stale links.\n"
        "• `!help` — Display this help overview."
    )
    await ctx.send(help_text)

@bot.command(name="scrape")
async def scrape_cmd(ctx):
    """Trigger backend scraper."""
    await ctx.send("🔄 Sending request to launch Job Sourcing Agent...")
    try:
        r = requests.post(f"{API_BASE}/api/scrape", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                await ctx.send("🚀 **Job Sourcing Agent started successfully in the background!** I'll fetch and process postings.")
            else:
                await ctx.send(f"⚠️ Sourcing Agent is already running: *{data.get('message')}*")
        else:
            await ctx.send(f"❌ Failed to reach backend API. Server returned code {r.status_code}.")
    except Exception as e:
        await ctx.send(f"❌ Error communicating with backend server: `{str(e)}`. Make sure the dashboard server is running.")

@bot.command(name="check-stale")
async def check_stale_cmd(ctx):
    """Trigger backend stale check."""
    await ctx.send("🔍 Sending request to launch Stale Job Checker...")
    try:
        r = requests.post(f"{API_BASE}/api/check-stale", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                await ctx.send("🔎 **Stale Job Checker launched successfully!** Scanning approved job postings in background...")
            else:
                await ctx.send(f"⚠️ Stale checker is already running: *{data.get('message')}*")
        else:
            await ctx.send(f"❌ Failed to reach backend API. Server returned code {r.status_code}.")
    except Exception as e:
        await ctx.send(f"❌ Error communicating with backend server: `{str(e)}`. Make sure the dashboard server is running.")

@bot.command(name="status")
async def status_cmd(ctx):
    """Check current scraper and checker status."""
    try:
        # Fetch scraper status
        scraper_msg = "Unknown"
        scraper_status = "idle"
        r_scr = requests.get(f"{API_BASE}/api/scraper-status", timeout=10)
        if r_scr.status_code == 200:
            scr_data = r_scr.json()
            scraper_status = scr_data.get("status", "idle")
            scraper_msg = scr_data.get("message", "")

        # Fetch stale check status
        stale_status = "idle"
        stale_progress = 0
        stale_completed = 0
        stale_total = 0
        stale_found = 0
        r_stl = requests.get(f"{API_BASE}/api/stale-status", timeout=10)
        if r_stl.status_code == 200:
            stl_data = r_stl.json()
            stale_status = stl_data.get("status", "idle")
            stale_progress = stl_data.get("progress", 0)
            stale_completed = stl_data.get("completed", 0)
            stale_total = stl_data.get("total", 0)
            stale_found = stl_data.get("stale_found", 0)

        # Build response message
        status_text = (
            "🤖 **MAAS Sourcing Agent Status**\n"
            f"• **Scraper Status**: `{scraper_status}`\n"
            f"• **Current activity**: *{scraper_msg}*\n\n"
            "🔍 **Stale Job Checker Status**\n"
            f"• **Checker Status**: `{stale_status}`\n"
        )
        
        if stale_status == "running":
            status_text += (
                f"• **Progress**: `{stale_progress}%` ({stale_completed}/{stale_total})\n"
                f"• **Stale postings found so far**: `{stale_found}`\n"
            )
        else:
            status_text += f"• **Last scan finished**. Total stale postings flagged: `{stale_found}` (out of {stale_total})\n"

        await ctx.send(status_text)
    except Exception as e:
        await ctx.send(f"❌ Error communicating with backend server: `{str(e)}`. Make sure the dashboard server is running.")

if __name__ == "__main__":
    print("Starting Discord Bot command listener...", flush=True)
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("Login failed: The provided Discord token is invalid.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error launching Discord bot: {e}", file=sys.stderr)
        sys.exit(1)
