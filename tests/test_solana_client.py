import pytest
import ujson
from unittest.mock import AsyncMock, MagicMock
from solana_client import AsyncCustomSolanaClient


@pytest.mark.asyncio
async def test_make_request_success(mocker):
    """Tests a successful request."""
    mock_session = MagicMock()
    mock_session.close = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json = AsyncMock(return_value={"result": "success"})

    # Configure the async context manager for session.post
    mock_session.post.return_value.__aenter__.return_value = mock_response

    mocker.patch('solana_client.aiohttp.ClientSession', return_value=mock_session)

    async with AsyncCustomSolanaClient("http://fake.rpc.com") as client:
        result = await client._make_request("test_method", [])
        assert result == {"result": "success"}
        mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_make_request_retry_on_429(mocker):
    """Tests that the client retries on a 429 status code."""
    mock_session = MagicMock()
    mock_session.close = AsyncMock()

    # First response is 429, second is 200
    response_429 = MagicMock()
    response_429.status = 429
    response_ok = MagicMock()
    response_ok.status = 200
    response_ok.json = AsyncMock(return_value={"result": "success after retry"})

    # Set up the context manager mock for side_effect
    enter_429 = AsyncMock(return_value=response_429)
    exit_mock = AsyncMock()
    enter_ok = AsyncMock(return_value=response_ok)

    mock_session.post.side_effect = [
        MagicMock(__aenter__=enter_429, __aexit__=exit_mock),
        MagicMock(__aenter__=enter_ok, __aexit__=exit_mock)
    ]

    mocker.patch('solana_client.aiohttp.ClientSession', return_value=mock_session)
    mocker.patch('asyncio.sleep', AsyncMock())  # patch sleep to not wait

    async with AsyncCustomSolanaClient("http://fake.rpc.com") as client:
        result = await client._make_request("test_method", [], retry_count=2)
        assert result == {"result": "success after retry"}
        assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_make_request_auth_failure_on_403(mocker):
    """Tests that the client raises an exception on a 403 status code."""
    mock_session = MagicMock()
    mock_session.close = AsyncMock()
    response_403 = MagicMock()
    response_403.status = 403

    mock_session.post.return_value.__aenter__.return_value = response_403

    mocker.patch('solana_client.aiohttp.ClientSession', return_value=mock_session)

    with pytest.raises(Exception, match="Authentication failed"):
        async with AsyncCustomSolanaClient("http://fake.rpc.com") as client:
            await client._make_request("test_method", [])


@pytest.mark.asyncio
async def test_get_transaction_uses_cache(mocker):
    """Tests that getTransaction method uses the internal cache."""
    mock_session = MagicMock()
    mock_session.close = AsyncMock()
    mocker.patch('solana_client.aiohttp.ClientSession', return_value=mock_session)

    async with AsyncCustomSolanaClient("http://fake.rpc.com") as client:
        # Manually set a cache entry
        params = ["fake_sig", {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        cache_key = f'getTransaction:{ujson.dumps(params)}'
        client.transaction_cache[cache_key] = {"result": "cached_data"}

        result = await client.get_transaction("fake_sig")

        assert result == {"result": "cached_data"}
        # _make_request should return from cache before making a POST call
        mock_session.post.assert_not_called()
