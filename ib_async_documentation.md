# The following contents were taken from https://ib-api-reloaded.github.io/ib_async/# for reference
Introduction
ib_async is a Python library that provides a clean, modern interface to Interactive Brokers’ Trader Workstation (TWS) and IB Gateway. It handles the complexities of the IBKR API so you can focus on building trading applications, research tools, and market data analysis.

What You Can Build
Market Data Applications: Stream live quotes, historical data, and market depth
Trading Systems: Place, modify, and monitor orders programmatically
Portfolio Tools: Track positions, account balances, and P&L in real-time
Research Platforms: Analyze contract details, option chains, and fundamental data
Risk Management: Monitor exposures and implement automated controls

Key Features
Simple and Intuitive: Write straightforward Python code without dealing with callback complexity
Automatic Synchronization: The IB component stays in sync with TWS/Gateway automatically
Async-Ready: Built on asyncio and eventkit for high-performance applications
Jupyter-Friendly: Interactive development with live data in notebooks
Production-Ready: Robust error handling, reconnection logic, and comprehensive logging
Be sure to take a look at the notebooks, the recipes and the API docs.

Installation
pip install ib_async
Requirements:
Python 3.10 or higher

We plan to support Python releases 2 years back which allows us to continue adding newer features and performance improvements over time.

A running IB Gateway application (or TWS with API mode enabled)
stable gateway — updated every few months
latest gateway — updated weekly
Make sure the API port is enabled and ‘Download open orders on connection’ is checked.
You may also want to increase the Java memory usage under Configure->Settings->Memory Allocation to 4096 MB minimum to prevent gateway crashes when loading bulk data.

The ibapi package from IB is not needed. ib_async implements the full IBKR API binary protocol internally.

Build Manually
First, install poetry:
pip install poetry -U

Installing Only Library
poetry install

Install Everything (enable docs + dev testing)
poetry install --with=docs,dev

Generate Docs
poetry install --with=docs
poetry run sphinx-build -b html docs html

Check Types
poetry run mypy ib_async

Build Package
poetry build

Upload Package (if maintaining)
poetry install
poetry config pypi-token.pypi your-api-token
poetry publish --build

Setup Interactive Brokers
1. Download IB Gateway or TWS
IB Gateway (Stable) — Updated every few months, more stable
IB Gateway (Latest) — Updated weekly, newest features
Trader Workstation (TWS) — Full trading platform

2. Configure API Access
Enable API: Go to Configure → API → Settings and check “Enable ActiveX and Socket Clients”
Set Port: Default ports are 7497 (TWS) and 4001 (Gateway). You can change these if needed.
Allow Connections: Add 127.0.0.1 to “Trusted IPs” if connecting locally
Download Orders: Check “Download open orders on connection” to see existing orders

3. Performance Settings
Memory: Go to Configure → Settings → Memory Allocation and set to 4096 MB minimum to prevent crashes with bulk data
Timeouts: Increase API timeout settings if you experience disconnections during large data requests

4. Common Connection Issues
Connection Refused

# Make sure TWS/Gateway is running and API is enabled
# Check that ports match (7497 for TWS, 4001 for Gateway)
ib.connect('127.0.0.1', 7497, clientId=1)  # TWS
ib.connect('127.0.0.1', 4001, clientId=1)  # Gateway
Client ID Conflicts

# Each connection needs a unique client ID
ib.connect('127.0.0.1', 7497, clientId=1)  # Use different numbers for multiple connections
Market Data Issues

# For free delayed data (no subscription required)
ib.reqMarketDataType(3)  # Delayed
ib.reqMarketDataType(4)  # Delayed frozen

# For real-time data (requires subscription)
ib.reqMarketDataType(1)  # Real-time
Connection Patterns
Basic Script Usage
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
# Your code here
ib.disconnect()
Jupyter Notebook Usage
from ib_async import *
util.startLoop()  # Required for notebooks

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
# Your code here - no need to call ib.run()
Async Application
import asyncio
from ib_async import *

