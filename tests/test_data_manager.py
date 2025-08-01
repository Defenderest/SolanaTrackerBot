import pytest

import data_manager  # To patch USER_DATA_FILE
from data_manager import load_user_data, save_user_data, resolve_address, get_rpc_url

MOCK_DEFAULT_RPC = "https://default.rpc.com"


@pytest.fixture(autouse=True)
def mock_default_rpc(mocker):
    """Mocks the default RPC URL for all tests in this file."""
    mocker.patch('data_manager.DEFAULT_RPC_URL', MOCK_DEFAULT_RPC)


def test_save_and_load_user_data(tmp_path):
    """Tests that data can be saved and loaded back correctly."""
    file_path = tmp_path / "user_data.json"
    data_manager.USER_DATA_FILE = str(file_path)

    test_data = {"123": {"aliases": {"wsol": "sol_address"}}}
    save_user_data(test_data)

    loaded_data = load_user_data()
    assert loaded_data == test_data


def test_load_non_existent_data(tmp_path):
    """Tests that loading a non-existent or invalid file returns an empty dictionary."""
    # Test with a non-existent file
    file_path = tmp_path / "non_existent.json"
    data_manager.USER_DATA_FILE = str(file_path)
    assert load_user_data() == {}

    # Test with an empty/invalid json file
    file_path.write_text("not json")
    assert load_user_data() == {}


def test_resolve_address(mocker):
    """Tests that an alias is correctly resolved to an address."""
    mock_data = {"123": {"aliases": {"wsol": "sol_address"}}}
    mocker.patch('data_manager.load_user_data', return_value=mock_data)

    # Test resolving a known alias
    assert resolve_address(123, "wsol") == "sol_address"
    # Test resolving an unknown alias (should return the input)
    assert resolve_address(123, "unknown") == "unknown"
    # Test resolving for a user with no aliases
    assert resolve_address(456, "wsol") == "wsol"


def test_get_rpc_url(mocker):
    """Tests that the correct RPC URL is returned."""
    mock_data = {
        "123": {"rpc_url": "https://custom.rpc.com"},
        "456": {}
    }
    mocker.patch('data_manager.load_user_data', return_value=mock_data)

    # User with a custom RPC
    assert get_rpc_url(123) == "https://custom.rpc.com"
    # User without a custom RPC, should return default
    assert get_rpc_url(456) == MOCK_DEFAULT_RPC
    # User not in data, should return default
    assert get_rpc_url(789) == MOCK_DEFAULT_RPC
