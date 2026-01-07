from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required
from database import get_db_connection
from datetime import datetime

portfolio_bp = Blueprint('portfolio', __name__)

@portfolio_bp.route('/strategy/<strategy_id>', methods=['GET'])
@jwt_required()
def get_strategy(strategy_id):
    """Fetch strategy data - real DB data for trendfollowing, mock for others"""
    try:
        current_app.logger.info(f'Fetching strategy: {strategy_id}')

        if strategy_id == 'trendfollowing':
            return get_live_trend_following_strategy()
        else:
            return get_mock_strategy(strategy_id)

    except Exception as e:
        current_app.logger.error(f'Error fetching strategy {strategy_id}: {str(e)}', exc_info=True)
        return jsonify({'error': 'Failed to fetch strategy'}), 500


def get_live_trend_following_strategy():
    """Fetch real data for LIVE_TREND_FOLLOWING from database"""
    from flask import current_app
    current_app.logger.info('[TREND] Starting to fetch LIVE_TREND_FOLLOWING data')

    conn = get_db_connection()
    current_app.logger.info('[TREND] Database connection established')

    try:
        with conn.cursor() as cursor:
            # 1. Get latest live results for metrics
            current_app.logger.info('[TREND] Fetching latest live_results...')
            cursor.execute("""
                SELECT * FROM trading.live_results
                WHERE config::jsonb->>'strategy_type' = 'LIVE_TREND_FOLLOWING'
                ORDER BY date DESC
                LIMIT 1
            """)
            latest = cursor.fetchone()
            current_app.logger.info(f'[TREND] Latest results: {latest is not None}')

            if not latest:
                current_app.logger.error('[TREND] No live_results found!')
                return jsonify({'error': 'No data found for strategy'}), 404

            # 2. Get equity curve for historical data
            current_app.logger.info('[TREND] Fetching equity_curve...')
            cursor.execute("""
                SELECT timestamp, equity
                FROM trading.equity_curve
                WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
                ORDER BY timestamp ASC
            """)
            equity_curve = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(equity_curve)} equity curve points')
            
            # 3. Get current positions
            current_app.logger.info('[TREND] Fetching positions...')
            cursor.execute("""
                SELECT symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl
                FROM trading.positions
                WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
                AND quantity != 0
                ORDER BY ABS(quantity * average_price) DESC
            """)
            positions = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(positions)} positions')

            # 4. Get all executions (assume all are for this strategy)
            current_app.logger.info('[TREND] Fetching executions...')
            cursor.execute("""
                SELECT symbol, side, quantity, price,
                       execution_time, commission
                FROM trading.executions
                ORDER BY execution_time DESC
                LIMIT 100
            """)
            executions = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(executions)} executions')

            # Calculate values
            current_app.logger.info('[TREND] Calculating values...')
            initial_equity = float(equity_curve[0]['equity']) if equity_curve else 500000
            # Round to 500k if very close
            if abs(initial_equity - 500000) < 5000:
                initial_equity = 500000

            current_app.logger.info(f'[TREND] Initial equity: {initial_equity}')

            current_value = float(latest['current_portfolio_value'])
            total_return = current_value - initial_equity
            return_percent = float(latest['total_cumulative_return']) * 100

            current_app.logger.info(f'[TREND] Current value: {current_value}, Return: {return_percent}%')

            # Transform positions
            current_app.logger.info('[TREND] Transforming positions...')
            transformed_positions = []
            for pos in positions:
                notional = abs(float(pos['quantity']) * float(pos['average_price']))
                transformed_positions.append({
                    'symbol': pos['symbol'],
                    'name': pos['symbol'].replace('.v.0', ''),
                    'shares': float(pos['quantity']),
                    'quantity': float(pos['quantity']),
                    'costBasis': float(pos['average_price']),
                    'currentValue': notional,
                    'marketPrice': float(pos['average_price']),
                    'notional': notional,
                    'percentOfTotal': (notional / current_value * 100) if current_value > 0 else 0
                })

            # Transform equity curve to historical data
            historical_data = []
            for point in equity_curve:
                historical_data.append({
                    'date': point['timestamp'].isoformat(),
                    'value': float(point['equity'])
                })

            # Calculate best/worst day
            daily_returns = []
            for i in range(1, len(historical_data)):
                prev_val = historical_data[i-1]['value']
                curr_val = historical_data[i]['value']
                if prev_val > 0:
                    daily_return = ((curr_val - prev_val) / prev_val) * 100
                    daily_returns.append(daily_return)

            best_day = max(daily_returns) if daily_returns else 0
            worst_day = min(daily_returns) if daily_returns else 0

            # Transform executions
            transformed_executions = []
            for exec in executions:
                transformed_executions.append({
                    'symbol': exec['symbol'],
                    'side': exec['side'],
                    'quantity': float(exec['quantity']),
                    'price': float(exec['price']),
                    'notional': float(exec['quantity']) * float(exec['price']),
                    'commission': float(exec['commission'])
                })

            # Calculate Sharpe ratio
            ann_return = float(latest['total_annualized_return'])
            volatility = float(latest['volatility'])
            sharpe = (ann_return / volatility) if volatility > 0 else 0

            current_app.logger.info('[TREND] Building strategy response...')

            # Build strategy response
            strategy = {
                'id': 'trendfollowing',
                'name': 'Trend Following',
                'description': 'Systematic trend following across multiple futures contracts',
                'invested': initial_equity,
                'currentValue': current_value,
                'return': total_return,
                'returnPercent': return_percent,
                'positions': transformed_positions,
                'historicalData': historical_data,
                'bestDay': best_day,
                'worstDay': worst_day,
                'executions': transformed_executions,
                'finalizedPositions': [],
                'managers': ['AlgoLens System'],
                'lastUpdate': latest['date'].isoformat(),
                'metrics': {
                    'volatility': volatility,
                    'sharpeRatio': sharpe,
                    'maxDrawdown': 0,
                    'winRate': 0,
                    'totalTrades': len(transformed_executions),
                    'avgWin': 0,
                    'avgLoss': 0,
                    'profitFactor': 0,
                    'dailyReturn': float(latest['daily_return']) if latest['daily_return'] else 0,
                    'cumulativeReturn': return_percent,
                    'annualizedReturn': ann_return,
                    'grossLeverage': float(latest['gross_leverage']),
                    'netLeverage': float(latest['net_leverage']),
                    'portfolioLeverage': float(latest['portfolio_leverage']),
                    'marginPosted': float(latest['margin_posted']),
                    'equityToMarginRatio': float(latest['equity_to_margin_ratio']),
                    'marginCushion': float(latest['margin_cushion']),
                    'totalNotional': float(latest['gross_notional']),
                    'unrealizedPnL': float(latest['total_unrealized_pnl']),
                    'realizedPnL': float(latest['total_realized_pnl']),
                    'totalCommissions': float(latest['total_commissions']),
                    'netPnL': float(latest['total_pnl']) - float(latest['total_commissions']),
                    'cashAvailable': float(latest['cash_available']),
                    'currentPortfolioValue': current_value
                }
            }

            current_app.logger.info('[TREND] Strategy response built successfully')
            return jsonify(strategy), 200

    except Exception as e:
        current_app.logger.error(f'[TREND] Error in get_live_trend_following_strategy: {str(e)}', exc_info=True)
        raise
    finally:
        conn.close()
        current_app.logger.info('[TREND] Database connection closed')


