"""Built-in list of large NSE companies with a sector tag. Used for peers and for the backtest."""

UNIVERSE = {
    "IT services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "Banks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Non-bank lenders": ["BAJFINANCE", "BAJAJFINSV", "SHRIRAMFIN"],
    "Automobiles": ["MARUTI", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR"],
    "Consumer staples": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
    "Oil and gas": ["RELIANCE", "ONGC", "BPCL", "IOC"],
    "Power": ["NTPC", "POWERGRID", "TATAPOWER"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "Cement and infrastructure": ["ULTRACEMCO", "GRASIM", "LT", "ADANIPORTS"],
    "Consumer discretionary": ["TITAN", "ASIANPAINT"],
    "Telecom": ["BHARTIARTL"],
}

SECTOR_OF = {sym: sector for sector, syms in UNIVERSE.items() for sym in syms}
ALL_SYMBOLS = sorted(SECTOR_OF)
LENDER_SECTORS = {"Banks", "Non-bank lenders"}


def peers_of(symbol: str, limit: int = 5) -> tuple[str | None, list[str]]:
    sector = SECTOR_OF.get(symbol)
    if not sector:
        return None, []
    return sector, [s for s in UNIVERSE[sector] if s != symbol][:limit]
