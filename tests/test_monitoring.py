import pytest
from unittest.mock import AsyncMock, MagicMock
from monitoring import format_transaction_notification

# Mock transaction info from get_transaction RPC call result
SAMPLE_TX_INFO_SOL = {
    "meta": {
        "err": None,
        "preBalances": [10000000000, 5000000000],
        "postBalances": [9000000000, 6000000000],
        "preTokenBalances": [],
        "postTokenBalances": []
    },
    "transaction": {
        "message": {
            "accountKeys": ["my_wallet", "other_wallet"]
        }
    },
    "signature": "sol_sig_123"
}

SAMPLE_TX_INFO_TOKEN = {
    "meta": {
        "err": None,
        "preBalances": [10000000000],
        "postBalances": [10000000000],
        "preTokenBalances": [
            {"mint": "USDC_mint", "owner": "my_wallet", "uiTokenAmount": {"uiAmountString": "100.0"}}
        ],
        "postTokenBalances": [
            {"mint": "USDC_mint", "owner": "my_wallet", "uiTokenAmount": {"uiAmountString": "50.0"}}
        ]
    },
    "transaction": {
        "message": {
            "accountKeys": ["my_wallet"]
        }
    },
    "signature": "token_sig_456"
}


@pytest.mark.asyncio
async def test_format_notification_sol_send(mocker):
    """Tests formatting for sending SOL."""
    mocker.patch('monitoring.get_token_prices', AsyncMock(return_value={}))

    mock_client = AsyncMock()
    mock_client.get_token_accounts_by_owner.return_value = {"result": {"value": []}}
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('monitoring.AsyncCustomSolanaClient', mock_async_client_class)

    message = await format_transaction_notification(SAMPLE_TX_INFO_SOL, "my_wallet", "fake_rpc")

    assert "🔴 Отправлено" in message
    assert "1.000000" in message
    assert "SOL" in message
    assert "sol_sig_123" in message


@pytest.mark.asyncio
async def test_format_notification_token_send(mocker):
    """Tests formatting for sending an SPL token."""
    mock_prices = {"USDC_mint": {"symbol": "USDC"}}
    mocker.patch('monitoring.get_token_prices', AsyncMock(return_value=mock_prices))

    mock_client = AsyncMock()
    mock_client.get_token_accounts_by_owner.return_value = {"result": {"value": []}}
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('monitoring.AsyncCustomSolanaClient', mock_async_client_class)

    message = await format_transaction_notification(SAMPLE_TX_INFO_TOKEN, "my_wallet", "fake_rpc")

    assert "🔴 Отправлено" in message
    assert "50.000000" in message
    assert "USDC" in message
    assert "token_sig_456" in message


@pytest.mark.asyncio
async def test_format_notification_failed_tx():
    """Tests that failed transactions produce no notification."""
    failed_tx = SAMPLE_TX_INFO_SOL.copy()
    failed_tx["meta"]["err"] = {"InstructionError": [0, "some error"]}

    message = await format_transaction_notification(failed_tx, "my_wallet", "fake_rpc")

    assert message == ""


@pytest.mark.asyncio
async def test_format_notification_no_change(mocker):
    """Tests that transactions with no balance change for the wallet produce no notification."""
    tx_no_change = SAMPLE_TX_INFO_TOKEN.copy()
    # Make pre and post balances the same
    tx_no_change["meta"]["postTokenBalances"][0]["uiTokenAmount"]["uiAmountString"] = "100.0"

    mocker.patch('monitoring.get_token_prices', AsyncMock(return_value={}))
    
    mock_client = AsyncMock()
    mock_client.get_token_accounts_by_owner.return_value = {"result": {"value": []}}
    mock_async_client_class = MagicMock()
    mock_async_client_class.return_value.__aenter__.return_value = mock_client
    mocker.patch('monitoring.AsyncCustomSolanaClient', mock_async_client_class)

    message = await format_transaction_notification(tx_no_change, "my_wallet", "fake_rpc")

    assert message == ""
