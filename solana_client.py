import aiohttp
import asyncio
from typing import Optional, Dict, List, Any
import logging
import ujson

logger = logging.getLogger(__name__)

class AsyncCustomSolanaClient:
    def __init__(self, rpc_url: str):
        if not rpc_url:
            rpc_url = "https://api.mainnet-beta.solana.com"
        self.rpc_url = rpc_url
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        if 'alchemy' in rpc_url.lower():
            api_key = rpc_url.split('/')[-1]
            self.headers.update({
                'User-Agent': 'Mozilla/5.0',
                'Origin': 'https://solana.com',
                'Referer': 'https://solana.com/',
                'Authorization': f'Bearer {api_key}'
            })
        elif 'quiknode' in rpc_url.lower():
            # QuickNode authenticates via the URL, no special headers needed for standard RPC.
            pass

        self.request_id = 1
        self.session = None
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.semaphore = asyncio.Semaphore(50)
        self.transaction_cache = {}

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=True, limit=100)
        self.session = aiohttp.ClientSession(
            connector=connector,
            headers=self.headers,
            timeout=self.timeout,
            trust_env=True,
            json_serialize=ujson.dumps
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _make_request(self, method: str, params: List[Any], retry_count: int = 3) -> Dict:
        async with self.semaphore:
            cache_key = f"{method}:{ujson.dumps(params)}"
            if method == "getTransaction" and cache_key in self.transaction_cache:
                return self.transaction_cache[cache_key]

            for attempt in range(retry_count):
                payload = {
                    "jsonrpc": "2.0",
                    "id": self.request_id,
                    "method": method,
                    "params": params
                }
                self.request_id += 1

                try:
                    async with self.session.post(
                            self.rpc_url,
                            json=payload,
                            allow_redirects=True,
                            verify_ssl=True
                    ) as response:
                        if response.status == 429:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        elif response.status == 403:
                            raise Exception("Authentication failed. Check your RPC URL and API key.")

                        response.raise_for_status()
                        result = await response.json(loads=ujson.loads)

                        if method == "getTransaction":
                            self.transaction_cache[cache_key] = result

                        return result
                except Exception as e:
                    if attempt == retry_count - 1:
                        logger.error(f"Request error after {retry_count} attempts: {str(e)}")
                        raise
                    await asyncio.sleep(2 ** attempt)
            return {"error": "Max retries reached"}

    async def get_signatures_for_address(self, address: str, before: Optional[str] = None,
                                         until: Optional[str] = None, limit: int = 1000):
        config = {"limit": limit}
        if before:
            config["before"] = before
        if until:
            config["until"] = until
        return await self._make_request("getSignaturesForAddress", [address, config])

    async def get_transaction(self, signature: str, encoding: str = "jsonParsed"):
        return await self._make_request(
            "getTransaction",
            [signature, {"encoding": encoding, "maxSupportedTransactionVersion": 0}]
        )

    async def get_token_accounts_by_owner(self, owner: str, mint: Optional[str] = None):
        filter_param = {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
        if mint:
            filter_param = {"mint": mint}

        return await self._make_request(
            "getTokenAccountsByOwner",
            [owner, filter_param, {"encoding": "jsonParsed"}]
        )

    async def get_token_supply(self, mint: str):
        return await self._make_request("getTokenSupply", [mint])

    async def get_account_info(self, pubkey: str, encoding: str = "jsonParsed"):
        return await self._make_request(
            "getAccountInfo",
            [pubkey, {"encoding": encoding}]
        )
