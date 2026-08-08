from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required
from database import get_db_connection
from datetime import datetime

portfolio_bp = Blueprint('portfolio', __name__)

@portfolio_bp.route('/strategy/<strategy_id>', methods=['GET'])
@jwt_required()
def get_strategy(strategy_id):
    """Fetch strategy data - only trendfollowing is supported"""
    try:
        current_app.logger.info(f'Fetching strategy: {strategy_id}')

        if strategy_id == 'trendfollowing':
            return get_live_trend_following_strategy()
        else:
            return jsonify({'error': 'Strategy not found'}), 404

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
            
            # 3. Get current positions (latest entry per symbol, sorted by notional)
            current_app.logger.info('[TREND] Fetching positions...')
            cursor.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (symbol)
                           symbol, quantity, average_price,
                           daily_unrealized_pnl, daily_realized_pnl
                    FROM trading.positions
                    WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
                    AND quantity != 0
                    ORDER BY symbol, updated_at DESC
                ) AS latest_positions
                ORDER BY ABS(quantity * average_price) DESC
            """)
            positions = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(positions)} positions')

            # 4. Get all executions (assume all are for this strategy)
            current_app.logger.info('[TREND] Fetching executions...')
            cursor.execute("""
                SELECT symbol, side, quantity, price,
                       execution_time, commissions_fees
                FROM trading.executions
                ORDER BY execution_time DESC
                LIMIT 100
            """)
            executions = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(executions)} executions')

            # 5. Get yesterday's positions for finalized positions comparison
            current_app.logger.info('[TREND] Fetching yesterday\'s positions...')
            cursor.execute("""
                SELECT DISTINCT ON (symbol)
                       symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl, updated_at
                FROM trading.positions
                WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
                AND updated_at::date = (CURRENT_DATE - INTERVAL '1 day')::date
                ORDER BY symbol, updated_at DESC
            """)
            yesterday_positions = cursor.fetchall()
            current_app.logger.info(f'[TREND] Found {len(yesterday_positions)} yesterday positions')

            # Calculate values
            current_app.logger.info('[TREND] Calculating values...')
            current_value = float(latest['current_portfolio_value'])

            # Starting capital is the FIRST point of the live-trading equity curve --
            # read it from the data, never hardcode it or snap it to a round number.
            # If the curve has no rows yet, reconstruct the baseline from the reported
            # cumulative return rather than assuming a fixed figure.
            if equity_curve:
                initial_equity = float(equity_curve[0]['equity'])
            else:
                cumulative_return = float(latest.get('total_cumulative_return') or 0)
                initial_equity = (
                    current_value / (1 + cumulative_return / 100)
                    if cumulative_return > -100 else current_value
                )

            current_app.logger.info(f'[TREND] Initial equity: {initial_equity}')

            total_return = current_value - initial_equity
            # Return percent from the actual start/end equity, not a stored field.
            return_percent = (total_return / initial_equity * 100) if initial_equity > 0 else 0

            current_app.logger.info(f'[TREND] Current value: {current_value}, Return: {return_percent}%')
            current_app.logger.info(f'[TREND] Total return (P&L): ${total_return}')

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

            # Calculate best/worst day and daily returns for win rate
            daily_returns = []
            daily_pnl = []  # Track actual P&L for win rate calculation
            for i in range(1, len(historical_data)):
                prev_val = historical_data[i-1]['value']
                curr_val = historical_data[i]['value']
                if prev_val > 0:
                    daily_return = ((curr_val - prev_val) / prev_val) * 100
                    daily_returns.append(daily_return)
                    daily_pnl.append(curr_val - prev_val)

            best_day = max(daily_returns) if daily_returns else 0
            worst_day = min(daily_returns) if daily_returns else 0

            # Calculate max drawdown from equity curve
            max_drawdown = 0
            peak = historical_data[0]['value'] if historical_data else 0
            for point in historical_data:
                if point['value'] > peak:
                    peak = point['value']
                drawdown = ((peak - point['value']) / peak) * 100 if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

            # Calculate win rate from daily returns (% of profitable days)
            winning_days = [pnl for pnl in daily_pnl if pnl > 0]
            losing_days = [pnl for pnl in daily_pnl if pnl < 0]
            total_days = len(daily_pnl)
            win_rate = (len(winning_days) / total_days * 100) if total_days > 0 else 0

            # Calculate average win and average loss
            avg_win = sum(winning_days) / len(winning_days) if winning_days else 0
            avg_loss = abs(sum(losing_days) / len(losing_days)) if losing_days else 0

            # Calculate profit factor (gross profit / gross loss)
            gross_profit = sum(winning_days) if winning_days else 0
            gross_loss = abs(sum(losing_days)) if losing_days else 0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0

            # Transform executions with dates
            transformed_executions = []
            for exec in executions:
                exec_time = exec['execution_time']
                transformed_executions.append({
                    'symbol': exec['symbol'],
                    'side': exec['side'],
                    'quantity': float(exec['quantity']),
                    'price': float(exec['price']),
                    'notional': float(exec['quantity']) * float(exec['price']),
                    'commission': float(exec['commissions_fees']),
                    'date': exec_time.isoformat() if exec_time else None
                })

            # Transform yesterday's positions into finalized positions
            # Compare with today's positions to show what changed
            current_app.logger.info('[TREND] Transforming finalized positions...')
            today_symbols = {pos['symbol'] for pos in positions}
            yesterday_symbols = {pos['symbol'] for pos in yesterday_positions}

            transformed_finalized = []
            for ypos in yesterday_positions:
                symbol = ypos['symbol']
                yesterday_qty = float(ypos['quantity'])
                yesterday_price = float(ypos['average_price'])

                # Find today's position for this symbol (if exists)
                today_pos = next((p for p in positions if p['symbol'] == symbol), None)
                today_qty = float(today_pos['quantity']) if today_pos else 0
                today_price = float(today_pos['average_price']) if today_pos else yesterday_price

                # Calculate realized P&L from position change
                qty_change = today_qty - yesterday_qty
                if qty_change != 0:  # Position changed
                    realized_pnl = float(ypos['daily_realized_pnl']) if ypos['daily_realized_pnl'] else 0
                    transformed_finalized.append({
                        'symbol': symbol.replace('.v.0', ''),
                        'quantity': yesterday_qty,
                        'entryPrice': yesterday_price,
                        'exitPrice': today_price,
                        'realizedPnL': realized_pnl
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
                'finalizedPositions': transformed_finalized,
                'managers': ['AlgoLens System'],
                'lastUpdate': latest['date'].isoformat(),
                'metrics': {
                    'volatility': volatility,
                    'sharpeRatio': sharpe,
                    'maxDrawdown': max_drawdown,
                    'winRate': win_rate,
                    'totalTrades': len(transformed_executions),
                    'avgWin': avg_win,
                    'avgLoss': avg_loss,
                    'profitFactor': profit_factor,
                    'dailyReturn': float(latest['daily_return']) if latest['daily_return'] else 0,
                    'cumulativeReturn': return_percent,
                    'annualizedReturn': ann_return,
                    'grossLeverage': float(latest['gross_leverage']) if latest['gross_leverage'] is not None else 0,
                    'netLeverage': float(latest['net_leverage']) if latest['net_leverage'] is not None else 0,
                    'portfolioLeverage': float(latest['portfolio_leverage']) if latest['portfolio_leverage'] is not None else 0,
                    'marginPosted': float(latest['margin_posted']) if latest['margin_posted'] is not None else 0,
                    'equityToMarginRatio': float(latest['equity_to_margin_ratio']) if latest['equity_to_margin_ratio'] is not None else 0,
                    'marginCushion': float(latest['margin_cushion']) if latest['margin_cushion'] is not None else 0,
                    'totalNotional': float(latest['gross_notional']) if latest['gross_notional'] is not None else 0,
                    'unrealizedPnL': float(latest['total_unrealized_pnl']) if latest['total_unrealized_pnl'] is not None else 0,
                    'realizedPnL': float(latest['total_realized_pnl']) if latest['total_realized_pnl'] is not None else 0,
                    'totalCommissions': float(latest['total_transaction_costs']) if latest['total_transaction_costs'] is not None else 0,
                    'netPnL': total_return,
                    'cashAvailable': float(latest['cash_available']) if latest['cash_available'] is not None else 0,
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


@portfolio_bp.route('/strategies', methods=['GET'])
@jwt_required()
def get_all_strategies():
    """Get summary of all strategies"""
    current_app.logger.info('[STRATEGIES] === /strategies endpoint called ===')

    try:
        strategies = []

        # Add real trendfollowing strategy
        current_app.logger.info('[STRATEGIES] Attempting database connection...')
        conn = get_db_connection()
        current_app.logger.info('[STRATEGIES] Database connection successful')

        try:
            with conn.cursor() as cursor:
                current_app.logger.info('[STRATEGIES] Executing query for LIVE_TREND_FOLLOWING...')
                cursor.execute("""
                    SELECT current_portfolio_value, total_annualized_return,
                           volatility, total_cumulative_return
                    FROM trading.live_results
                    WHERE config::jsonb->>'strategy_type' = 'LIVE_TREND_FOLLOWING'
                    ORDER BY date DESC
                    LIMIT 1
                """)
                latest = cursor.fetchone()
                current_app.logger.info(f'[STRATEGIES] Query result: {latest is not None}')

                if latest:
                    current_value = float(latest['current_portfolio_value'])

                    # Starting capital = the FIRST point of the live-trading equity
                    # curve (read from data, not hardcoded). Fall back to the stored
                    # cumulative return only if the curve has no rows yet.
                    cursor.execute("""
                        SELECT equity
                        FROM trading.equity_curve
                        WHERE strategy_id = 'LIVE_TREND_FOLLOWING'
                        ORDER BY timestamp ASC
                        LIMIT 1
                    """)
                    first_point = cursor.fetchone()
                    if first_point:
                        initial_equity = float(first_point['equity'])
                        actual_return_percent = (
                            (current_value - initial_equity) / initial_equity * 100
                            if initial_equity > 0 else 0
                        )
                    else:
                        actual_return_percent = float(latest.get('total_cumulative_return') or 0)

                    current_app.logger.info(f'[STRATEGIES] Found live_results data: portfolio_value={current_value}, calculated_return={actual_return_percent}%')
                    sharpe = (float(latest['total_annualized_return']) / float(latest['volatility'])) if float(latest['volatility']) > 0 else 0
                    strategies.append({
                        'id': 'trendfollowing',
                        'name': 'Trend Following',
                        'currentValue': current_value,
                        'returnPercent': actual_return_percent,  # Use calculated value
                        'volatility': float(latest['volatility']),
                        'sharpeRatio': sharpe,
                        'annualizedReturn': float(latest['total_annualized_return'])
                    })
                    current_app.logger.info(f'[STRATEGIES] Strategy added: trendfollowing')
                else:
                    current_app.logger.warning('[STRATEGIES] No live_results data found for LIVE_TREND_FOLLOWING')
        finally:
            conn.close()
            current_app.logger.info('[STRATEGIES] Database connection closed')

        current_app.logger.info(f'[STRATEGIES] Returning {len(strategies)} strategies')
        return jsonify({'strategies': strategies}), 200

    except Exception as e:
        current_app.logger.error(f'[STRATEGIES] Error fetching strategies: {str(e)}', exc_info=True)
        return jsonify({'error': f'Failed to fetch strategies: {str(e)}'}), 500
