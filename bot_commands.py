import logging
import asyncio
import csv
from datetime import datetime, time, timezone, timedelta
from io import StringIO, BytesIO

import pandas as pd
import pytz
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from config import BIRDEYE_API_KEY
from data_manager import (
    load_user_data, save_user_data, resolve_address, get_rpc_url
)
from solana_helpers import (
    fetch_and_parse_transactions, fetch_and_parse_new_transactions, 
    get_token_details, get_wallet_balance, get_token_prices
)
from monitoring import MONITOR_TASKS, start_monitoring_task
from chart_generator import create_daily_volume_chart
from solana_client import AsyncCustomSolanaClient

logger = logging.getLogger(__name__)


# --- UI / Keyboards ---

def get_main_menu_keyboard():
    """Returns the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🔍 Scan Transactions", callback_data='scan_wallet')],
        [InlineKeyboardButton("💰 Wallet Balance", callback_data='balance_wallet')],
        [InlineKeyboardButton("📊 Chart Wallet", callback_data='chart_wallet')],
        [InlineKeyboardButton("💹 Token Price", callback_data='price_token')],
        [InlineKeyboardButton("ℹ️ Token Info", callback_data='tokeninfo')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings_menu')],
        [InlineKeyboardButton("❓ Help", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu_keyboard():
    """Returns the settings menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🗂 Manage Addresses", callback_data='manage_addresses')],
        [InlineKeyboardButton("📡 Manage Monitors", callback_data='manage_monitors')],
        [InlineKeyboardButton("⏰ Manage Schedules", callback_data='manage_schedules')],
        [InlineKeyboardButton("🔌 RPC Settings", callback_data='manage_rpc')],
        [InlineKeyboardButton("⬅️ Back", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_settings_keyboard():
    """Returns a keyboard with a 'Back to settings' button."""
    keyboard = [[InlineKeyboardButton("⬅️ Back to Settings", callback_data='settings_menu')]]
    return InlineKeyboardMarkup(keyboard)


def get_scan_options_keyboard(action_prefix: str):
    """Returns a keyboard with scan/chart options."""
    keyboard = [
        [InlineKeyboardButton("Last 100 Transactions", callback_data=f'{action_prefix}_limit_100')],
        [InlineKeyboardButton("Set Custom Limit", callback_data=f'{action_prefix}_limit')],
        [InlineKeyboardButton("By Date", callback_data=f'{action_prefix}_date')],
        [InlineKeyboardButton("By Block Range", callback_data=f'{action_prefix}_blocks')],
        [InlineKeyboardButton("⬅️ Back", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Core Logic Functions (for reuse) ---

async def _execute_scan(update: Update, context: CallbackContext, address: str, limit: int = 100, start_block: int = None, end_block: int = None, start_date: datetime = None, end_date: datetime = None):
    """Core logic to perform a scan and send the results."""
    chat_id = update.effective_chat.id
    try:
        rpc_url = get_rpc_url(chat_id)
        transactions = await fetch_and_parse_transactions(address, rpc_url, limit=limit, start_block=start_block, end_block=end_block, start_date=start_date, end_date=end_date)

        if not transactions:
            await context.bot.send_message(chat_id, "✅ No transactions found for the specified address, or an error occurred.")
            return

        output = StringIO()
        fieldnames = ['type', 'wallet_1', 'wallet_2', 'amount', 'authority', 'timestamp', 'signature', 'block_number', 'link']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(transactions)
        
        csv_data = BytesIO(output.getvalue().encode('utf-8'))
        csv_filename = f"transactions_{address[:10]}.csv"

        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(csv_data, filename=csv_filename),
            caption=f"✅ **Scan complete.**\nFound transactions for address `{address}`."
        )
    except Exception as e:
        logger.error(f"Error in _execute_scan: {e}")
        await context.bot.send_message(chat_id, f"❌ An error occurred during the scan: {e}")


async def _execute_balance(update: Update, context: CallbackContext, address: str):
    """Core logic to fetch and display wallet balance."""
    chat_id = update.effective_chat.id
    rpc_url = get_rpc_url(chat_id)
    msg = await context.bot.send_message(chat_id, f"⏳ Requesting balance for `{address}`...", parse_mode='Markdown')
    balance_message = await get_wallet_balance(address, rpc_url, BIRDEYE_API_KEY)
    await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    await send_long_message(context, chat_id, balance_message, parse_mode='Markdown')


async def _execute_price(update: Update, context: CallbackContext, address: str):
    """Core logic to fetch and display token price."""
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, f"⏳ Requesting price for `{address}`...", parse_mode='Markdown')
    price_data = await get_token_prices([address], BIRDEYE_API_KEY)
    price_message = format_price_info(address, price_data)
    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=price_message, parse_mode='Markdown')


async def _execute_tokeninfo(update: Update, context: CallbackContext, address: str):
    """Core logic to fetch and display token info."""
    chat_id = update.effective_chat.id
    rpc_url = get_rpc_url(chat_id)
    await context.bot.send_message(chat_id, f"⏳ Fetching info for token `{address}`...", parse_mode='Markdown')

    details = await get_token_details(address, rpc_url)

    if not details.get('decimals'): # A token must have decimals
        await context.bot.send_message(chat_id, "❌ Could not find information. Please ensure this is an SPL token mint address.")
        return

    message_lines = [
        f"✅ **Token Information:** `{address}`\n",
        f"🪙 **Total Supply:** `{details.get('supply', 'N/A')}`",
        f"🔬 **Decimals:** `{details.get('decimals', 'N/A')}`",
        f"🔑 **Mint Authority:** `{details.get('mint_authority', 'N/A')}`"
    ]
    if 'freeze_authority' in details:
        message_lines.append(f"❄️ **Freeze Authority:** `{details.get('freeze_authority', 'N/A')}`")

    await context.bot.send_message(chat_id, "\n".join(message_lines), parse_mode='Markdown')


async def _execute_chart(update: Update, context: CallbackContext, address: str, limit: int = 100, start_block: int = None, end_block: int = None, start_date: datetime = None, end_date: datetime = None, transactions: list = None):
    """Core logic for generating and sending a chart."""
    chat_id = update.effective_chat.id
    rpc_url = get_rpc_url(chat_id)
    try:
        if transactions is None:
            transactions = await fetch_and_parse_transactions(address, rpc_url, limit=limit, start_block=start_block, end_block=end_block, start_date=start_date, end_date=end_date)

        if not transactions:
            await context.bot.send_message(chat_id, "✅ No transactions found for the specified address or parameters.")
            return

        token_details = await get_token_details(address, rpc_url)
        is_token_mint = token_details.get('decimals') is not None
        
        token_accounts = []
        if not is_token_mint:
            try:
                async with AsyncCustomSolanaClient(rpc_url) as client:
                    token_accounts_res = await client.get_token_accounts_by_owner(address)
                    if token_accounts_res and "result" in token_accounts_res and token_accounts_res["result"].get("value"):
                        token_accounts = [acc["pubkey"] for acc in token_accounts_res["result"]["value"]]
            except Exception as e:
                logger.error(f"Could not fetch token accounts for wallet {address}: {e}")
        
        # Calculate statistics for the caption
        stats_caption = ""
        try:
            df = pd.DataFrame(transactions)
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
            df.dropna(subset=['amount'], inplace=True)

            if not df.empty:
                if is_token_mint:
                    total_volume = df['amount'].sum()
                    num_transactions = len(df)
                    avg_tx_size = total_volume / num_transactions if num_transactions > 0 else 0
                    stats_caption = (
                        f"\n\n**Statistics:**\n"
                        f"▫️ **Total Volume:** `{total_volume:,.2f}`\n"
                        f"▫️ **Transactions:** `{num_transactions}`\n"
                        f"▫️ **Avg. Tx Size:** `{avg_tx_size:,.2f}`"
                    )
                else: # is_wallet
                    address_stripped = address.strip()
                    token_accounts_set = set(token_accounts)
                    
                    df['wallet_1'] = df.get('wallet_1', pd.Series(dtype=str)).fillna('')
                    df['wallet_2'] = df.get('wallet_2', pd.Series(dtype=str)).fillna('')
                    if 'authority' not in df.columns:
                        df['authority'] = ''
                    df['authority'] = df['authority'].fillna('')

                    incoming_mask = df.apply(lambda row: row['wallet_2'] == address_stripped or row['wallet_2'] in token_accounts_set, axis=1)
                    outgoing_mask = df.apply(lambda row: row['wallet_1'] == address_stripped or row['authority'] == address_stripped, axis=1)

                    total_incoming = df.loc[incoming_mask, 'amount'].sum()
                    total_outgoing = df.loc[outgoing_mask, 'amount'].sum()
                    net_flow = total_incoming - total_outgoing
                    num_incoming_tx = int(incoming_mask.sum())
                    num_outgoing_tx = int(outgoing_mask.sum())

                    stats_caption = (
                        f"\n\n**Statistics:**\n"
                        f"➡️ **Total Incoming:** `{total_incoming:,.2f}` in `{num_incoming_tx}` txs\n"
                        f"⬅️ **Total Outgoing:** `{total_outgoing:,.2f}` in `{num_outgoing_tx}` txs\n"
                        f"📈 **Net Flow:** `{net_flow:,.2f}`"
                    )
        except Exception as e:
            logger.warning(f"Could not generate statistics for chart caption: {e}")
            stats_caption = ""

        chart_image = create_daily_volume_chart(transactions, address, token_accounts, is_token_mint)

        if not chart_image:
            await context.bot.send_message(chat_id, "📉 Not enough data to create a chart. Please try a different range.")
            return

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=chart_image,
            caption=f"📈 **Daily Volume Chart** for address `{address}`{stats_caption}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in _execute_chart: {e}")
        await context.bot.send_message(chat_id, f"❌ An error occurred while creating the chart: {e}")


# --- New Handlers for Button UI ---

async def button_callback_handler(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery and routes to the appropriate handler."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # Main menu routing
    if data == 'main_menu':
        await main_menu(update, context)
        return
    elif data == 'settings_menu':
        await settings_menu(update, context)
        return
    elif data == 'help':
        await help_command(update, context, from_button=True)
        return

    # --- Actions requiring input ---
    if data == 'scan_wallet':
        keyboard = get_scan_options_keyboard('scan')
        await query.edit_message_text(text="🔍 **Scan Wallet**\n\nChoose how to scan transactions:", reply_markup=keyboard, parse_mode='Markdown')

    elif data == 'chart_wallet':
        keyboard = get_scan_options_keyboard('chart')
        await query.edit_message_text(text="📊 **Chart Wallet**\n\nChoose the data for the chart:", reply_markup=keyboard, parse_mode='Markdown')
    
    elif data.startswith(('scan_', 'chart_')):
        # User has selected a scan/chart type. Now ask for address.
        context.user_data['state'] = data 
        context.user_data['action'] = data.split('_')[0] # 'scan' or 'chart'
        await query.edit_message_text(text="✍️ Please send a wallet/token address or a saved name.\n\nTo cancel, type /cancel")

    elif data in ['balance_wallet', 'price_token', 'tokeninfo']:
        # Simple actions that just need an address. Convert 'balance_wallet' to 'balance'
        context.user_data['state'] = data.split('_')[0]
        await query.edit_message_text(text="✍️ Please send a wallet/token address or a saved name.\n\nTo cancel, type /cancel")
        
    elif data.startswith('manage_'):
        # For sub-menus that don't need input yet
        if data == 'manage_addresses':
            await list_addresses(update, context, from_button=True)
        elif data == 'manage_monitors':
            await list_monitors(update, context, from_button=True)
        elif data == 'manage_schedules':
            await list_schedules(update, context, from_button=True)
        elif data == 'manage_rpc':
            await get_rpc(update, context, from_button=True)
        
async def text_handler(update: Update, context: CallbackContext) -> None:
    """Handles text messages for multi-step conversations."""
    state = context.user_data.get('state')
    if not state:
        await main_menu(update, context)
        return

    chat_id = update.effective_chat.id
    text = update.message.text

    # --- Handle simple state actions (balance, price, tokeninfo) ---
    if state in ['balance', 'price', 'tokeninfo']:
        context.user_data.clear() # Clear state after use
        address = resolve_address(chat_id, text)
        if state == 'balance': await _execute_balance(update, context, address)
        elif state == 'price': await _execute_price(update, context, address)
        elif state == 'tokeninfo': await _execute_tokeninfo(update, context, address)
        return

    # --- Handle multi-step scan/chart actions ---
    action = context.user_data.get('action')

    # Step 1: User sent an address.
    if state.startswith(('scan_', 'chart_')):
        address = resolve_address(chat_id, text)
        context.user_data['address'] = address
        
        # Action requires no more input
        if state.endswith('_limit_100'):
            context.user_data.clear()
            if action == 'scan':
                await update.message.reply_text(f"🔍 **Starting scan...**\n**Address:** `{address}`\n**Mode:** last `100` transactions.", parse_mode='Markdown')
                await _execute_scan(update, context, address, limit=100)
            elif action == 'chart':
                await update.message.reply_text(f"📊 **Generating chart...**\n**Address:** `{address}`\n**Mode:** based on the last `100` transactions.", parse_mode='Markdown')
                await _execute_chart(update, context, address, limit=100)
        
        # Action requires more input
        elif state.endswith('_limit'):
            context.user_data['state'] = f'awaiting_limit_for_{action}'
            await update.message.reply_text("🔢 Please enter the desired limit (e.g., `500`).")
        elif state.endswith('_date'):
            context.user_data['state'] = f'awaiting_date_for_{action}'
            await update.message.reply_text("🗓 Please enter a date in `YYYY-MM-DD` format or a range `YYYY-MM-DD:YYYY-MM-DD`.")
        elif state.endswith('_blocks'):
            context.user_data['state'] = f'awaiting_blocks_for_{action}'
            await update.message.reply_text("🧱 Please enter a block range in `START-END` format (e.g., `200000000-200001000`).")
        return

    # Step 2: User sent the final piece of information (limit, date, or blocks).
    if state.startswith('awaiting_'):
        address = context.user_data.get('address')
        if not address or not action:
            await cancel(update, context) # State is inconsistent, cancel
            return

        try:
            params = {}
            scan_mode_msg = ""
            if state == f'awaiting_limit_for_{action}':
                if not text.isdigit() or int(text) <= 0:
                    await update.message.reply_text("❌ Invalid format. Please enter a positive number.")
                    return
                params['limit'] = int(text)
                scan_mode_msg = f"with a limit of `{params['limit']}` transactions"

            elif state == f'awaiting_date_for_{action}':
                date_parts = text.split(':')
                if len(date_parts) == 1:
                    params['start_date'] = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    params['end_date'] = params['start_date'] + timedelta(days=1) - timedelta(microseconds=1)
                    scan_mode_msg = f"for the date `{params['start_date'].strftime('%Y-%m-%d')}`"
                elif len(date_parts) == 2:
                    params['start_date'] = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    params['end_date'] = datetime.strptime(date_parts[1], '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(microseconds=1)
                    scan_mode_msg = f"for the period from `{params['start_date'].strftime('%Y-%m-%d')}` to `{params['end_date'].strftime('%Y-%m-%d')}`"
                else:
                    raise ValueError("Invalid date format")
            
            elif state == f'awaiting_blocks_for_{action}':
                block_parts = text.split('-')
                if len(block_parts) != 2 or not block_parts[0].isdigit() or not block_parts[1].isdigit():
                     raise ValueError("Invalid block format")
                params['start_block'] = int(block_parts[0])
                params['end_block'] = int(block_parts[1])
                scan_mode_msg = f"in the block range from `{params['start_block']}` to `{params['end_block']}`"

            # Clean up user_data and execute
            context.user_data.clear()
            
            if action == 'scan':
                await update.message.reply_text(f"🔍 **Starting scan...**\n**Address:** `{address}`\n**Mode:** {scan_mode_msg}.\n\nPlease wait.", parse_mode='Markdown')
                await _execute_scan(update, context, address, **params)
            elif action == 'chart':
                await update.message.reply_text(f"📊 **Generating chart...**\n**Address:** `{address}`\n**Mode:** {scan_mode_msg}.\n\nPlease wait.", parse_mode='Markdown')
                await _execute_chart(update, context, address, **params)

        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid format. Please try again.")
        except Exception as e:
            logger.error(f"Error in text_handler during final execution step: {e}")
            await update.message.reply_text(f"❌ An error occurred: {e}")
            await cancel(update, context)


async def cancel(update: Update, context: CallbackContext) -> None:
    """Clears any active state and returns to the main menu."""
    if 'state' in context.user_data:
        del context.user_data['state']
    
    await update.message.reply_text("Operation cancelled. Returning to the main menu.")
    await main_menu(update, context)


async def main_menu(update: Update, context: CallbackContext):
    """Displays the main menu."""
    text = "👋 **Hi! I'm your Solana assistant.**\n\nChoose an action:"
    keyboard = get_main_menu_keyboard()
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def settings_menu(update: Update, context: CallbackContext):
    """Displays the settings menu."""
    text = "⚙️ **Settings**\n\nHere you can manage saved addresses, monitors, and other parameters."
    keyboard = get_settings_menu_keyboard()
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def send_long_message(context: CallbackContext, chat_id: int, text: str, **kwargs):
    """Sends a long message by splitting it into parts without breaking lines."""
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return

    lines = text.split('\n')
    message_part = ""
    for line in lines:
        if len(message_part) + len(line) + 1 > MAX_LENGTH:
            await context.bot.send_message(chat_id=chat_id, text=message_part, **kwargs)
            message_part = ""
        
        message_part += line + "\n"
    
    if message_part:
        await context.bot.send_message(chat_id=chat_id, text=message_part, **kwargs)


async def start(update: Update, context: CallbackContext) -> None:
    """Sends a welcome message with the main menu."""
    await main_menu(update, context)


async def help_command(update: Update, context: CallbackContext, from_button: bool = False) -> None:
    """Displays the help message with all available commands."""
    help_text = (
        "👋 **Command Reference**\n\n"
        "You can use the menu buttons or type commands manually.\n\n"
        "🗂 **Address Management:**\n"
        "`/add <name> <address>` - Save an address.\n"
        "`/remove <name>` - Remove an address.\n"
        "`/list` - List saved addresses.\n\n"
        "🔍 **Transaction Scanning:**\n"
        "`/scan <address|name> [PARAMETERS]`\n"
        "   • `--limit 100` - Last N transactions.\n"
        "   • `--blocks S-E` - Within a block range.\n"
        "   • `--date YYYY-MM-DD` or `START:END` - For a day or period.\n"
        "*Example:* `/scan wsol --date 2024-07-30`\n\n"
        "💰 **Balance:**\n"
        "`/balance <address|name>` - Show wallet balance.\n\n"
        "💹 **Token Price:**\n"
        "`/price <address|name>` - Get token price.\n\n"
        "📊 **Charts:**\n"
        "`/chart <address|name> [PARAMETERS]`\n"
        "   • You can also reply to a CSV file with `/chart <name>`.\n\n"
        "⏰ **Scheduled Scans:**\n"
        "   • `/schedule <name> <HH:MM>` - Daily scan (UTC).\n"
        "   • `/unschedule <name>` - Cancel a schedule.\n"
        "   • `/listschedules` - List schedules.\n\n"
        "📡 **Monitoring:**\n"
        "   • `/monitor <address|name>` - Start monitoring.\n"
        "   • `/unmonitor <address|name>` - Stop monitoring.\n"
        "   • `/listmonitors` - List monitored wallets.\n\n"
        "ℹ️ **Token Info:**\n"
        "`/tokeninfo <address|name>` - Info about an SPL token.\n\n"
        "⚙️ **RPC Settings:**\n"
        "`/setrpc <URL>` - Set a custom RPC.\n"
        "`/getrpc` - Show the current RPC.\n"
        "`/resetrpc` - Reset to default RPC.\n\n"
        "To cancel the current operation, type /cancel."
    )
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')]])

    if from_button:
        await update.callback_query.edit_message_text(help_text, reply_markup=keyboard, parse_mode='Markdown')
    else:
        # This is for /help command
        await update.message.reply_text(help_text, parse_mode='Markdown')
        await main_menu(update, context)


async def tokeninfo(update: Update, context: CallbackContext) -> None:
    """Gets info about an SPL token."""
    chat_id = update.message.chat_id
    args = context.args

    if not args:
        await context.bot.send_message(chat_id, "ℹ️ Please provide a token address or its name.\nExample: `/tokeninfo usdc`", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    await _execute_tokeninfo(update, context, address)


def format_price_info(token_address: str, price_data: dict) -> str:
    """Formats the price data for a single token into a user-friendly message."""
    price_info = price_data.get(token_address, {})
    value = price_info.get("value")

    if value is None:
        return f"❌ Could not fetch price for `{token_address}`."

    symbol = price_info.get("symbol", "N/A")
    
    message = (
        f"📊 **Price for {symbol}** (`{token_address}`)\n\n"
        f"   - **Price:** `${value:,.8f}`"
    )
    return message


async def price(update: Update, context: CallbackContext) -> None:
    """Fetches and displays the price for a given token."""
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await context.bot.send_message(chat_id, "⛑️ Please provide a token address or its name.\nExample: `/price USDC`", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    await _execute_price(update, context, address)


async def monitor(update: Update, context: CallbackContext) -> None:
    """Starts monitoring a wallet for real-time transactions."""
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await update.message.reply_text("⛑️ **Usage:** `/monitor <address|name>`", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    
    if len(address) < 32 or len(address) > 45:
        await update.message.reply_text("❌ Invalid Solana address.", parse_mode='Markdown')
        return

    data = load_user_data()
    if str(chat_id) not in data:
        data[str(chat_id)] = {"aliases": {}, "schedules": {}, "monitors": {}}
    if "monitors" not in data[str(chat_id)]:
        data[str(chat_id)]["monitors"] = {}

    if address in data[str(chat_id)]["monitors"]:
        await update.message.reply_text(f"ℹ️ Address `{address[:6]}...` is already being monitored.", parse_mode='Markdown')
        return

    task = asyncio.create_task(start_monitoring_task(context.application, chat_id, address))
    MONITOR_TASKS[(chat_id, address)] = task
    
    data[str(chat_id)]["monitors"][address] = alias_or_address
    save_user_data(data)
    
    await update.message.reply_text(f"📡 **Starting monitoring** for wallet `{address}`. You will receive notifications for new transactions.", parse_mode='Markdown')


async def unmonitor(update: Update, context: CallbackContext) -> None:
    """Stops monitoring a wallet."""
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await update.message.reply_text("⛑️ **Usage:** `/unmonitor <address|name>`", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)

    task = MONITOR_TASKS.get((chat_id, address))
    if task:
        task.cancel()
        del MONITOR_TASKS[(chat_id, address)]
    
    data = load_user_data()
    if str(chat_id) in data and "monitors" in data[str(chat_id)] and address in data[str(chat_id)]["monitors"]:
        del data[str(chat_id)]["monitors"][address]
        save_user_data(data)
        await update.message.reply_text(f"🛑 Monitoring for `{address}` has been stopped.", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Address `{address}` is not being monitored.", parse_mode='Markdown')


async def list_monitors(update: Update, context: CallbackContext, from_button: bool = False) -> None:
    """Lists all monitored wallets."""
    chat_id = update.effective_chat.id
    data = load_user_data()
    user_monitors = data.get(str(chat_id), {}).get("monitors", {})

    message = "📡 **Monitored Wallets:**\n\n"
    if not user_monitors:
        message += "You have no monitored wallets."
    else:
        for address, alias in user_monitors.items():
            display_name = f"`{alias}` (`{address}`)" if alias != address else f"`{address}`"
            message += f"▪️ {display_name}\n"
    
    message += "\n\nTo add one, use `/monitor <name|address>`."

    if from_button:
        await update.callback_query.edit_message_text(message, reply_markup=get_back_to_settings_keyboard(), parse_mode='Markdown')
    else:
        await send_long_message(context, chat_id, message, parse_mode='Markdown')


async def balance(update: Update, context: CallbackContext) -> None:
    """Gets the balance of a Solana wallet."""
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await context.bot.send_message(chat_id, "⛑️ Please provide a wallet address or its name.\nExample: `/balance wsol`", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    await _execute_balance(update, context, address)


async def scheduled_scan_callback(context: CallbackContext):
    """The callback function for scheduled scans."""
    job = context.job
    chat_id = job.data["chat_id"]
    alias = job.data["alias"]
    address = job.data["address"]

    await context.bot.send_message(chat_id, f"🤖 Starting scheduled scan for `{alias}` (`{address[:4]}...`)", parse_mode='Markdown')

    user_data = load_user_data()
    schedule_info = user_data.get(str(chat_id), {}).get("schedules", {}).get(alias, {})
    last_signature = schedule_info.get("last_signature")

    rpc_url = get_rpc_url(chat_id)
    transactions, new_last_signature = await fetch_and_parse_new_transactions(address, rpc_url, last_signature)

    if not transactions:
        await context.bot.send_message(chat_id, f"✅ No new transactions found for `{alias}`.", parse_mode='Markdown')
        return

    if new_last_signature and new_last_signature != last_signature:
        user_data[str(chat_id)]["schedules"][alias]["last_signature"] = new_last_signature
        save_user_data(user_data)
        logger.info(f"Updated last signature for {alias} (chat {chat_id}) to {new_last_signature}")

    output = StringIO()
    fieldnames = ['type', 'wallet_1', 'wallet_2', 'amount', 'authority', 'timestamp', 'signature', 'block_number', 'link']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(transactions)
    
    csv_data = BytesIO(output.getvalue().encode('utf-8'))
    csv_filename = f"scheduled_scan_{alias}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"

    await context.bot.send_document(
        chat_id=chat_id,
        document=InputFile(csv_data, filename=csv_filename),
        caption=f"📄 **New transactions found for `{alias}`!**"
    )


async def schedule(update: Update, context: CallbackContext) -> None:
    """Schedules a daily scan for a given alias."""
    chat_id = update.message.chat_id
    args = context.args
    
    if len(args) != 2:
        await update.message.reply_text("⛑️ **Usage:** `/schedule <name> <HH:MM>` (time in UTC)\n*Example:* `/schedule my_wallet 15:30`", parse_mode='Markdown')
        return

    alias, time_str = args
    address = resolve_address(chat_id, alias)
    if address == alias:
        await update.message.reply_text(f"❌ Name `{alias}` not found. Please add the address first using `/add`.", parse_mode='Markdown')
        return

    try:
        scan_time = time.fromisoformat(time_str)
    except ValueError:
        await update.message.reply_text("❌ Invalid time format. Please use `HH:MM`.", parse_mode='Markdown')
        return

    job_name = f"scan_{chat_id}_{alias}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
    
    context.job_queue.run_daily(
        scheduled_scan_callback,
        time=scan_time.replace(tzinfo=pytz.UTC),
        chat_id=chat_id,
        user_id=chat_id,
        name=job_name,
        data={"chat_id": chat_id, "alias": alias, "address": address}
    )

    data = load_user_data()
    if str(chat_id) not in data:
        data[str(chat_id)] = {"aliases": {}, "schedules": {}}
    if "schedules" not in data[str(chat_id)]:
        data[str(chat_id)]["schedules"] = {}
    
    data[str(chat_id)]["schedules"][alias] = {"time": time_str, "address": address, "last_signature": None}
    save_user_data(data)

    await update.message.reply_text(f"✅ **Done!** Daily scan for `{alias}` has been set for `{time_str}` UTC.", parse_mode='Markdown')


async def unschedule(update: Update, context: CallbackContext) -> None:
    """Removes a scheduled scan."""
    chat_id = update.message.chat_id
    args = context.args

    if len(args) != 1:
        await update.message.reply_text("⛑️ **Usage:** `/unschedule <name>`", parse_mode='Markdown')
        return

    alias = args[0]
    job_name = f"scan_{chat_id}_{alias}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)

    if not current_jobs:
        await update.message.reply_text(f"❌ No schedule found for `{alias}`.", parse_mode='Markdown')
        return

    for job in current_jobs:
        job.schedule_removal()

    data = load_user_data()
    if str(chat_id) in data and "schedules" in data[str(chat_id)] and alias in data[str(chat_id)]["schedules"]:
        del data[str(chat_id)]["schedules"][alias]
        save_user_data(data)

    await update.message.reply_text(f"🗑️ Schedule for `{alias}` has been removed.", parse_mode='Markdown')


async def list_schedules(update: Update, context: CallbackContext, from_button: bool = False) -> None:
    """Lists all scheduled scans for the user."""
    chat_id = update.effective_chat.id
    data = load_user_data()
    user_schedules = data.get(str(chat_id), {}).get("schedules", {})

    message = "⏰ **Your Schedules (time in UTC):**\n\n"
    if not user_schedules:
        message += "You have no scheduled scans."
    else:
        for alias, details in user_schedules.items():
            message += f"▪️ `{alias}` at `{details.get('time', 'N/A')}`\n"
    
    message += "\n\nTo add one, use `/schedule <name> <HH:MM>`."

    if from_button:
        await update.callback_query.edit_message_text(message, reply_markup=get_back_to_settings_keyboard(), parse_mode='Markdown')
    else:
        await send_long_message(context, chat_id, message, parse_mode='Markdown')


async def scan(update: Update, context: CallbackContext) -> None:
    """Scans for transactions and sends a CSV file."""
    chat_id = update.message.chat_id
    args = context.args

    if not args:
        await context.bot.send_message(chat_id, "⛑️ Please provide an address and scan parameters. See /help for examples.", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    
    limit = 100
    start_block, end_block = None, None
    start_date, end_date = None, None
    scan_mode_msg = f"with a limit of `{limit}` transactions"

    if len(args) > 1:
        param = args[1]
        value = args[2] if len(args) > 2 else None

        if param == '--limit' and value and value.isdigit():
            limit = int(value)
            scan_mode_msg = f"with a limit of `{limit}` transactions"
        elif param == '--blocks' and value and '-' in value:
            try:
                start_str, end_str = value.split('-')
                start_block = int(start_str)
                end_block = int(end_str)
                limit = None
                scan_mode_msg = f"in the block range from `{start_block}` to `{end_block}`"
            except (ValueError, IndexError):
                await context.bot.send_message(chat_id, "❌ Invalid block format. Use: `--blocks START-END`.", parse_mode='Markdown')
                return
        elif param == '--date' and value:
            try:
                date_parts = value.split(':')
                if len(date_parts) == 1:
                    start_date = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    end_date = start_date + timedelta(days=1) - timedelta(microseconds=1)
                    scan_mode_msg = f"for the date `{start_date.strftime('%Y-%m-%d')}`"
                elif len(date_parts) == 2:
                    start_date = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    end_date = datetime.strptime(date_parts[1], '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(microseconds=1)
                    scan_mode_msg = f"for the period from `{start_date.strftime('%Y-%m-%d')}` to `{end_date.strftime('%Y-%m-%d')}`"
                
                limit, start_block, end_block = None, None, None
            except ValueError:
                await context.bot.send_message(chat_id, "❌ Invalid date format. Use: `--date YYYY-MM-DD` or `--date YYYY-MM-DD:YYYY-MM-DD`.", parse_mode='Markdown')
                return

    await context.bot.send_message(chat_id, f"🔍 **Starting scan...**\n**Address:** `{address}`\n**Mode:** {scan_mode_msg}.\n\nPlease wait.", parse_mode='Markdown')
    await _execute_scan(update, context, address, limit=limit, start_block=start_block, end_block=end_block, start_date=start_date, end_date=end_date)


async def chart(update: Update, context: CallbackContext) -> None:
    """Generates and sends a chart of transaction volume."""
    chat_id = update.message.chat_id
    args = context.args

    if not args:
        await context.bot.send_message(chat_id, "⛑️ Please provide an address. To analyze a CSV file, reply to the file's message with the command.\nSee /help for examples.", parse_mode='Markdown')
        return

    alias_or_address = args[0]
    address = resolve_address(chat_id, alias_or_address)
    
    transactions = []
    replied_message = update.message.reply_to_message

    if replied_message and replied_message.document and replied_message.document.file_name.lower().endswith('.csv'):
        await context.bot.send_message(chat_id, f"📊 **Analyzing CSV file for chart...**\n**Address:** `{address}`", parse_mode='Markdown')
        
        csv_file = await replied_message.document.get_file()
        csv_content = await csv_file.download_as_bytearray()
        
        csv_io = StringIO(csv_content.decode('utf-8'))
        reader = csv.DictReader(csv_io)
        transactions = [row for row in reader]
        await _execute_chart(update, context, address, transactions=transactions)
    
    else:
        limit = 100
        start_block, end_block = None, None
        start_date, end_date = None, None
        scan_mode_msg = f"based on the last `{limit}` transactions"

        if len(args) > 1:
            param = args[1]
            value = args[2] if len(args) > 2 else None

            if param == '--limit' and value and value.isdigit():
                limit = int(value)
                scan_mode_msg = f"based on the last `{limit}` transactions"
            elif param == '--blocks' and value and '-' in value:
                try:
                    start_str, end_str = value.split('-')
                    start_block = int(start_str)
                    end_block = int(end_str)
                    limit = None
                    scan_mode_msg = f"in the block range from `{start_block}` to `{end_block}`"
                except (ValueError, IndexError):
                    await context.bot.send_message(chat_id, "❌ Invalid block format. Use: `--blocks START-END`.", parse_mode='Markdown')
                    return
            elif param == '--date' and value:
                try:
                    date_parts = value.split(':')
                    if len(date_parts) == 1:
                        start_date = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        end_date = start_date + timedelta(days=1) - timedelta(microseconds=1)
                        scan_mode_msg = f"for the date `{start_date.strftime('%Y-%m-%d')}`"
                    elif len(date_parts) == 2:
                        start_date = datetime.strptime(date_parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        end_date = datetime.strptime(date_parts[1], '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(microseconds=1)
                        scan_mode_msg = f"for the period from `{start_date.strftime('%Y-%m-%d')}` to `{end_date.strftime('%Y-%m-%d')}`"
                    
                    limit, start_block, end_block = None, None, None
                except ValueError:
                    await context.bot.send_message(chat_id, "❌ Invalid date format. Use: `--date YYYY-MM-DD` or `--date YYYY-MM-DD:YYYY-MM-DD`.", parse_mode='Markdown')
                    return

        await context.bot.send_message(chat_id, f"📊 **Generating chart...**\n**Address:** `{address}`\n**Mode:** {scan_mode_msg}.\n\nPlease wait, this may take a moment.", parse_mode='Markdown')
        await _execute_chart(update, context, address, limit=limit, start_block=start_block, end_block=end_block, start_date=start_date, end_date=end_date)


async def set_rpc(update: Update, context: CallbackContext) -> None:
    """Sets a custom RPC URL for the chat."""
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await update.message.reply_text("⛑️ **Usage:** `/setrpc <URL>`\n*Example:* `/setrpc https://api.mainnet-beta.solana.com`", parse_mode='Markdown')
        return

    rpc_url = args[0]
    if not rpc_url.startswith("http"):
        await update.message.reply_text("❌ Invalid URL. The URL must start with `http` or `https`.", parse_mode='Markdown')
        return

    data = load_user_data()
    if str(chat_id) not in data:
        data[str(chat_id)] = {"aliases": {}, "schedules": {}}
    data[str(chat_id)]["rpc_url"] = rpc_url
    save_user_data(data)

    await update.message.reply_text(f"✅ **Done!** RPC URL has been set to `{rpc_url}`.", parse_mode='Markdown')


async def get_rpc(update: Update, context: CallbackContext, from_button: bool = False) -> None:
    """Displays the current RPC URL for the chat."""
    chat_id = update.effective_chat.id
    rpc_url = get_rpc_url(chat_id)
    default_rpc = context.bot_data.get("default_rpc_url", "")
    is_default = rpc_url == default_rpc

    message = (
        f"🌐 **Current RPC URL:** `{rpc_url}`\n"
        f"{'*(default)*' if is_default else '*(custom)*'}\n\n"
        f"To change it, use `/setrpc <URL>`."
    )
    
    if from_button:
        await update.callback_query.edit_message_text(message, reply_markup=get_back_to_settings_keyboard(), parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')


async def reset_rpc(update: Update, context: CallbackContext) -> None:
    """Resets the RPC URL to the default."""
    chat_id = update.message.chat_id
    data = load_user_data()
    if str(chat_id) in data and "rpc_url" in data[str(chat_id)]:
        del data[str(chat_id)]["rpc_url"]
        save_user_data(data)
        await update.message.reply_text(f"✅ **Done!** RPC URL has been reset to default.", parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ You are already using the default RPC URL.", parse_mode='Markdown')


async def add_address(update: Update, context: CallbackContext) -> None:
    """Saves a Solana address with an alias."""
    chat_id = update.message.chat_id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("⛑️ **Usage:** `/add <name> <address>`\n*Example:* `/add usdc EpjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`", parse_mode='Markdown')
        return

    alias, address = args
    data = load_user_data()

    if str(chat_id) not in data:
        data[str(chat_id)] = {"aliases": {}}
    
    data[str(chat_id)]["aliases"][alias] = address
    save_user_data(data)

    await update.message.reply_text(f"✅ **Done!** Address `{address}` has been saved with the name `{alias}`.", parse_mode='Markdown')


async def remove_address(update: Update, context: CallbackContext) -> None:
    """Removes a saved alias."""
    chat_id = update.message.chat_id
    args = context.args

    if len(args) != 1:
        await update.message.reply_text("⛑️ **Usage:** `/remove <name>`", parse_mode='Markdown')
        return

    alias = args[0]
    data = load_user_data()
    user_aliases = data.get(str(chat_id), {}).get("aliases", {})

    if alias in user_aliases:
        del user_aliases[alias]
        save_user_data(data)
        await update.message.reply_text(f"🗑️ Name `{alias}` has been removed.", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Name `{alias}` not found.", parse_mode='Markdown')


async def list_addresses(update: Update, context: CallbackContext, from_button: bool = False) -> None:
    """Lists all saved aliases for the user."""
    chat_id = update.effective_chat.id
    data = load_user_data()
    user_aliases = data.get(str(chat_id), {}).get("aliases", {})
    
    message = "📚 **Your Saved Addresses:**\n\n"
    if not user_aliases:
        message += "You have no saved addresses."
    else:
        for alias, address in user_aliases.items():
            message += f"▪️ `{alias}`: `{address}`\n"
    
    message += "\n\nTo add one, use `/add <name> <address>`."

    if from_button:
        await update.callback_query.edit_message_text(message, reply_markup=get_back_to_settings_keyboard(), parse_mode='Markdown')
    else:
        await send_long_message(context, chat_id, message, parse_mode='Markdown')
