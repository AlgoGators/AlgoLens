import React from "react";

interface Asset {
    ticker: string;
    Ideal_Positions: number;
    Realized_Capital: number;
}

interface Summary {
    Assets: Asset[];
    Realized_Capital: number;
    Ideal_Capital: number;
}

interface LastPosition {
    date: string;
    Summary: Summary;
}

interface StrategyData {
    proportion?: number;
    last_position: LastPosition;
  }

  interface PositionsSummaryProps {
    positions: {
        strategyPositions: {
            strategy: string;
            positions: Asset[];
        }[];
        portfolioPositions: { [ticker: string]: number };
    };
}

  
const PositionsSummary: React.FC<PositionsSummaryProps> = ({ positions }) => {
    const { strategyPositions, portfolioPositions } = positions;

    return (
        <div className="container mx-auto p-4">
            {/* Portfolio-Wide Positions */}
            <div className="mb-8">
                <h2 className="text-xl font-bold mb-4">Aggregated Final Portfolio Positions</h2>
                <table className="w-full border-collapse border border-gray-300">
                    <thead>
                        <tr className="bg-gray-100">
                            <th className="border border-gray-300 px-4 py-2 text-left">Ticker</th>
                            <th className="border border-gray-300 px-4 py-2 text-left">Position</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(portfolioPositions).map(([ticker, position]) => (
                            <tr key={ticker}>
                                <td className="border border-gray-300 px-4 py-2">{ticker}</td>
                                <td className="border border-gray-300 px-4 py-2">{position.toFixed(2)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Strategy-Specific Positions */}
            <div>
                <h2 className="text-xl font-bold mb-4">Strategy-Specific Final Positions</h2>
                {strategyPositions.map(({ strategy, positions }) => (
                    <div key={strategy} className="mb-6">
                        <h3 className="text-lg font-semibold mb-2">{strategy}</h3>
                        <table className="w-full border-collapse border border-gray-300">
                            <thead>
                                <tr className="bg-gray-100">
                                    <th className="border border-gray-300 px-4 py-2 text-left">Ticker</th>
                                    <th className="border border-gray-300 px-4 py-2 text-left">Ideal Positions</th>
                                    <th className="border border-gray-300 px-4 py-2 text-left">Realized Capital</th>
                                </tr>
                            </thead>
                            <tbody>
                                {positions.map((asset) => (
                                    <tr key={asset.ticker}>
                                        <td className="border border-gray-300 px-4 py-2">{asset.ticker}</td>
                                        <td className="border border-gray-300 px-4 py-2">{asset.Ideal_Positions.toFixed(2)}</td>
                                        <td className="border border-gray-300 px-4 py-2">{asset.Realized_Capital.toFixed(2)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default PositionsSummary;