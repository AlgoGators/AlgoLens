/** Validate canonical signed int64 fixed-point Decimal8 text. */
export function parseFixedDecimal8(value: unknown): string {
  if (typeof value !== 'string' || value.length > 21) {
    throw new Error('invalid_fixed_decimal8');
  }
  const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{0,7}[1-9])?$/.exec(value);
  if (!match || match[0].length !== value.length || value === '-0') {
    throw new Error('invalid_fixed_decimal8');
  }

  const negative = value.startsWith('-');
  const unsigned = negative ? value.slice(1) : value;
  const [integer, fraction = ''] = unsigned.split('.');
  const magnitude = BigInt(integer) * 100000000n + BigInt(fraction.padEnd(8, '0'));
  const scaled = negative ? -magnitude : magnitude;
  if (scaled < -9223372036854775808n || scaled > 9223372036854775807n) {
    throw new Error('invalid_fixed_decimal8');
  }
  return value;
}