def get_mock_strategy(strategy_id):
    """Return mock data for non-database strategies"""
    mock_strategies = {
        'dividend': {
            'id': 'dividend',
            'name': 'Dividend Strategy',
            'description': 'Stable dividend-paying blue chip stocks',
            'invested': 35000,
            'currentValue': 41234.87,
            'returnPercent': 17.81
        },
        'value': {
            'id': 'value',
            'name': 'Value Strategy',
            'description': 'Undervalued companies with strong fundamentals',
            'invested': 25000,
            'currentValue': 32380.00,
            'returnPercent': 29.52
        },
        'growth': {
            'id': 'growth',
            'name': 'Growth Strategy',
            'description': 'High-growth tech and innovative companies',
            'invested': 40000,
            'currentValue': 54230.45,
            'returnPercent': 35.58
        }
    }

    if strategy_id not in mock_strategies:
        return jsonify({'error': 'Strategy not found'}), 404

    mock = mock_strategies[strategy_id]

    # Generate mock historical data
    from datetime import timedelta
    historical_data = []
    today = datetime.now()
    for i in range(90, -1, -1):
        date = today - timedelta(days=i)
        progress = (90 - i) / 90
        value = mock['invested'] + (mock['currentValue'] - mock['invested']) * progress
        historical_data.append({
            'date': date.isoformat(),
            'value': round(value, 2)
        })

    return jsonify({
        **mock,
        'return': mock['currentValue'] - mock['invested'],
        'positions': [],
        'historicalData': historical_data,
        'bestDay': 2.5,
        'worstDay': -1.8,
        'executions': [],
        'finalizedPositions': [],
        'managers': ['Mock Manager'],
        'lastUpdate': datetime.now().isoformat(),
        'metrics': {
            'volatility': 12.0,
            'sharpeRatio': 1.5,
            'maxDrawdown': -10.0,
            'winRate': 65.0,
            'totalTrades': 0,
            'avgWin': 0,
            'avgLoss': 0,
            'profitFactor': 2.0,
            'dailyReturn': 0.5,
            'cumulativeReturn': mock['returnPercent'],
            'annualizedReturn': mock['returnPercent'] * 1.2,
            'grossLeverage': 1.0,
            'netLeverage': 1.0,
            'portfolioLeverage': 1.0,
            'marginPosted': mock['currentValue'] * 0.2,
            'equityToMarginRatio': 5.0,
            'marginCushion': 80.0,
            'totalNotional': mock['currentValue'],
            'unrealizedPnL': 0,
            'realizedPnL': mock['currentValue'] - mock['invested'],
            'totalCommissions': 500.0,
            'netPnL': mock['currentValue'] - mock['invested'] - 500,
            'cashAvailable': mock['currentValue'] * 0.1,
            'currentPortfolioValue': mock['currentValue']
        }
    }), 200