async def main():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 7497, clientId=1)
    # Your async code here
    ib.disconnect()

asyncio.run(main())
Quick Start
Basic Connection
from ib_async import *

# Connect to TWS or IB Gateway
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
print("Connected")

# Disconnect when done
ib.disconnect()
Get Account Information
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Get account summary
account = ib.managedAccounts()[0]
summary = ib.accountSummary(account)
for item in summary:
    print(f"{item.tag}: {item.value}")

ib.disconnect()
Historical Data
from ib_async import *
# util.startLoop()  # uncomment this line when in a notebook

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Request historical data
contract = Forex('EURUSD')
bars = ib.reqHistoricalData(
    contract, endDateTime='', durationStr='30 D',
    barSizeSetting='1 hour', whatToShow='MIDPOINT', useRTH=True)

# Convert to pandas dataframe (pandas needs to be installed):
df = util.df(bars)
print(df.head())

ib.disconnect()
Live Market Data
from ib_async import *
import time

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Subscribe to live market data
contract = Stock('AAPL', 'SMART', 'USD')
ticker = ib.reqMktData(contract, '', False, False)

# Print live quotes for 30 seconds
for i in range(30):
    ib.sleep(1)  # Wait 1 second
    if ticker.last:
        print(f"AAPL: ${ticker.last} (bid: ${ticker.bid}, ask: ${ticker.ask})")

ib.disconnect()
Place a Simple Order
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Create a contract and order
contract = Stock('AAPL', 'SMART', 'USD')
order = MarketOrder('BUY', 100)

# Place the order
trade = ib.placeOrder(contract, order)
print(f"Order placed: {trade}")

# Monitor order status
while not trade.isDone():
    ib.sleep(1)
    print(f"Order status: {trade.orderStatus.status}")

ib.disconnect()
More Complete Examples
Portfolio Monitoring
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Get current positions
positions = ib.positions()
print("Current Positions:")
for pos in positions:
    print(f"{pos.contract.symbol}: {pos.position} @ {pos.avgCost}")

# Get open orders
orders = ib.openTrades()
print(f"\nOpen Orders: {len(orders)}")
for trade in orders:
    print(f"{trade.contract.symbol}: {trade.order.action} {trade.order.totalQuantity}")

ib.disconnect()
Real-time P&L Tracking
from ib_async import *

def onPnL(pnl):
    print(f"P&L Update: Unrealized: ${pnl.unrealizedPnL:.2f}, Realized: ${pnl.realizedPnL:.2f}")

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Subscribe to P&L updates
account = ib.managedAccounts()[0]
pnl = ib.reqPnL(account)
pnl.updateEvent += onPnL

# Keep running to receive updates
try:
    ib.run()  # Run until interrupted
except KeyboardInterrupt:
    ib.disconnect()
Advanced Order Management
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Create a bracket order (entry + stop loss + take profit)
contract = Stock('TSLA', 'SMART', 'USD')

# Parent order
parent = LimitOrder('BUY', 100, 250.00)
parent.orderId = ib.client.getReqId()
parent.transmit = False

# Stop loss
stopLoss = StopOrder('SELL', 100, 240.00)
stopLoss.orderId = ib.client.getReqId()
stopLoss.parentId = parent.orderId
stopLoss.transmit = False

# Take profit
takeProfit = LimitOrder('SELL', 100, 260.00)
takeProfit.orderId = ib.client.getReqId()
takeProfit.parentId = parent.orderId
takeProfit.transmit = True

# Place bracket order
trades = []
trades.append(ib.placeOrder(contract, parent))
trades.append(ib.placeOrder(contract, stopLoss))
trades.append(ib.placeOrder(contract, takeProfit))

print(f"Bracket order placed: {len(trades)} orders")
ib.disconnect()
Historical Data Analysis
from ib_async import *
import pandas as pd

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Get multiple timeframes
contract = Stock('SPY', 'SMART', 'USD')

