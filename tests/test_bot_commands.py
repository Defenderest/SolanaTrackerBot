import pytest
from unittest.mock import AsyncMock, MagicMock
import bot_commands
from bot_commands import add_address, list_addresses, text_handler, _execute_balance, cancel


# Mock telegram Update and Context objects
@pytest.fixture
def mock_update():
    """Provides a mocked Telegram Update object."""
    update = MagicMock()
    update.effective_chat.id = 12345
    update.message = AsyncMock()
    update.message.text = "test message"
    update.message.chat_id = 12345
    update.callback_query = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Provides a mocked Telegram CallbackContext object."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {}
    context.application = MagicMock()
    return context


@pytest.mark.asyncio
async def test_add_address(mock_update, mock_context, mocker):
    """Tests the /add command."""
    mock_load = mocker.patch('bot_commands.load_user_data', return_value={})
    mock_save = mocker.patch('bot_commands.save_user_data')

    mock_context.args = ["wsol", "sol_address"]

    await add_address(mock_update, mock_context)

    mock_load.assert_called_once()
    mock_save.assert_called_once_with({'12345': {'aliases': {'wsol': 'sol_address'}}})
    mock_update.message.reply_text.assert_called_once()
    assert "saved" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_list_addresses_empty(mock_update, mock_context, mocker):
    """Tests /list command when no addresses are saved."""
    mocker.patch('bot_commands.load_user_data', return_value={})
    mock_send_long = mocker.patch('bot_commands.send_long_message', new_callable=AsyncMock)

    await list_addresses(mock_update, mock_context)

    # Instead of checking bot.send_message, we check our helper
    mock_send_long.assert_awaited_once()
    sent_text = mock_send_long.call_args.args[2]
    assert "You have no saved addresses" in sent_text


@pytest.mark.asyncio
async def test_execute_balance(mock_update, mock_context, mocker):
    """Tests the core balance execution logic."""
    mocker.patch('bot_commands.get_rpc_url', return_value="fake_rpc")
    mocker.patch('bot_commands.BIRDEYE_API_KEY', "fake_key")
    mock_get_balance = mocker.patch('bot_commands.get_wallet_balance', AsyncMock(return_value="Formatted Balance"))
    mock_send_long = mocker.patch('bot_commands.send_long_message', new_callable=AsyncMock)

    await _execute_balance(mock_update, mock_context, "test_address")

    mock_get_balance.assert_awaited_once_with("test_address", "fake_rpc", "fake_key")
    # Check that placeholder is sent, deleted, and final message sent via helper
    assert mock_context.bot.send_message.call_count == 1
    assert mock_context.bot.delete_message.call_count == 1
    mock_send_long.assert_awaited_once()
    assert "Formatted Balance" in mock_send_long.call_args.args[2]


@pytest.mark.asyncio
async def test_text_handler_for_balance(mock_update, mock_context, mocker):
    """Tests the text handler conversation flow for getting a balance."""
    mock_resolve = mocker.patch('bot_commands.resolve_address', return_value="resolved_address")
    mock_execute_balance = mocker.patch('bot_commands._execute_balance', new_callable=AsyncMock)

    # Simulate user clicking "Wallet Balance" button, bot asks for address
    mock_context.user_data['state'] = 'balance'

    # Simulate user sending an address
    mock_update.message.text = "my_wallet_alias"
    await text_handler(mock_update, mock_context)

    mock_resolve.assert_called_once_with(12345, "my_wallet_alias")
    mock_execute_balance.assert_awaited_once_with(mock_update, mock_context, "resolved_address")
    # State should be cleared after execution
    assert 'state' not in mock_context.user_data


@pytest.mark.asyncio
async def test_cancel_command(mock_update, mock_context, mocker):
    """Tests that the /cancel command clears state and shows main menu."""
    mock_main_menu = mocker.patch('bot_commands.main_menu', new_callable=AsyncMock)
    mock_context.user_data['state'] = 'awaiting_something'

    await cancel(mock_update, mock_context)

    assert 'state' not in mock_context.user_data
    mock_update.message.reply_text.assert_called_once_with("Operation cancelled. Returning to the main menu.")
    mock_main_menu.assert_awaited_once()
