from system.trading_system import TradingSystem
from system.strategies.strategy1 import Strategy1
from system.strategies.strategy2 import Strategy2
from system.data import get_data, add_tickers_and_data
from system.init_db import init_db
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Selection of strategies
@app.route('/api/strategies', methods=['GET'])
def get_strategies():
    strategies = ["Mean Reversion", "Momentum", "Arbitrage", "Pairs Trading", "Trend Following"]
    return jsonify(strategies)

# Endpoint to handle submitted strategies
@app.route('/api/submit-strategies', methods=['POST'])
def submit_strategies():
    response = request.json
    print("Received data:", response)

    # Fetch the data
    print("Fetching data")
    data: pd.DataFrame = get_data(start_date="2024-1-1", fetch=False)
    print("Data fetched")

    # Calculate total capital and initialize variables
    total_capital = sum(element["capital"] for element in response)
    strategies = []

    # Prepare strategies
    for element in response:
        risk_target = element["volatility"]
        capital = element["capital"]
        if element["strategy"] == "Mean Reversion":
            strategy = Strategy2(data=data, risk_target=risk_target, capital=capital, num_stocks=5)
        elif element["strategy"] == "Momentum":
            strategy = Strategy1(data=data, risk_target=risk_target, capital=capital, num_stocks=5)
        strategies.append((capital / total_capital, strategy))

    # Initialize the trading system with the strategies
    trading_system = TradingSystem(strategies=strategies)

    # Run the backtest and get the results
    backtest_results = trading_system.backtest()  # Returns a dictionary

    # Calculate aggregated final positions
    final_positions = {}
    for strategy_name, strategy_data in backtest_results["strategies"].items():
        for asset in strategy_data["last_position"]["Summary"]["Assets"]:
            ticker = asset["ticker"]
            final_positions[ticker] = final_positions.get(ticker, 0) + asset["Ideal_Positions"]

    print("Backtest completed successfully.")

    return jsonify({
        "message": "Data received successfully!",
        "positions": {
            "strategyPositions": [
                {
                    "strategy": strategy_name,
                    "positions": strategy_data["last_position"]["Summary"]["Assets"],
                }
                for strategy_name, strategy_data in backtest_results["strategies"].items()
            ],
            "portfolioPositions": final_positions,  # Aggregated final positions
        },
        "metrics": backtest_results["metrics"],  # Portfolio-level metrics
    }), 200

if __name__ == '__main__':
    app.run(port=5000)
