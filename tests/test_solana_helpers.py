import pytest
from unittest.mock import AsyncMock, MagicMock
from solana_helpers import _parse_transaction_details, get_token_prices, fetch_and_parse_transactions, get_token_details, get_wallet_balance

# Sample data for mocking API responses
SAMPLE_SIG_INFO = {'signature': 'dummy_sig_123', 'slot': 12345678, 'blockTime': 1672531200}
SAMPLE_TX_RESPONSE = {
    'jsonrpc': '2.0',
    'result': {
        'blockTime': 1672531200,
        'slot': 12345678,
        'transaction': {
            'message': {
                'instructions': [
                    {
                        'parsed': {
                            'type': 'transferChecked',
                            'info': {
                                'source': 'SourceWallet',
                                'destination': 'DestinationWallet',
                                'authority': 'AuthorityWallet',
                                'tokenAmount': {'uiAmountString': '123.45'}
                            }
                        },
                        'program': 'spl-token'
                    },
                    {
                        'parsed': {
                            'type': 'unsupported_type',
                            'info': {}
                        }
                    }
                ]
            }
        }
    },
    'id': 1
}

@pytest.mark.asyncio
async def test_parse_transaction_details():
    """Tests the internal transaction parsing logic."""
    parsed_data = _parse_transaction_details(SAMPLE_TX_RESPONSE, SAMPLE_SIG_INFO)
    
    # Should only parse one valid instruction
    assert len(parsed_data) == 1
    
    tx_info = parsed_data[0]
    assert tx_info['signature'] == 'dummy_sig_123'
    assert tx_info['wallet_1'] == 'SourceWallet'
    assert tx_info['wallet_2'] == 'DestinationWallet'
    assert tx_info['amount'] == '123.45'
    assert tx_info['type'] == 'transferChecked'

@pytest.mark.asyncio
async def test_get_token_prices_success(mocker):
    """Tests successful fetching of token prices from Birdeye."""
    # Mock httpx response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": {"value": 150.5}
    }
    
    mock_async_client = AsyncMock()
    mock_async_client.get.return_value = mock_response
    
    # Patch the client context manager to correctly handle `async with`
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_async_client
    mocker.patch('solana_helpers.httpx.AsyncClient', mock_async_client_class)
    
    token_addresses = ["So11111111111111111111111111111111111111112"]
    api_key = "fake_api_key"
    
    prices = await get_token_prices(token_addresses, api_key)
    
    assert "So11111111111111111111111111111111111111112" in prices
    assert prices["So11111111111111111111111111111111111111112"]["value"] == 150.5

@pytest.mark.asyncio
async def test_get_token_prices_missing_api_key(caplog):
    """Tests that an error is logged if the API key is missing."""
    prices = await get_token_prices(["some_address"], None)
    assert prices == {}
    assert "Birdeye API key is missing" in caplog.text

    prices = await get_token_prices(["some_address"], "YOUR_API_KEY_HERE")
    assert prices == {}
    assert "Birdeye API key is missing" in caplog.text


@pytest.mark.asyncio
async def test_fetch_and_parse_transactions(mocker):
    """Tests the main transaction fetching and parsing pipeline."""
    mock_client = AsyncMock()
    mock_client.get_signatures_for_address.return_value = {
        "result": [SAMPLE_SIG_INFO]
    }
    # This mock now returns the full structure expected by _fetch_transaction_with_retry
    mock_client.get_transaction.return_value = SAMPLE_TX_RESPONSE

    # Mock the client's context manager
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('solana_helpers.AsyncCustomSolanaClient', mock_async_client_class)

    transactions = await fetch_and_parse_transactions("some_address", "fake_rpc", limit=1)

    assert len(transactions) == 1
    assert transactions[0]['signature'] == 'dummy_sig_123'
    mock_client.get_signatures_for_address.assert_awaited_once_with("some_address", limit=1)
    mock_client.get_transaction.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_token_details(mocker):
    """Tests fetching details for an SPL token."""
    mock_client = AsyncMock()
    mock_client.get_token_supply.return_value = {
        "result": {"value": {"uiAmountString": "1000000", "decimals": 6}}
    }
    mock_client.get_account_info.return_value = {
        "result": {"value": {"data": {"parsed": {"type": "mint", "info": {
            "mintAuthority": "AuthAddress",
            "freezeAuthority": "FreezeAddress"
        }}}}}
    }

    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('solana_helpers.AsyncCustomSolanaClient', mock_async_client_class)

    details = await get_token_details("token_address", "fake_rpc")

    assert details['supply'] == "1000000"
    assert details['decimals'] == 6
    assert details['mint_authority'] == "AuthAddress"
    assert details['freeze_authority'] == "FreezeAddress"


@pytest.mark.asyncio
async def test_get_wallet_balance(mocker):
    """Tests the wallet balance formatting logic."""
    # Mock client calls
    mock_client = AsyncMock()
    # SOL balance
    mock_client.get_account_info.return_value = {"result": {"value": {"lamports": 1.5 * 1_000_000_000}}}
    # Token balances
    mock_client.get_token_accounts_by_owner.return_value = {
        "result": {"value": [{
            "account": {"data": {"parsed": {"info": {
                "tokenAmount": {"uiAmountString": "123.45"},
                "mint": "USDC_MINT"
            }}}}
        }]}
    }
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('solana_helpers.AsyncCustomSolanaClient', mock_async_client_class)

    # Mock price calls
    mock_prices = {
        "So11111111111111111111111111111111111111112": {"value": 200.0},
        "USDC_MINT": {"value": 1.0, "symbol": "USDC"}
    }
    mocker.patch('solana_helpers.get_token_prices', AsyncMock(return_value=mock_prices))

    balance_msg = await get_wallet_balance("wallet_address", "fake_rpc", "fake_api_key")

    assert "Total Value:** `$423.45`" in balance_msg
    assert "SOL:** `1.500000` (~$300.00)" in balance_msg
    assert "`123.450000` **USDC** (~$123.45)" in balance_msg
    assert "`USDC_MINT`" in balance_msg
