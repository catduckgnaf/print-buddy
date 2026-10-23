"""Standalone Discord bot: Print Buddy without Hermes and without an LLM (#73).

    python3 -m print_buddy.bot            run the bot (bot.mode must be standalone)
    python3 -m print_buddy.bot check      validate the setup offline, exit 1 on a problem
    python3 -m print_buddy.bot health     exit 0 only while a running bot reports a fresh heartbeat

The bot runs the same print-feedback handlers the Hermes gateway runs, in the same order, with
Print Buddy's own Discord adapter and prompt registry. Importing this package does not import
discord.py; only the runtime does.
"""
