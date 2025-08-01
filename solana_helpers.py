import logging
import asyncio
import csv
from datetime import datetime
from io import StringIO, BytesIO
from typing import List, Dict, Any, Optional, Tuple

import httpx
from solana_client import AsyncCustomSolanaClient

logger = logging.getLogger(__name__)


# --- Core Solana scanning logic ---
async def _fetch_transaction_with_retry(client: AsyncCustomSolanaClient, sig_info: dict, sem: asyncio.Semaphore):
    """Fetches a single transaction with a retry loop, semaphore, and exponential backoff."""
    MAX_RETRIES = 5
    INITIAL_DELAY_SECONDS = 1
    delay = INITIAL_DELAY_SECONDS
    signature = sig_info['signature']

    for attempt in range(MAX_RETRIES):
        try:
            async with sem:
                return await client.get_transaction(signature)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for tx {signature}: {e}. Retrying in {delay}s...")

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(delay)
            delay *= 2  # Exponential backoff

    logger.error(f"Failed to fetch transaction {signature} after {MAX_RETRIES} attempts.")
    return None


def _parse_transaction_details(tx_response: Dict[str, Any], sig_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parses the details of a transaction response."""
    parsed_data = []
    if not tx_response or "result" not in tx_response or not tx_response["result"]:
        logger.info(f"Could not retrieve transaction for signature {sig_info['signature']}, skipping.")
        return parsed_data
    
    tx_result = tx_response["result"]
    signature = sig_info['signature']

    block_time = tx_result.get('blockTime')
    timestamp = datetime.fromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S') if block_time else ''
    slot = tx_result.get('slot', '')

    transaction_field = tx_result.get('transaction')
    if not isinstance(transaction_field, dict):
        logger.info(f"Transaction {signature} has a malformed transaction field (not a dict), skipping.")
        return parsed_data
    
    message = transaction_field.get('message', {})
    if not isinstance(message, dict):
        logger.info(f"Transaction {signature} has a malformed message field (not a dict), skipping.")
        return parsed_data
    
    instructions = message.get('instructions', [])

    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        parsed_info = instruction.get('parsed', {})
        if not isinstance(parsed_info, dict) or not parsed_info:
            continue

        tx_type = parsed_info.get('type')
        if tx_type not in ['transfer', 'transferChecked']:
            continue
        
        info = parsed_info.get('info', {})
        wallet_1 = info.get('source')
        wallet_2 = info.get('destination')
        authority = info.get('authority')

        if not wallet_1 or not wallet_2:
            continue

        amount = 'N/A'
        if 'lamports' in info:  # SOL transfer
            amount = info.get('lamports', 0) / 1_000_000_000
        elif 'tokenAmount' in info:  # SPL token transfer with decimals
            amount = info.get('tokenAmount', {}).get('uiAmountString') or info.get('tokenAmount', {}).get('uiAmount')
        elif 'amount' in info:  # SPL token transfer, raw amount
            amount = info.get('amount')

        parsed_data.append({
            'type': tx_type,
            'wallet_1': wallet_1,
            'wallet_2': wallet_2,
            'amount': amount,
            'authority': authority,
            'timestamp': timestamp,
            'signature': signature,
            'block_number': slot,
            'link': f"https://solscan.io/tx/{signature}"
        })
    return parsed_data


async def fetch_and_parse_transactions(address: str, rpc_url: str, limit: int = 100, start_block: Optional[int] = None, end_block: Optional[int] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Fetches and parses transactions for a given Solana address based on different criteria."""
    parsed_data = []
    try:
        async with AsyncCustomSolanaClient(rpc_url) as client:
            logger.info(f"Fetching signatures for address {address}...")

            signatures = []
            if start_date and end_date:
                start_ts = int(start_date.timestamp())
                end_ts = int(end_date.timestamp())
                
                before_sig = None
                fetched_count = 0
                while fetched_count < 20000:  # Safety limit of 20000 txns to avoid extreme usage
                    response = await client.get_signatures_for_address(address, limit=1000, before=before_sig)
                    if "error" in response or not response.get("result"):
                        break
                    
                    batch = response["result"]
                    if not batch:
                        break

                    # Collect signatures within the date range
                    for sig_info in batch:
                        block_time = sig_info.get("blockTime")
                        if block_time and start_ts <= block_time <= end_ts:
                            signatures.append(sig_info)
                    
                    # If the last signature in the batch is older than our start date, we can stop.
                    last_sig_time = batch[-1].get("blockTime")
                    if last_sig_time and last_sig_time < start_ts:
                        break

                    # Stop if we've reached the end of the history for this address
                    if len(batch) < 1000:
                        break
                    
                    before_sig = batch[-1]["signature"]
                    fetched_count += len(batch)

            elif start_block or end_block:
                before_sig = None
                fetched_count = 0
                while fetched_count < 5000:  # Safety limit of 5000 txns to avoid extreme usage
                    response = await client.get_signatures_for_address(address, limit=1000, before=before_sig)
                    if "error" in response or not response.get("result"):
                        break
                    
                    batch = response["result"]
                    if not batch:
                        break

                    stop_fetching = False
                    for sig_info in batch:
                        slot = sig_info.get("slot")
                        if end_block and slot > end_block:
                            continue
                        if start_block and slot < start_block:
                            stop_fetching = True
                            break
                        signatures.append(sig_info)
                    
                    if stop_fetching or len(batch) < 1000:
                        break
                    
                    before_sig = batch[-1]["signature"]
                    fetched_count += len(batch)
            else:
                signatures_response = await client.get_signatures_for_address(address, limit=limit)
                if "error" in signatures_response or not signatures_response.get("result"):
                    logger.error(f"Could not fetch signatures: {signatures_response.get('error')}")
                    return []
                signatures = signatures_response["result"]
            
            logger.info(f"Found {len(signatures)} signatures. Fetching transactions...")

            # Use a semaphore to limit concurrent requests and a retry mechanism to handle RPC errors.
            sem = asyncio.Semaphore(15)  # Reduced concurrency to avoid rate limiting
            tx_tasks = [_fetch_transaction_with_retry(client, sig, sem) for sig in signatures]
            tx_responses = await asyncio.gather(*tx_tasks)

            for sig_info, tx_response in zip(signatures, tx_responses):
                parsed_data.extend(_parse_transaction_details(tx_response, sig_info))
    except Exception as e:
        logger.error(f"An error occurred during transaction fetching: {e}")

    return parsed_data


async def fetch_and_parse_new_transactions(address: str, rpc_url: str, last_signature: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetches transactions since the last known signature."""
    new_signatures_info = []
    try:
        async with AsyncCustomSolanaClient(rpc_url) as client:
            before_sig = None
            found_last_sig = False
            newest_signature = None

            # Fetch signatures page by page until we find the last known one
            for _ in range(10): # Limit to 10 pages (10000 txs) to avoid abuse
                response = await client.get_signatures_for_address(address, limit=1000, before=before_sig)
                if "error" in response or not response.get("result"):
                    break
                
                batch = response["result"]
                if not batch:
                    break

                if not newest_signature:
                    newest_signature = batch[0]["signature"]

                for sig_info in batch:
                    if sig_info["signature"] == last_signature:
                        found_last_sig = True
                        break
                    new_signatures_info.append(sig_info)
                
                if found_last_sig or len(batch) < 1000:
                    break
                
                before_sig = batch[-1]["signature"]

            if not new_signatures_info:
                return [], last_signature

            # Now fetch and parse the new transactions
            parsed_data = []
            # Use a semaphore to limit concurrent requests and a retry mechanism to handle RPC errors.
            sem = asyncio.Semaphore(15)  # Reduced concurrency to avoid rate limiting
            tx_tasks = [_fetch_transaction_with_retry(client, sig, sem) for sig in new_signatures_info]
            tx_responses = await asyncio.gather(*tx_tasks)

            for sig_info, tx_response in zip(new_signatures_info, tx_responses):
                parsed_data.extend(_parse_transaction_details(tx_response, sig_info))

            return parsed_data, newest_signature

    except Exception as e:
        logger.error(f"Error during new transaction fetch for {address}: {e}")
        return [], last_signature


async def get_token_details(address: str, rpc_url: str) -> Dict[str, Any]:
    """Fetches details for a given SPL token."""
    details = {}
    try:
        async with AsyncCustomSolanaClient(rpc_url) as client:
            # Get supply and decimals
            supply_res = await client.get_token_supply(address)
            if supply_res and supply_res.get("result"):
                supply_value = supply_res["result"]["value"]
                details["supply"] = supply_value.get("uiAmountString", supply_value.get("amount"))
                details["decimals"] = supply_value.get("decimals")

            # Get mint authority info from account data
            info_res = await client.get_account_info(address)
            if info_res and info_res.get("result") and info_res["result"].get("value"):
                parsed_data = info_res["result"]["value"].get("data", {}).get("parsed", {})
                if parsed_data and parsed_data.get("type") == "mint":
                    parsed_info = parsed_data.get("info", {})
                    details["mint_authority"] = parsed_info.get("mintAuthority")
                    if parsed_info.get("freezeAuthority"):
                        details["freeze_authority"] = parsed_info.get("freezeAuthority")

    except Exception as e:
        logger.error(f"Could not fetch token details for {address}: {e}")
    return details


async def get_wallet_balance(address: str, rpc_url: str, api_key: str) -> str:
    """Fetches and formats the wallet balance (SOL and SPL tokens)."""
    try:
        async with AsyncCustomSolanaClient(rpc_url) as client:
            # Get SOL balance
            sol_balance_res = await client.get_account_info(address)
            sol_balance = 0
            if sol_balance_res and sol_balance_res.get("result") and sol_balance_res["result"].get("value"):
                sol_balance = sol_balance_res["result"]["value"].get("lamports", 0) / 1_000_000_000

            # Get SPL token balances
            token_accounts_res = await client.get_token_accounts_by_owner(address)
            token_balances = []
            if token_accounts_res and "result" in token_accounts_res and token_accounts_res["result"].get("value"):
                for acc in token_accounts_res["result"]["value"]:
                    try:
                        acc_info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        balance_info = acc_info.get("tokenAmount", {})
                        balance = float(balance_info.get("uiAmountString", "0"))
                        mint = acc_info.get("mint")
                        if balance > 0:
                            token_balances.append({"mint": mint, "balance": balance})
                    except (ValueError, TypeError):
                        continue
            
            # Get prices
            sol_price_data = await get_token_prices(["So11111111111111111111111111111111111111112"], api_key)
            sol_price = sol_price_data.get("So11111111111111111111111111111111111111112", {}).get("value", 0)
            
            token_mints = [tb['mint'] for tb in token_balances]
            token_prices = await get_token_prices(token_mints, api_key) if token_mints else {}
            
            # Format the message
            message_lines = [f"💰 **Balance for wallet:** `{address}`\n"]
            total_usd_value = 0
            
            # SOL
            sol_usd_value = sol_balance * sol_price
            total_usd_value += sol_usd_value
            message_lines.append(f"◎ **SOL:** `{sol_balance:,.6f}` (~${sol_usd_value:,.2f})")
            
            if token_balances:
                message_lines.append("\n🪙 **Tokens:**")
                sorted_tokens = sorted(token_balances, key=lambda x: token_prices.get(x['mint'], {}).get('value', 0) * x['balance'], reverse=True)
                
                for token in sorted_tokens:
                    price = token_prices.get(token['mint'], {}).get('value', 0)
                    symbol = token_prices.get(token['mint'], {}).get('symbol', token['mint'][:6]+"...")
                    usd_value = token['balance'] * price
                    total_usd_value += usd_value
                    
                    value_str = f" (~${usd_value:,.2f})" if usd_value > 0.01 else ""
                    message_lines.append(f"   • `{token['balance']:,.6f}` **{symbol}**{value_str}")
                    message_lines.append(f"     `{token['mint']}`")
            else:
                message_lines.append("\nℹ️ No SPL tokens found in this wallet.")

            message_lines.insert(1, f"💵 **Total Value:** `${total_usd_value:,.2f}`")
            return "\n".join(message_lines)

    except Exception as e:
        logger.error(f"Could not fetch balance for {address}: {e}")
        return f"❌ Failed to get balance for `{address}`. Please check the address or try again later."


# --- Price & Monitoring Helpers ---
async def get_token_prices(token_addresses: List[str], api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetches token prices from Birdeye API by making concurrent requests for each token."""
    if not token_addresses:
        return {}
    
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.error("Birdeye API key is missing. Please set it in config.py.")
        return {}

    async def _fetch_one_price(client: httpx.AsyncClient, address: str, sem: asyncio.Semaphore):
        """Inner function to fetch, parse, and retry a single token price."""
        url = "https://public-api.birdeye.so/defi/price"
        params = {
            "address": address,
            "check_liquidity": "1",
            "include_liquidity": "false",
        }
        headers = {"X-API-KEY": api_key}
        MAX_RETRIES = 3
        delay = 1.0

        async with sem:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.get(url, params=params, headers=headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    if data.get("success") and "data" in data and data.get("data"):
                        price_value = data["data"].get("value")
                        if price_value is not None:
                            return address, {"value": price_value}
                    # If success is true but no data, it's a valid "not found"
                    return address, None
                except httpx.HTTPStatusError as e:
                    # Don't retry on 404, it means token not found on Birdeye
                    if e.response.status_code == 404:
                        logger.info(f"Token {address} not found on Birdeye (404), not retrying.")
                        return address, None
                    logger.warning(f"Price fetch attempt {attempt + 1}/{MAX_RETRIES} for {address} failed: {e}")
                except Exception as e:
                    logger.warning(f"Price fetch attempt {attempt + 1}/{MAX_RETRIES} for {address} failed with unexpected error: {e}")

                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
        
        logger.error(f"Failed to fetch price for {address} after all retries.")
        return address, None

    formatted_prices = {}
    sem = asyncio.Semaphore(10)  # Limit concurrency to 10 requests at a time
    
    # Use set to avoid duplicate requests for the same token address
    unique_addresses = list(set(token_addresses))
    
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one_price(client, addr, sem) for addr in unique_addresses]
        results = await asyncio.gather(*tasks)

    for address, price_info in results:
        if price_info:
            formatted_prices[address] = price_info

    return formatted_prices
