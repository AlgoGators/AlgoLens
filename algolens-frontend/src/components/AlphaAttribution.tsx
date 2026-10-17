import { useMemo } from 'react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts';
import type { HistoricalDataPoint } from '../domain/portfolio/portfolioData';

/**
 * Shows whether QT's decisions are adding value: one chart, two lines (D-3, HD 2026-10-16).
 *
 *   system  the model's book of the desk's portfolio (A), from the first QT day
 *   qt      what QT actually held -- the real book
 *
 * The gap between them is the desk's value. This replaces the model twin and the
 * `benchmark` stream it was to feed, which the platform never wrote (D-1).
 */

interface Props {
    equityByStream?: Record<string, HistoricalDataPoint[]>;
    theme: 'light' | 'dark';
}

const STREAM_STYLE: Record<string, { label: string; colour: string; description: string }> = {
    qt: {
        label: 'QT book',
        colour: '#f97316',
        description: 'what we actually held',
    },
    system: {
        label: 'Model book',
        colour: '#6366f1',
        description: "the model's book, before the desk's edits",
    },
};

/** The two books the chart compares, in drawing order. */
export const COMPARED_STREAMS = ['system', 'qt'] as const;

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

export function AlphaAttribution({ equityByStream, theme }: Props) {
    const dark = theme === 'dark';

    const compared = useMemo(() => {
        const out: Record<string, HistoricalDataPoint[]> = {};
        for (const stream of COMPARED_STREAMS) {
            const points = equityByStream?.[stream];
            if (points?.length) out[stream] = points;
        }
        return out;
    }, [equityByStream]);

    const merged = useMemo(() => mergeByDate(compared), [compared]);

    // The headline number: where the QT book ended up versus the model's book.
    const spread = useMemo(() => {
        const qt = compared.qt;
        const model = compared.system;
        if (!qt?.length || !model?.length) return null;
        const qtFinal = qt[qt.length - 1].value;
        const modelFinal = model[model.length - 1].value;
        return { qtFinal, modelFinal, diff: qtFinal - modelFinal };
    }, [compared]);

    const streams = Object.keys(compared);

    // Until the QT book has days of its own there is nothing to compare. Say so
    // plainly rather than rendering an empty chart.
    if (streams.length < 2) {
        return (
            <div
                className={`rounded-lg border p-6 ${dark ? 'border-gray-800 bg-gray-900/40' : 'border-gray-200 bg-gray-50'
                    }`}
            >
                <h3 className={`text-sm font-semibold mb-2 ${dark ? 'text-gray-200' : 'text-gray-900'}`}>
                    Discretionary alpha
                </h3>
                <p className={`text-sm ${dark ? 'text-gray-400' : 'text-gray-600'}`}>
                    Not available yet. This compares the QT book with the model&rsquo;s book of the
                    same portfolio; it needs both, from the first QT day.
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
                        The QT book against the model&rsquo;s book: the gap is the desk&rsquo;s value
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
                            {spread.diff >= 0 ? 'added by the desk' : "given up vs. the model's book"}
                        </div>
                    </div>
                )}
            </div>

            <ResponsiveContainer width="100%" height={280}>
                <LineChart data={merged}>
                    <XAxis
                        dataKey="date"
                        tick={{ fontSize: 11, fill: dark ? '#6b7280' : '#9ca3af' }}
                        tickFormatter={(d: string) =>
                            new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                        }
                        minTickGap={40}
                    />
                    <YAxis
                        tick={{ fontSize: 11, fill: dark ? '#6b7280' : '#9ca3af' }}
                        domain={['dataMin - 500', 'dataMax + 500']}
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
                            new Date(label).toLocaleDateString('en-US', {
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
                            dot={false}
                            connectNulls
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>

            <dl className="mt-4 grid grid-cols-1 gap-1 sm:grid-cols-2">
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
