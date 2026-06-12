"""Offline backtest harness for the option-income strategies.

The live system has no historical option-chain data source (yfinance/IBKR paper do not expose
historical chains), so this harness *synthesises* option premiums with Black-Scholes from the
underlying's historical price path and its trailing realised volatility. It is a deterministic
approximation for sizing expectations and comparing parameter choices — NOT a tick-accurate
replay, and it is completely separate from the live broker/risk path (it imports nothing from
`engine/` or `execution/` and is never imported by them).

See `engine.simulate` for the model and its stated assumptions.
"""
