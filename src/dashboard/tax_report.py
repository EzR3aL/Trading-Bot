"""
Tax Report Generator for Bitget Trading Bot.

Generates comprehensive tax reports for German tax compliance with support
for both German and English languages.
"""
from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime
import csv
from io import StringIO
import logging

logger = logging.getLogger(__name__)

# Internationalization translations
TRANSLATIONS = {
    'de': {
        # Headers
        'tax_report_title': 'STEUERREPORT FÜR KRYPTOWÄHRUNGSHANDEL',
        'reporting_period': 'Berichtszeitraum',
        'generated_on': 'Erstellt am',
        'to': 'bis',

        # Disclaimer
        'disclaimer': 'HINWEIS: Dieser Bericht dient nur zu Informationszwecken. Konsultieren Sie einen Steuerberater für offizielle Steuererklärungen.',

        # Summary section
        'summary': 'ZUSAMMENFASSUNG',
        'metric': 'Metrik',
        'value': 'Wert (€)',
        'total_gains': 'Gesamtgewinne',
        'total_losses': 'Gesamtverluste',
        'net_pnl': 'Netto-Gewinn/-Verlust',
        'total_fees': 'Gesamtgebühren',
        'total_funding': 'Finanzierungskosten',
        'trade_count': 'Anzahl Trades',
        'win_rate': 'Gewinnrate',
        'open_trades_note': 'Offene Trades nicht enthalten',

        # Detailed trades section
        'detailed_trades': 'EINZELTRANSAKTIONEN',
        'date': 'Datum',
        'symbol': 'Symbol',
        'side': 'Richtung',
        'entry_price': 'Einstiegspreis (€)',
        'exit_price': 'Ausstiegspreis (€)',
        'size': 'Größe',
        'pnl': 'Gewinn-Verlust (€)',
        'fees': 'Gebühren (€)',
        'funding': 'Finanzierung (€)',
        'net_result': 'Netto-Ergebnis (€)',
        'duration': 'Haltedauer (h)',
        'long': 'LONG',
        'short': 'SHORT',

        # Monthly breakdown
        'monthly_breakdown': 'MONATLICHE AUFSCHLÜSSELUNG',
        'month': 'Monat',
        'trades': 'Trades',
        'wins': 'Gewinne',
        'win_rate_percent': 'Gewinnrate (%)',
        'total_pnl': 'Gesamt-PnL (€)',
        'total_fees_monthly': 'Gebühren (€)',
        'total_funding_monthly': 'Finanzierung (€)',
        'net': 'Netto (€)',

        # Funding payments
        'funding_payments': 'FINANZIERUNGSKOSTEN EINZELN',
        'funding_rate': 'Rate (%)',
        'position_value': 'Positionswert (€)',
        'amount': 'Betrag (€)',

        # Messages
        'no_data': 'Keine Daten für dieses Jahr',
    },
    'en': {
        # Headers
        'tax_report_title': 'TAX REPORT FOR CRYPTOCURRENCY TRADING',
        'reporting_period': 'Reporting Period',
        'generated_on': 'Generated on',
        'to': 'to',

        # Disclaimer
        'disclaimer': 'NOTE: This report is for informational purposes only. Consult a tax advisor for official tax declarations.',

        # Summary section
        'summary': 'SUMMARY',
        'metric': 'Metric',
        'value': 'Value (€)',
        'total_gains': 'Total Gains',
        'total_losses': 'Total Losses',
        'net_pnl': 'Net PnL',
        'total_fees': 'Total Fees',
        'total_funding': 'Funding Costs',
        'trade_count': 'Trade Count',
        'win_rate': 'Win Rate',
        'open_trades_note': 'Open trades not included',

        # Detailed trades section
        'detailed_trades': 'DETAILED TRADES',
        'date': 'Date',
        'symbol': 'Symbol',
        'side': 'Side',
        'entry_price': 'Entry Price (€)',
        'exit_price': 'Exit Price (€)',
        'size': 'Size',
        'pnl': 'PnL (€)',
        'fees': 'Fees (€)',
        'funding': 'Funding (€)',
        'net_result': 'Net Result (€)',
        'duration': 'Duration (h)',
        'long': 'LONG',
        'short': 'SHORT',

        # Monthly breakdown
        'monthly_breakdown': 'MONTHLY BREAKDOWN',
        'month': 'Month',
        'trades': 'Trades',
        'wins': 'Wins',
        'win_rate_percent': 'Win Rate (%)',
        'total_pnl': 'Total PnL (€)',
        'total_fees_monthly': 'Fees (€)',
        'total_funding_monthly': 'Funding (€)',
        'net': 'Net (€)',

        # Funding payments
        'funding_payments': 'FUNDING PAYMENTS DETAIL',
        'funding_rate': 'Rate (%)',
        'position_value': 'Position Value (€)',
        'amount': 'Amount (€)',

        # Messages
        'no_data': 'No data for this year',
    }
}


