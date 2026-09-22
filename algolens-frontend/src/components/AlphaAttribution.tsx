import { useMemo } from 'react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts';
import type { HistoricalDataPoint } from '../domain/portfolio/portfolioData';
import type { HistoryBreak } from '../domain/portfolio/historySegments';
import { aggregateCommonCoverage } from '../domain/portfolio/commonCoverage';
import { formatBarDate } from '../domain/portfolio/formatBarDate';

/**
 * Shows whether QT's decisions are adding value.
 *
 * The engine writes three streams and, until now, nothing displayed them:
 *
 *   qt         what QT actually decided -- the real book
 *   system     what the algorithm said today, given the real book
 *   benchmark  what the algorithm would have compounded to untouched
 *
 * The comparison that answers "has QT added value over time" is qt vs benchmark.
 * `system` is deliberately NOT the yardstick: position buffering anchors each
 * day's target on yesterday's actual position, so `system` drifts along with
 * QT's own decisions. It scores a single day's tweak; it cannot score a year.
 */

interface Props {
    equityByStream?: Record<string, HistoricalDataPoint[]>;
    historyBreaks?: HistoryBreak[];
    theme: 'light' | 'dark';
}

const STREAM_STYLE: Record<string, { label: string; colour: string; description: string }> = {
    qt: {
        label: 'QT (actual)',
        colour: '#f97316',
        description: 'what we actually held',
    },
    benchmark: {
        label: 'System alone',
        colour: '#6366f1',
        description: 'never saw a QT edit',
    },
    system: {
        label: "Today's signal",
        colour: '#94a3b8',
        description: 'what the algorithm said today, given the real book',
    },
};

/** Merge the per-stream series into rows keyed by date, so recharts can align them. */
function mergeByDate(
    byStream: Record<string, HistoricalDataPoint[]>,
): Array<Record<string, string | number>> {
    const rows = new Map<string, Record<string, string | number>>();

    for (const [stream, points] of Object.entries(byStream)) {
        for (const point of points) {
            const existing = rows.get(point.date) ?? { date: point.date };
            existing[stream] = point.value;
            rows.set(point.date, existing);
        }
    }

    return Array.from(rows.values()).sort((a, b) =>
        String(a.date).localeCompare(String(b.date)),
    );
}

