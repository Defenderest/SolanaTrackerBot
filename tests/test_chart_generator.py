import pytest
from io import BytesIO
from chart_generator import create_daily_volume_chart

# Mock transactions data
WALLET_TRANSACTIONS = [
    {'timestamp': '2023-01-01 10:00:00', 'amount': '10', 'wallet_1': 'my_wallet', 'wallet_2': 'other_wallet', 'authority': ''},
    {'timestamp': '2023-01-01 12:00:00', 'amount': '5', 'wallet_1': 'other_wallet', 'wallet_2': 'my_wallet', 'authority': ''},
    {'timestamp': '2023-01-02 11:00:00', 'amount': '20', 'wallet_1': 'my_wallet', 'wallet_2': 'another_wallet', 'authority': ''},
]

TOKEN_MINT_TRANSACTIONS = [
    {'timestamp': '2023-01-01 10:00:00', 'amount': '1000'},
    {'timestamp': '2023-01-02 12:00:00', 'amount': '500'},
]


def test_create_chart_with_no_transactions():
    """Tests that the function returns None for empty transaction list."""
    chart = create_daily_volume_chart([], 'some_address')
    assert chart is None


def test_create_chart_for_wallet():
    """Tests chart creation for a regular wallet address."""
    chart = create_daily_volume_chart(WALLET_TRANSACTIONS, 'my_wallet', is_token_mint=False)
    assert isinstance(chart, BytesIO)
    assert len(chart.getvalue()) > 0


def test_create_chart_for_token_mint():
    """Tests chart creation for a token mint address."""
    chart = create_daily_volume_chart(TOKEN_MINT_TRANSACTIONS, 'token_mint_address', is_token_mint=True)
    assert isinstance(chart, BytesIO)
    assert len(chart.getvalue()) > 0


def test_create_chart_with_unplottable_data():
    """Tests that the function returns None if processed data is empty."""
    # Transactions with amounts that will be dropped
    bad_transactions = [
        {'timestamp': '2023-01-01 10:00:00', 'amount': 'not_a_number'},
    ]
    chart = create_daily_volume_chart(bad_transactions, 'some_address')
    assert chart is None