# Daily bars for 1 year
daily_bars = ib.reqHistoricalData(
    contract, endDateTime='', durationStr='1 Y',
    barSizeSetting='1 day', whatToShow='TRADES', useRTH=True)

# 5-minute bars for last 5 days
intraday_bars = ib.reqHistoricalData(
    contract, endDateTime='', durationStr='5 D',
    barSizeSetting='5 mins', whatToShow='TRADES', useRTH=True)

# Convert to DataFrames
daily_df = util.df(daily_bars)
intraday_df = util.df(intraday_bars)

print(f"Daily bars: {len(daily_df)} rows")
print(f"Intraday bars: {len(intraday_df)} rows")

# Calculate simple moving average
daily_df['SMA_20'] = daily_df['close'].rolling(20).mean()
print(daily_df[['date', 'close', 'SMA_20']].tail())

ib.disconnect()
Library Structure
Core Components
ib_async.ib.IB - Main interface class

Connection management (connect(), disconnect(), connectAsync())

Market data requests (reqMktData(), reqHistoricalData())

Order management (placeOrder(), cancelOrder())

Account data (positions(), accountSummary(), reqPnL())

ib_async.contract - Financial instruments

Stock, Option, Future, Forex, Index, Bond

Contract - Base class for all instruments

ComboLeg, DeltaNeutralContract - Complex instruments

ib_async.order - Order types and management

MarketOrder, LimitOrder, StopOrder, StopLimitOrder

Order - Base order class with all parameters

OrderStatus, OrderState - Order execution tracking

Trade - Complete order lifecycle tracking

ib_async.ticker - Real-time market data

Ticker - Live quotes, trades, and market data

Automatic field updates (bid, ask, last, volume, etc.)

Event-driven updates via updateEvent

ib_async.objects - Data structures

BarData - Historical price bars

Position - Portfolio positions

PortfolioItem - Portfolio details with P&L

AccountValue - Account metrics

Key Patterns
Synchronous vs Asynchronous

# Synchronous (blocks until complete)
bars = ib.reqHistoricalData(contract, ...)

# Asynchronous (yields to event loop)
bars = await ib.reqHistoricalDataAsync(contract, ...)
Event Handling

# Subscribe to events
def onOrderUpdate(trade):
    print(f"Order update: {trade.orderStatus.status}")

ib.orderStatusEvent += onOrderUpdate

# Or with async
async def onTicker(ticker):
    print(f"Price update: {ticker.last}")

ticker.updateEvent += onTicker
Error Handling

try:
    ib.connect('127.0.0.1', 7497, clientId=1)
except ConnectionRefusedError:
    print("TWS/Gateway not running or API not enabled")
except Exception as e:
    print(f"Connection error: {e}")
Documentation
The complete API documentation.

Changelog.

Development
Running Tests
poetry install --with=dev
poetry run pytest
Type Checking
poetry run mypy ib_async
Code Formatting
poetry run ruff format
poetry run ruff check --fix
Local Development
Clone the repository:

git clone https://github.com/ib-api-reloaded/ib_async.git
cd ib_async
Install dependencies:

poetry install --with=dev,docs
Make your changes and run tests:

poetry run pytest
poetry run mypy ib_async
Submit a pull request with:

Clear description of changes

Tests for new functionality

Updated documentation if needed

Contributing Guidelines
Follow existing code style (enforced by ruff)

Add tests for new features

Update documentation for user-facing changes

Keep commits focused and well-described

Be responsive to code review feedback

Community Resources
If you have other public work related to ib_async or ib_insync open an issue and we can keep an active list here.

Projects below are not endorsed by any entity and are purely for reference or entertainment purposes.

Adi’s livestream VODs about using IBKR APIs: Interactive Brokers API in Python

Matt’s IBKR python CLI: icli

Corporate data parsing via IBKR API: ib_fundamental

Disclaimer
The software is provided on the conditions of the simplified BSD license.

This project is not affiliated with Interactive Brokers Group, Inc.

Official Interactive Brokers API Docs