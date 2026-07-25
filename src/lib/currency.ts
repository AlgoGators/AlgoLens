export function formatCurrency(
  value: number,
  options?: { minimumFractionDigits?: number; maximumFractionDigits?: number }
): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, ...options })}`;
}
