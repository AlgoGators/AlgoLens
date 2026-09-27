import { parseFixedDecimal8 } from '../../domain/numbers/fixedDecimal8';
import { qtComponentKey, type QtSelectionRow } from '../../domain/portfolio/qtPreview';

const scale = 100000000n;
function units(value: string): bigint {
  parseFixedDecimal8(value);
  const negative = value.startsWith('-');
  const [whole, fraction = ''] = (negative ? value.slice(1) : value).split('.');
  const result = BigInt(whole) * scale + BigInt(fraction.padEnd(8, '0'));
  return negative ? -result : result;
}
function delta(source: string, selected: string): string {
  try {
    const difference = units(selected) - units(source);
    const magnitude = difference < 0n ? -difference : difference;
    const fraction = (magnitude % scale).toString().padStart(8, '0').replace(/0+$/, '');
    const text = `${magnitude / scale}${fraction ? `.${fraction}` : ''}`;
    return difference > 0n ? `+${text}` : difference < 0n ? `-${text}` : '0';
  } catch { return 'Invalid quantity'; }
}

// Display matching keeps the exact owner/day identity and only normalizes the two QT streams.
const displayKey = (row: QtSelectionRow) => qtComponentKey({ ...row.key, portfolio_type: 'qt' });
export function QtSelectionTable({ sourceRows, chosenRows, previousQtRows = [], selection, onEdit, locked,
  tableLabel = 'QT component quantities' }: {
  sourceRows: QtSelectionRow[]; chosenRows: QtSelectionRow[];
  previousQtRows?: QtSelectionRow[]; tableLabel?: string;
  selection: Readonly<Record<string, string>>;
  onEdit: (identity: string, value: string) => void; locked: boolean;
}) {
  const source = new Map(sourceRows.filter(row => row.origin === 'verified_model_seed').map(row => [displayKey(row), row]));
  const previous = new Map(previousQtRows.filter(row => row.origin === 'verified_qt_decision').map(row => [displayKey(row), row]));
  // Draft/preview rows are the complete selected book, including immutable holdings.
  // MODEL rows are comparison evidence; they must not add editable selected components.
  const rows = new Map((chosenRows.length ? chosenRows : sourceRows).map(row => [qtComponentKey(row.key), row]));
  return <table aria-label={tableLabel}>
    <thead><tr><th scope="col">Component owner</th><th scope="col">Instrument</th>
      <th scope="col">MODEL recommendation</th><th scope="col">Verified previous QT choice</th>
      <th scope="col">QT chosen quantity</th><th scope="col">Choice origin</th><th scope="col">Change from MODEL</th></tr></thead>
    <tbody>{[...rows].map(([identity, row]) => {
      const sourceQuantity = source.get(displayKey(row))?.quantity_exact;
      const previousQuantity = previous.get(displayKey(row))?.quantity_exact ??
        (row.origin === 'verified_qt_decision' ? row.quantity_exact : undefined);
      const chosen = selection[identity] ?? row.quantity_exact;
      const origin = !row.editable || row.origin === 'immutable' ? 'Immutable holdings' :
        chosen !== row.quantity_exact || row.origin === 'qt_draft' ? 'New QT draft' :
          row.origin === 'verified_qt_decision' ? 'Verified previous QT choice' :
            row.origin === 'verified_model_seed' ? 'MODEL recommendation' : 'Reconciled legacy draft';
      const label = `Chosen quantity for ${row.key.strategy_name} ${row.key.strategy_id} ${row.key.symbol} ${row.key.portfolio_type}`;
      return <tr key={identity}>
        <td>{row.key.strategy_name}<small> ({row.key.strategy_id}; {row.key.portfolio_id}; {row.key.date}; {row.key.portfolio_type})</small></td>
        <td>{row.key.symbol} ({row.asset_type})</td>
        <td>{sourceQuantity ?? 'Unavailable'}</td><td>{previousQuantity ?? 'Unavailable'}</td>
        <td><input type="text" inputMode="decimal" aria-label={label} value={chosen}
          disabled={locked || !row.editable} aria-readonly={!row.editable}
          onChange={event => onEdit(identity, event.target.value)} /></td>
        <td>{origin}</td><td>{sourceQuantity === undefined ? 'Unavailable' : delta(sourceQuantity, chosen)}</td>
      </tr>;
    })}</tbody>
  </table>;
}