@portfolio_bp.route('/strategies', methods=['GET'])
@jwt_required()
def get_all_strategies():
    """Get summary of all strategies"""
    try:
        strategies = []

        # Add real trendfollowing strategy
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT current_portfolio_value, total_annualized_return,
                           volatility, total_cumulative_return
                    FROM trading.live_results
                    WHERE config::jsonb->>'strategy_type' = 'LIVE_TREND_FOLLOWING'
                    ORDER BY date DESC
                    LIMIT 1
                """)
                latest = cursor.fetchone()

                if latest:
                    sharpe = (float(latest['total_annualized_return']) / float(latest['volatility'])) if float(latest['volatility']) > 0 else 0
                    strategies.append({
                        'id': 'trendfollowing',
                        'name': 'Trend Following',
                        'currentValue': float(latest['current_portfolio_value']),
                        'returnPercent': float(latest['total_cumulative_return']) * 100,
                        'volatility': float(latest['volatility']),
                        'sharpeRatio': sharpe,
                        'annualizedReturn': float(latest['total_annualized_return'])
                    })
        finally:
            conn.close()

        # Add mock strategies
        strategies.extend([
            {
                'id': 'dividend',
                'name': 'Dividend Strategy',
                'currentValue': 41234.87,
                'returnPercent': 17.81,
                'volatility': 8.45,
                'sharpeRatio': 2.15,
                'annualizedReturn': 21.45
            },
            {
                'id': 'value',
                'name': 'Value Strategy',
                'currentValue': 32380.00,
                'returnPercent': 29.52,
                'volatility': 12.34,
                'sharpeRatio': 2.05,
                'annualizedReturn': 35.80
            },
            {
                'id': 'growth',
                'name': 'Growth Strategy',
                'currentValue': 54230.45,
                'returnPercent': 35.58,
                'volatility': 17.97,
                'sharpeRatio': 1.85,
                'annualizedReturn': 42.15
            }
        ])

        return jsonify({'strategies': strategies}), 200

    except Exception as e:
        current_app.logger.error(f'Error fetching strategies: {str(e)}', exc_info=True)
        return jsonify({'error': 'Failed to fetch strategies'}), 500