@dataclass
class TaxReportConfig:
    """Configuration for tax report generation."""
    year: int
    language: str  # 'de' or 'en'
    include_funding: bool = True
    include_monthly_breakdown: bool = True


def translate(key: str, language: str) -> str:
    """
    Translate a key to the specified language.

    Args:
        key: Translation key
        language: Language code ('de' or 'en')

    Returns:
        Translated string, falls back to English if key not found
    """
    return TRANSLATIONS.get(language, TRANSLATIONS['en']).get(key, key)


class TaxReportGenerator:
    """
    Generates tax reports with aggregated trade data for tax compliance.

    Responsibilities:
    - Query all trades for a calendar year
    - Aggregate realized gains/losses, fees, funding costs
    - Generate monthly breakdowns
    - Create CSV exports in German tax format
    """

    def __init__(self, trade_db, funding_tracker):
        """
        Initialize the tax report generator.

        Args:
            trade_db: TradeDatabase instance
            funding_tracker: FundingTracker instance
        """
        self.trade_db = trade_db
        self.funding_tracker = funding_tracker

    async def get_available_years(self) -> List[int]:
        """
        Get list of years that have trade data.

        Returns:
            List of years in descending order (e.g., [2025, 2024, 2023])
        """
        try:
            import aiosqlite
            async with aiosqlite.connect(self.trade_db.db_path) as db:
                cursor = await db.execute("""
                    SELECT DISTINCT strftime('%Y', entry_time) as year
                    FROM trades
                    WHERE entry_time IS NOT NULL
                    ORDER BY year DESC
                """)
                rows = await cursor.fetchall()
                return [int(row[0]) for row in rows if row[0]]
        except Exception as e:
            logger.error(f"Error getting available years: {e}")
            return []

    async def get_year_data(self, year: int, language: str = 'de') -> Dict[str, Any]:
        """
        Get complete tax report data for a specific year.

        Args:
            year: Calendar year (e.g., 2025)
            language: Language code ('de' or 'en')

        Returns:
            Dictionary with summary, trades, and monthly breakdown
        """
        try:
            # Get all closed trades for the year
            trades = await self.trade_db.get_trades_by_year(year)

            # Get open trades count for informational purposes
            open_trades = await self.trade_db.get_open_trades()
            open_trades_count = len(open_trades) if open_trades else 0

            # Aggregate summary
            summary = await self.aggregate_year_summary(year, trades)
            summary['open_trades_count'] = open_trades_count

            # Monthly breakdown
            monthly_breakdown = await self.aggregate_monthly_summary(year, trades)

            # Get funding payments
            funding_payments = await self.get_funding_payments(year)

            # Convert trades to dict format
            trades_data = [self._trade_to_dict(trade) for trade in trades]

            return {
                'year': year,
                'language': language,
                'summary': summary,
                'trades': trades_data,
                'monthly_breakdown': monthly_breakdown,
                'funding_payments': funding_payments,
            }
        except Exception as e:
            logger.error(f"Error getting year data for {year}: {e}")
            return {
                'year': year,
                'language': language,
                'summary': {},
                'trades': [],
                'monthly_breakdown': [],
                'funding_payments': [],
            }

    async def aggregate_year_summary(self, year: int, trades: List = None) -> Dict[str, Any]:
        """
        Aggregate yearly summary statistics.

        Args:
            year: Calendar year
            trades: Optional list of trades (if None, will fetch)

        Returns:
            Dictionary with aggregated statistics
        """
        if trades is None:
            trades = await self.trade_db.get_trades_by_year(year)

        if not trades:
            return {
                'total_gains': 0.0,
                'total_losses': 0.0,
                'net_pnl': 0.0,
                'total_fees': 0.0,
                'total_funding': 0.0,
                'trade_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0.0,
            }

        total_gains = sum(trade.pnl for trade in trades if trade.pnl and trade.pnl > 0)
        total_losses = sum(trade.pnl for trade in trades if trade.pnl and trade.pnl < 0)
        total_fees = sum(trade.fees or 0 for trade in trades)
        total_funding = sum(trade.funding_paid or 0 for trade in trades)

        win_count = sum(1 for trade in trades if trade.pnl and trade.pnl > 0)
        loss_count = sum(1 for trade in trades if trade.pnl and trade.pnl <= 0)
        win_rate = (win_count / len(trades) * 100) if trades else 0.0

        # Net PnL after all costs
        gross_pnl = total_gains + total_losses  # total_losses is already negative
        net_pnl = gross_pnl - total_fees - abs(total_funding)

        return {
            'total_gains': round(total_gains, 2),
            'total_losses': round(total_losses, 2),
            'gross_pnl': round(gross_pnl, 2),
            'net_pnl': round(net_pnl, 2),
            'total_fees': round(total_fees, 2),
            'total_funding': round(abs(total_funding), 2),
            'trade_count': len(trades),
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': round(win_rate, 2),
        }

    async def aggregate_monthly_summary(self, year: int, trades: List = None) -> List[Dict[str, Any]]:
        """
        Aggregate monthly summary statistics.

        Args:
            year: Calendar year
            trades: Optional list of trades (if None, will fetch)

        Returns:
            List of 12 monthly dictionaries (Jan-Dec), empty months have zeros
        """
        if trades is None:
            trades = await self.trade_db.get_trades_by_year(year)

        # Initialize all 12 months with zeros
        monthly_data = {}
        for month in range(1, 13):
            month_key = f"{year}-{month:02d}"
            monthly_data[month_key] = {
                'month': month_key,
                'pnl': 0.0,
                'fees': 0.0,
                'funding': 0.0,
                'trades': 0,
                'wins': 0,
                'losses': 0,
            }

        # Aggregate trade data by month
        for trade in trades:
            if trade.entry_time:
                month_key = trade.entry_time.strftime('%Y-%m')

                if month_key in monthly_data:
                    monthly_data[month_key]['pnl'] += trade.pnl or 0
                    monthly_data[month_key]['fees'] += trade.fees or 0
                    monthly_data[month_key]['funding'] += abs(trade.funding_paid or 0)
                    monthly_data[month_key]['trades'] += 1

                    if trade.pnl and trade.pnl > 0:
                        monthly_data[month_key]['wins'] += 1
                    else:
                        monthly_data[month_key]['losses'] += 1

        # Calculate win rates and net PnL
        result = []
        for month_key in sorted(monthly_data.keys()):
            month_stats = monthly_data[month_key]
            total_trades = month_stats['trades']
            win_rate = (month_stats['wins'] / total_trades * 100) if total_trades > 0 else 0.0
            net_pnl = month_stats['pnl'] - month_stats['fees'] - month_stats['funding']

            result.append({
                'month': month_key,
                'trades': total_trades,
                'wins': month_stats['wins'],
                'losses': month_stats['losses'],
                'win_rate': round(win_rate, 2),
                'pnl': round(month_stats['pnl'], 2),
                'fees': round(month_stats['fees'], 2),
                'funding': round(month_stats['funding'], 2),
                'net': round(net_pnl, 2),
            })

        return result

    async def get_funding_payments(self, year: int) -> List[Dict[str, Any]]:
        """
        Get all funding payments for a specific year.

        Args:
            year: Calendar year

        Returns:
            List of funding payment dictionaries
        """
        try:
            import aiosqlite
            async with aiosqlite.connect(self.funding_tracker.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT symbol, timestamp, funding_rate, position_value,
                           payment_amount, side
                    FROM funding_payments
                    WHERE strftime('%Y', timestamp) = ?
                    ORDER BY timestamp ASC
                """, (str(year),))
                rows = await cursor.fetchall()

                return [
                    {
                        'timestamp': row['timestamp'],
                        'symbol': row['symbol'],
                        'side': row['side'],
                        'funding_rate': row['funding_rate'],
                        'position_value': row['position_value'],
                        'payment_amount': row['payment_amount'],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting funding payments: {e}")
            return []

    def _trade_to_dict(self, trade) -> Dict[str, Any]:
        """Convert a Trade object to a dictionary."""
        duration_hours = 0.0
        if trade.entry_time and trade.exit_time:
            duration_seconds = (trade.exit_time - trade.entry_time).total_seconds()
            duration_hours = round(duration_seconds / 3600, 2)

        net_result = (trade.pnl or 0) - (trade.fees or 0) - abs(trade.funding_paid or 0)

        return {
            'id': trade.id,
            'symbol': trade.symbol,
            'side': trade.side,
            'entry_time': trade.entry_time.isoformat() if trade.entry_time else '',
            'exit_time': trade.exit_time.isoformat() if trade.exit_time else '',
            'entry_price': trade.entry_price,
            'exit_price': trade.exit_price,
            'size': trade.size,
            'pnl': round(trade.pnl, 2) if trade.pnl else 0.0,
            'fees': round(trade.fees, 2) if trade.fees else 0.0,
            'funding_paid': round(abs(trade.funding_paid or 0), 2),
            'net_result': round(net_result, 2),
            'duration_hours': duration_hours,
        }

    async def generate_csv_content(self, year: int, language: str = 'de') -> str:
        """
        Generate CSV content for tax report.

        Args:
            year: Calendar year
            language: Language code ('de' or 'en')

        Returns:
            CSV content as string with UTF-8 BOM encoding
        """
        # Get all data
        data = await self.get_year_data(year, language)

        # Create CSV in memory
        output = StringIO()

        # Add UTF-8 BOM for Excel compatibility
        output.write('\ufeff')

        writer = csv.writer(output, delimiter=',', quoting=csv.QUOTE_MINIMAL)

        # Write header section
        self._write_header_section(writer, data, language)

        # Write summary section
        self._write_summary_section(writer, data, language)

        # Write detailed trades section
        self._write_trades_section(writer, data, language)

        # Write monthly breakdown section
        self._write_monthly_section(writer, data, language)

        # Write funding payments section
        if data['funding_payments']:
            self._write_funding_section(writer, data, language)

        return output.getvalue()

    def _write_header_section(self, writer, data: Dict, language: str):
        """Write CSV header section."""
        def t(key): return translate(key, language)
        year = data['year']

        # Bilingual title
        writer.writerow([f"{TRANSLATIONS['de']['tax_report_title']} / {TRANSLATIONS['en']['tax_report_title']}"])
        writer.writerow([
            f"{t('reporting_period')} / Reporting Period",
            f"{year}-01-01 {t('to')}/to {year}-12-31"
        ])
        writer.writerow([
            f"{t('generated_on')} / Generated on",
            datetime.now().strftime('%Y-%m-%d')
        ])
        writer.writerow([])

        # Disclaimer (bilingual)
        writer.writerow([TRANSLATIONS['de']['disclaimer']])
        writer.writerow([TRANSLATIONS['en']['disclaimer']])
        writer.writerow([])

    def _write_summary_section(self, writer, data: Dict, language: str):
        """Write summary section."""
        def t(key): return translate(key, language)
        summary = data['summary']

        # Section header (bilingual)
        writer.writerow([f"{TRANSLATIONS['de']['summary']} / {TRANSLATIONS['en']['summary']}"])
        writer.writerow([
            f"{t('metric')} / Metric",
            f"{t('value')} / Value (€)"
        ])

        # Summary rows
        writer.writerow([f"{t('total_gains')} / Total Gains", summary.get('total_gains', 0)])
        writer.writerow([f"{t('total_losses')} / Total Losses", summary.get('total_losses', 0)])
        writer.writerow([f"{t('net_pnl')} / Net PnL", summary.get('net_pnl', 0)])
        writer.writerow([f"{t('total_fees')} / Total Fees", summary.get('total_fees', 0)])
        writer.writerow([f"{t('total_funding')} / Funding Costs", summary.get('total_funding', 0)])
        writer.writerow([f"{t('trade_count')} / Trade Count", summary.get('trade_count', 0)])
        writer.writerow([f"{t('win_rate')} / Win Rate", f"{summary.get('win_rate', 0)}%"])

        if summary.get('open_trades_count', 0) > 0:
            writer.writerow([
                f"{t('open_trades_note')} / Open trades not included",
                summary['open_trades_count']
            ])

        writer.writerow([])

    def _write_trades_section(self, writer, data: Dict, language: str):
        """Write detailed trades section."""
        def t(key): return translate(key, language)
        trades = data['trades']

        # Section header (bilingual)
        writer.writerow([f"{TRANSLATIONS['de']['detailed_trades']} / {TRANSLATIONS['en']['detailed_trades']}"])

        # Column headers (bilingual)
        writer.writerow([
            f"{t('date')} / Date",
            f"{t('symbol')} / Symbol",
            f"{t('side')} / Side",
            f"{t('entry_price')} / Entry",
            f"{t('exit_price')} / Exit",
            f"{t('size')} / Size",
            f"{t('pnl')} / PnL",
            f"{t('fees')} / Fees",
            f"{t('funding')} / Funding",
            f"{t('net_result')} / Net",
            f"{t('duration')} / Duration (h)",
        ])

        # Trade rows
        for trade in trades:
            writer.writerow([
                trade['entry_time'][:19] if trade['entry_time'] else '',  # Remove microseconds
                trade['symbol'],
                trade['side'].upper(),
                trade['entry_price'],
                trade['exit_price'] or '',
                trade['size'],
                trade['pnl'],
                trade['fees'],
                trade['funding_paid'],
                trade['net_result'],
                trade['duration_hours'],
            ])

        writer.writerow([])

    def _write_monthly_section(self, writer, data: Dict, language: str):
        """Write monthly breakdown section."""
        def t(key): return translate(key, language)
        monthly = data['monthly_breakdown']

        # Section header (bilingual)
        writer.writerow([f"{TRANSLATIONS['de']['monthly_breakdown']} / {TRANSLATIONS['en']['monthly_breakdown']}"])

        # Column headers (bilingual)
        writer.writerow([
            f"{t('month')} / Month",
            f"{t('trades')} / Trades",
            f"{t('wins')} / Wins",
            f"{t('win_rate_percent')} / Win Rate (%)",
            f"{t('total_pnl')} / PnL",
            f"{t('total_fees_monthly')} / Fees",
            f"{t('total_funding_monthly')} / Funding",
            f"{t('net')} / Net",
        ])

        # Monthly rows (only include months with trades for brevity)
        for month_data in monthly:
            if month_data['trades'] > 0:  # Only include months with trades
                writer.writerow([
                    month_data['month'],
                    month_data['trades'],
                    month_data['wins'],
                    month_data['win_rate'],
                    month_data['pnl'],
                    month_data['fees'],
                    month_data['funding'],
                    month_data['net'],
                ])

        writer.writerow([])

    def _write_funding_section(self, writer, data: Dict, language: str):
        """Write funding payments section."""
        def t(key): return translate(key, language)
        funding = data['funding_payments']

        # Section header (bilingual)
        writer.writerow([f"{TRANSLATIONS['de']['funding_payments']} / {TRANSLATIONS['en']['funding_payments']}"])

        # Column headers (bilingual)
        writer.writerow([
            f"{t('date')} / Date",
            f"{t('symbol')} / Symbol",
            f"{t('side')} / Side",
            f"{t('funding_rate')} / Rate (%)",
            f"{t('position_value')} / Position Value",
            f"{t('amount')} / Amount",
        ])

        # Funding rows
        for payment in funding:
            writer.writerow([
                payment['timestamp'][:19] if payment['timestamp'] else '',
                payment['symbol'],
                payment['side'].upper(),
                round(payment['funding_rate'] * 100, 4),  # Convert to percentage
                round(payment['position_value'], 2),
                round(payment['payment_amount'], 2),
            ])

        writer.writerow([])
