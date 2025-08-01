import logging
import asyncio
import sys
from datetime import time

import pytz
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN, DEFAULT_RPC_URL
from data_manager import load_user_data
from monitoring import MONITOR_TASKS, start_monitoring_task
from bot_commands import (
    start, help_command, scan, chart, balance, price, tokeninfo,
    monitor, unmonitor, list_monitors,
    add_address, remove_address, list_addresses,
    schedule, unschedule, list_schedules,
    set_rpc, get_rpc, reset_rpc, scheduled_scan_callback,
    button_callback_handler, text_handler, cancel
)

# --- Logging and event loop setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
else:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        logger.warning("uvloop not available, using default event loop policy")


# --- Main bot setup ---
async def set_bot_commands(application: Application):
    """Sets the bot's command list and restores jobs."""
    commands = [
        BotCommand("start", "🚀 Start bot / Show main menu"),
        BotCommand("help", "❓ Help with all commands"),
        BotCommand("cancel", "❌ Cancel current operation"),
        BotCommand("scan", "🔍 Scan transactions"),
        BotCommand("chart", "📊 Chart volume"),
        BotCommand("balance", "💰 Check wallet balance"),
        BotCommand("price", "💹 Get token price"),
        BotCommand("tokeninfo", "ℹ️ Get token info"),
        BotCommand("monitor", "📡 Monitor a wallet"),
        BotCommand("add", "✍️ Save an address"),
        BotCommand("list", "📚 List saved addresses"),
    ]
    await application.bot.set_my_commands(commands)

    # --- Reschedule jobs on startup ---
    logger.info("Checking for schedules and monitors to restore...")
    all_user_data = load_user_data()
    
    # Restore schedules
    job_queue = application.job_queue
    for chat_id_str, user_data in all_user_data.items():
        chat_id = int(chat_id_str)
        schedules = user_data.get("schedules", {})
        for alias, details in schedules.items():
            try:
                scan_time = time.fromisoformat(details["time"]).replace(tzinfo=pytz.UTC)
                address = details["address"]
                job_name = f"scan_{chat_id}_{alias}"
                job_queue.run_daily(
                    scheduled_scan_callback, time=scan_time, chat_id=chat_id, user_id=chat_id, name=job_name,
                    data={"chat_id": chat_id, "alias": alias, "address": address}
                )
                logger.info(f"Restored schedule for '{alias}' for chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to restore schedule for '{alias}' (chat {chat_id}): {e}")

    # Restore monitors
    for chat_id_str, user_data in all_user_data.items():
        chat_id = int(chat_id_str)
        monitors = user_data.get("monitors", {})
        for address in monitors.keys():
            if (chat_id, address) not in MONITOR_TASKS:
                task = asyncio.create_task(start_monitoring_task(application, chat_id, address))
                MONITOR_TASKS[(chat_id, address)] = task


def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN not found. "
            "Please create a .env file and add your token to it."
        )
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data["default_rpc_url"] = DEFAULT_RPC_URL

    # Set up bot commands for the menu
    application.post_init = set_bot_commands

    # Register handlers
    # --- New UI Handlers ---
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(CommandHandler("cancel", cancel))

    # --- Command Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("scan", scan))
    application.add_handler(CommandHandler("chart", chart))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("tokeninfo", tokeninfo))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("unmonitor", unmonitor))
    application.add_handler(CommandHandler("listmonitors", list_monitors))
    application.add_handler(CommandHandler("add", add_address))
    application.add_handler(CommandHandler("remove", remove_address))
    application.add_handler(CommandHandler("list", list_addresses))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(CommandHandler("unschedule", unschedule))
    application.add_handler(CommandHandler("listschedules", list_schedules))
    application.add_handler(CommandHandler("setrpc", set_rpc))
    application.add_handler(CommandHandler("getrpc", get_rpc))
    application.add_handler(CommandHandler("resetrpc", reset_rpc))

    logger.info("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
