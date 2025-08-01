import logging
import asyncio

from telegram import helpers
from telegram.ext import Application
from telegram.constants import ParseMode

from solana_client import AsyncCustomSolanaClient
from data_manager import get_rpc_url
from solana_helpers import get_token_prices

logger = logging.getLogger(__name__)

MONITOR_TASKS = {}


async def format_transaction_notification(tx_info: dict, wallet_address: str, rpc_url: str) -> str:
    """Formats a transaction into a notification message."""
    signature = tx_info['signature']
    link = f"https://solscan.io/tx/{signature}"
    tx_result = tx_info.get("transaction", {})
    meta = tx_info.get("meta", {})
    if not tx_result or not meta or meta.get("err"):
        return "" # Don't notify for failed or malformed transactions

    sol_change = 0
    token_changes = []

    # Get SOL balance change
    try:
        account_keys = tx_result.get('message', {}).get('accountKeys', [])
        addr_idx = next((i for i, acc in enumerate(account_keys) if acc == wallet_address), -1)
        if addr_idx != -1:
            pre_sol = meta['preBalances'][addr_idx]
            post_sol = meta['postBalances'][addr_idx]
            sol_change = (post_sol - pre_sol) / 1_000_000_000
    except (KeyError, IndexError, TypeError):
        pass # Ignore if SOL balances are not available

    # Get SPL token balance changes
    token_accounts = []
    try:
        async with AsyncCustomSolanaClient(rpc_url) as client:
            res = await client.get_token_accounts_by_owner(wallet_address)
            if res and res.get("result", {}).get("value"):
                token_accounts = {acc["pubkey"] for acc in res["result"]["value"]}
    except Exception as e:
        logger.error(f"Monitor could not fetch token accounts for {wallet_address}: {e}")

    pre_token_balances = {b['mint']: b for b in meta.get("preTokenBalances", []) if b.get('owner') == wallet_address}
    post_token_balances = {b['mint']: b for b in meta.get("postTokenBalances", []) if b.get('owner') == wallet_address}
    all_mints = set(pre_token_balances.keys()) | set(post_token_balances.keys())

    for mint in all_mints:
        pre_amount = float(pre_token_balances.get(mint, {}).get('uiTokenAmount', {}).get('uiAmountString', '0'))
        post_amount = float(post_token_balances.get(mint, {}).get('uiTokenAmount', {}).get('uiAmountString', '0'))
        change = post_amount - pre_amount
        if abs(change) > 0:
            token_changes.append({'mint': mint, 'change': change})

    # Build the message
    lines = []
    if abs(sol_change) > 0:
        direction = "🟢 Получено" if sol_change > 0 else "🔴 Отправлено"
        lines.append(f"{direction} `{abs(sol_change):.6f}` **SOL**")

    if token_changes:
        prices = await get_token_prices([tc['mint'] for tc in token_changes])
        for tc in token_changes:
            symbol = prices.get(tc['mint'], {}).get('symbol', tc['mint'][:6]+"...")
            direction = "🟢 Получено" if tc['change'] > 0 else "🔴 Отправлено"
            lines.append(f"{direction} `{abs(tc['change']):,.6f}` **{symbol}**")
            
    if not lines:
        return "" # No relevant changes detected

    header = f"🔔 **Новая транзакция** для кошелька `{wallet_address[:4]}...{wallet_address[-4:]}`"
    # Manually create link to avoid issues with different library versions
    escaped_text = helpers.escape_markdown("Посмотреть на Solscan", version=2)
    tx_link = f"[{escaped_text}]({link})"
    return f"{header}\n\n" + "\n".join(lines) + f"\n\n{tx_link}"


async def start_monitoring_task(application: Application, chat_id: int, address: str):
    """The main loop for monitoring a wallet using websockets."""
    rpc_url = get_rpc_url(chat_id)
    ws_url = rpc_url.replace("https", "wss").replace("http", "ws")
    
    logger.info(f"Starting monitor task for {address} on chat {chat_id} via {ws_url}")
    
    while True: # Outer loop for reconnection
        try:
            async with AsyncCustomSolanaClient(rpc_url) as client:
                await client.ws_connect(ws_url)
                await client.logs_subscribe(address)
                
                while True: # Inner loop for receiving messages
                    message = await client.ws_recv()
                    if message and 'params' in message and 'result' in message['params']:
                        signature = message['params']['result']['value']['signature']
                        
                        # Use a small delay to ensure transaction is finalized on RPC
                        await asyncio.sleep(2) 
                        
                        tx_info_res = await client.get_transaction(signature, max_supported_transaction_version=0)
                        if tx_info_res and tx_info_res.get('result'):
                            notification_msg = await format_transaction_notification(tx_info_res['result'], address, rpc_url)
                            if notification_msg:
                                await application.bot.send_message(chat_id, notification_msg, parse_mode=ParseMode.MARKDOWN_V2)
                        else:
                            logger.warning(f"Monitor could not fetch details for tx {signature}")

        except (asyncio.CancelledError):
            logger.info(f"Monitor task for {address} (chat {chat_id}) was cancelled.")
            break # Exit the outer loop
        except Exception as e:
            logger.error(f"Error in monitor for {address} (chat {chat_id}): {e}. Reconnecting in 10s...")
            await asyncio.sleep(10) # Wait before reconnecting
        finally:
            if 'client' in locals() and client.ws_is_connected():
                await client.ws_close()