const money = (n: number) =>
    `$${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;

export function AlphaAttribution({ equityByStream, historyBreaks, theme }: Props) {
    const dark = theme === 'dark';

    const namedStreams = useMemo(() => {
        if (!equityByStream) return {};
        return Object.fromEntries(
            ['qt', 'benchmark', 'system']
                .filter(name => equityByStream[name]?.length)
                .map(name => [name, equityByStream[name]]),
        );
    }, [equityByStream]);

    const merged = useMemo(() => {
        const rows = mergeByDate(namedStreams);
        for (const item of [...(historyBreaks ?? [])].sort((a, b) => a.date.localeCompare(b.date))) {
            const index = rows.findIndex(row => String(row.date) >= item.date);
            if (index > 0) rows.splice(index, 0, { date: `${item.date} (history break)` });
        }
        return rows;
    }, [historyBreaks, namedStreams]);

    // The headline number: where the real book ended up versus where the
    // untouched system would have. Only meaningful once both streams exist.
    const spread = useMemo(() => {
        if (!equityByStream) return null;
        const qt = equityByStream.qt;
        const bench = equityByStream.benchmark;
        if (!qt?.length || !bench?.length) return null;
        const common = aggregateCommonCoverage([
            { id: 'qt', points: qt, historyBreaks },
            { id: 'benchmark', points: bench, historyBreaks },
        ]);
        const comparisonDate = common.coverage.lastCommonDate;
        if (!comparisonDate) return null;
        const qtFinal = qt.find(point => point.date === comparisonDate)!.value;
        const benchFinal = bench.find(point => point.date === comparisonDate)!.value;
        return {
            qtFinal,
            benchFinal,
            diff: qtFinal - benchFinal,
            comparisonDate,
            coverage: common.coverage,
            qtLatest: qt[qt.length - 1].date,
            benchmarkLatest: bench[bench.length - 1].date,
        };
    }, [equityByStream, historyBreaks]);

    const streams = Object.keys(namedStreams);
    const hasRequiredStreams = streams.includes('qt') && streams.includes('benchmark');

    // Before the dual-portfolio migration there is only one stream, so there is
    // nothing to compare. Say so plainly rather than rendering an empty chart.
    if (!hasRequiredStreams || !spread) {
        return (
            <div
                className={`rounded-lg border p-6 ${dark ? 'border-gray-800 bg-gray-900/40' : 'border-gray-200 bg-gray-50'
                    }`}
            >
                <h3 className={`text-sm font-semibold mb-2 ${dark ? 'text-gray-200' : 'text-gray-900'}`}>
                    Discretionary alpha
                </h3>
                <p className={`text-sm ${dark ? 'text-gray-400' : 'text-gray-600'}`}>
                    Not available yet. This comparison needs both the QT and benchmark streams
                    with at least one shared date.
                </p>
            </div>
        );
    }

    return (
        <div
            className={`rounded-lg border p-6 ${dark ? 'border-gray-800 bg-gray-900/40' : 'border-gray-200 bg-white'
                }`}
        >
            <div className="flex items-start justify-between mb-4">
                <div>
                    <h3 className={`text-sm font-semibold ${dark ? 'text-gray-200' : 'text-gray-900'}`}>
                        Discretionary alpha
                    </h3>
                    <p className={`text-xs mt-1 ${dark ? 'text-gray-500' : 'text-gray-500'}`}>
                        QT&rsquo;s book versus the same system left untouched
                    </p>
                </div>

                {spread && (
                    <div className="text-right">
                        <div
                            className={`text-2xl font-semibold tabular-nums ${spread.diff >= 0 ? 'text-emerald-500' : 'text-red-500'
                                }`}
                        >
                            {spread.diff >= 0 ? '+' : '−'}
                            {money(Math.abs(spread.diff))}
                        </div>
                        <div className={`text-xs ${dark ? 'text-gray-500' : 'text-gray-500'}`}>
                            {spread.diff >= 0 ? 'added by QT' : 'given up vs. system alone'}
                        </div>
                        <div className={`text-xs ${dark ? 'text-gray-500' : 'text-gray-500'}`}>
                            Compared on {formatBarDate(spread.comparisonDate)}
                        </div>
                    </div>
                )}
            </div>

            {(spread.coverage.partial || spread.qtLatest !== spread.benchmarkLatest) && (
                <p className={`mb-3 text-xs ${dark ? 'text-amber-400' : 'text-amber-700'}`}>
                    {spread.coverage.excludedDates.length > 0
                        ? `${spread.coverage.excludedDates.length} ${spread.coverage.excludedDates.length === 1 ? 'date' : 'dates'} excluded from the QT comparison. `
                        : ''}
                    {spread.qtLatest !== spread.benchmarkLatest
                        ? `The latest QT point is ${formatBarDate(spread.qtLatest)}; benchmark is ${formatBarDate(spread.benchmarkLatest)}.`
                        : ''}
                </p>
            )}

            <ResponsiveContainer width="100%" height={280}>
                <LineChart data={merged}>
                    <XAxis
                        dataKey="date"
                        tick={{ fontSize: 11, fill: dark ? '#6b7280' : '#9ca3af' }}
                        tickFormatter={(d: string) =>
                            formatBarDate(d, { month: 'short', day: 'numeric' })
                        }
                        minTickGap={40}
                    />
                    <YAxis
                        tick={{ fontSize: 11, fill: dark ? '#6b7280' : '#9ca3af' }}
                        domain={['auto', 'auto']}
                        tickFormatter={money}
                        width={70}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: dark ? '#1f2937' : '#fff',
                            border: dark ? '1px solid #374151' : '1px solid #e5e7eb',
                            borderRadius: '8px',
                            color: dark ? '#fff' : '#000',
                        }}
                        formatter={(value: number, name: string) => [
                            money(value),
                            STREAM_STYLE[name]?.label ?? name,
                        ]}
                        labelFormatter={(label) =>
                            formatBarDate(String(label), {
                                month: 'short',
                                day: 'numeric',
                                year: 'numeric',
                            })
                        }
                    />
                    <Legend
                        formatter={(name: string) => STREAM_STYLE[name]?.label ?? name}
                        wrapperStyle={{ fontSize: 12 }}
                    />
                    {streams.map((stream) => (
                        <Line
                            key={stream}
                            type="linear"
                            dataKey={stream}
                            stroke={STREAM_STYLE[stream]?.colour ?? '#94a3b8'}
                            strokeWidth={stream === 'qt' ? 2 : 1.5}
                            // The signal-of-the-day line is context, not a comparison
                            // baseline, so it is visually subordinate.
                            strokeDasharray={stream === 'system' ? '4 3' : undefined}
                            dot={false}
                            connectNulls={false}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>

            <dl className="mt-4 grid grid-cols-1 gap-1 sm:grid-cols-3">
                {streams.map((stream) => (
                    <div key={stream} className="flex items-baseline gap-2">
                        <span
                            className="inline-block h-2 w-2 rounded-full shrink-0"
                            style={{ backgroundColor: STREAM_STYLE[stream]?.colour ?? '#94a3b8' }}
                        />
                        <dt className={`text-xs font-medium ${dark ? 'text-gray-300' : 'text-gray-700'}`}>
                            {STREAM_STYLE[stream]?.label ?? stream}
                        </dt>
                        <dd className={`text-xs ${dark ? 'text-gray-500' : 'text-gray-500'}`}>
                            {STREAM_STYLE[stream]?.description}
                        </dd>
                    </div>
                ))}
            </dl>
        </div>
    );
}

export default AlphaAttribution;
