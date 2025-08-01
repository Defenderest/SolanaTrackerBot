import logging
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
from io import BytesIO


def create_daily_volume_chart(transactions: list, address: str, token_accounts: list = None, is_token_mint: bool = False) -> BytesIO:
    """Создает гистограмму объема транзакций, с улучшенным дизайном и адаптивностью."""
    if not transactions:
        return None

    try:
        df = pd.DataFrame(transactions)
        if df.empty:
            return None
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        df.dropna(subset=['amount', 'timestamp'], inplace=True)

        if df.empty:
            return None

        address = address.strip()
        # --- Улучшенная адаптивная логика для периода группировки ---
        time_span = df['timestamp'].max() - df['timestamp'].min()
        if time_span.days < 3:  # до 3 дней -> часовой
            resample_period, xlabel, title_period = 'h', 'Время', 'часовой'
            date_format = mdates.DateFormatter('%d-%b %H:%M')
        elif time_span.days <= 90:  # до 3 месяцев -> дневной
            resample_period, xlabel, title_period = 'D', 'Дата', 'дневной'
            date_format = mdates.DateFormatter('%d-%b-%Y')
        else:  # более 3 месяцев -> недельный
            resample_period, xlabel, title_period = 'W', 'Неделя', 'недельный'
            date_format = mdates.DateFormatter('%d-%b-%Y')

        # --- Обновленный, более современный дизайн ---
        plt.style.use('seaborn-v0_8-darkgrid')
        plt.rcParams.update({
            'figure.facecolor': '#1E1E1E', 'axes.facecolor': '#1E1E1E',
            'text.color': '#EAEAEA', 'axes.labelcolor': '#EAEAEA',
            'xtick.color': '#CCCCCC', 'ytick.color': '#CCCCCC',
            'grid.color': '#444444', 'font.family': 'sans-serif',
            'figure.dpi': 120
        })
        
        fig, ax = plt.subplots(figsize=(12, 7))
        logger = logging.getLogger(__name__)

        # --- Логика для разных типов графиков ---
        if is_token_mint:
            df['volume'] = df['amount']
            summary = df.set_index('timestamp').resample(resample_period).agg({'volume': 'sum'})
            summary = summary[summary['volume'] > 0].reset_index()
            
            ax.bar(summary['timestamp'], summary['volume'], color='#3498db', label='Объем', width=0.8, edgecolor='#a9cce3', linewidth=0.6)
            ax.set_title(f'Объем торгов ({title_period}) для токена\n{address}', fontsize=16, pad=20)

        else: # is_wallet
            if token_accounts is None: token_accounts = []
            token_accounts_set = set(token_accounts)

            # Гарантируем, что поля с адресами являются строками и не содержат None
            df['wallet_1'] = df.get('wallet_1', pd.Series(dtype=str)).fillna('')
            df['wallet_2'] = df.get('wallet_2', pd.Series(dtype=str)).fillna('')
            if 'authority' not in df.columns:
                df['authority'] = ''
            df['authority'] = df['authority'].fillna('')

            df['incoming'] = df.apply(lambda row: row['amount'] if row['wallet_2'] == address or row['wallet_2'] in token_accounts_set else 0, axis=1)
            df['outgoing'] = df.apply(lambda row: row['amount'] if row['wallet_1'] == address or row['authority'] == address else 0, axis=1)
            
            summary = df.set_index('timestamp').resample(resample_period).agg({'incoming': 'sum', 'outgoing': 'sum'})
            summary = summary[(summary['incoming'] > 0) | (summary['outgoing'] > 0)].reset_index()

            ax.bar(summary['timestamp'], summary['incoming'], color='#2ecc71', label='Входящие', width=0.8, edgecolor='#a9dfbf', linewidth=0.6)
            ax.bar(summary['timestamp'], summary['outgoing'].apply(lambda x: -x), color='#e74c3c', label='Исходящие', width=0.8, edgecolor='#f5b7b1', linewidth=0.6)
            ax.legend(frameon=False, labelcolor='#EAEAEA')
            ax.set_title(f'Объем транзакций ({title_period}) для {address[:6]}...{address[-4:]}', fontsize=16, pad=20)

        if summary.empty:
            logger.warning(f"Chart summary is empty for address {address}. No data to plot.")
        else:
            logger.info(f"Chart summary for address {address}:\n{summary.to_string()}")

        # --- Общее форматирование ---
        ax.set_ylabel('Объем', fontsize=12)
        ax.set_xlabel(xlabel, fontsize=12)
        
        fig.autofmt_xdate(rotation=30, ha='right')
        ax.xaxis.set_major_formatter(date_format)
        ax.grid(True, which='both', linestyle=':', linewidth=0.6)
        
        for spine in ax.spines.values():
            spine.set_visible(False)
        
        if not is_token_mint:
            ax.axhline(0, color='#888888', linewidth=1)

        # --- Исправленный форматтер для оси Y ---
        def y_axis_formatter(y, _):
            return f'{abs(y):,.2f}'
        ax.yaxis.set_major_formatter(FuncFormatter(y_axis_formatter))
        
        plt.tight_layout(pad=1.5)

        # --- Сохранение в буфер ---
        buf = BytesIO()
        plt.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none')
        buf.seek(0)
        plt.close(fig)

        return buf
    except Exception as e:
        # В случае ошибки при создании графика возвращаем None
        logging.getLogger(__name__).error(f"Failed to create chart: {e}", exc_info=True)
        return None
