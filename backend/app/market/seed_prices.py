"""Static seed data for the simulator: starting prices, GBM params, sectors."""

SEED_PRICES: dict[str, float] = {
    "AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "AMZN": 185.0, "TSLA": 250.0,
    "NVDA": 120.0, "META": 500.0, "JPM": 200.0, "V": 280.0, "NFLX": 650.0,
}

# (mu, sigma) - annualized drift and volatility
TICKER_PARAMS: dict[str, tuple[float, float]] = {
    "AAPL": (0.08, 0.25), "GOOGL": (0.08, 0.28), "MSFT": (0.08, 0.24),
    "AMZN": (0.10, 0.30), "TSLA": (0.10, 0.55), "NVDA": (0.15, 0.50),
    "META": (0.10, 0.35), "JPM": (0.06, 0.20), "V": (0.06, 0.18),
    "NFLX": (0.10, 0.38),
}
DEFAULT_PARAMS: tuple[float, float] = (0.06, 0.30)

SECTORS: dict[str, str] = {
    "AAPL": "tech", "GOOGL": "tech", "MSFT": "tech", "AMZN": "tech", "NVDA": "tech",
    "META": "tech", "NFLX": "tech", "TSLA": "auto", "JPM": "finance", "V": "finance",
}
DEFAULT_SECTOR = "other"

# Pairwise correlation of GBM shocks
INTRA_SECTOR_CORR: dict[str, float] = {"tech": 0.60, "finance": 0.50}
DEFAULT_INTRA_SECTOR_CORR = 0.40
CROSS_SECTOR_CORR = 0.25
IDIOSYNCRATIC: dict[str, float] = {"TSLA": 0.20}  # caps correlation with anything
