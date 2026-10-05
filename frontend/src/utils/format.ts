const numbers = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 });
const preciseNumbers = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 });
const times = new Intl.DateTimeFormat('fr-FR', { timeStyle: 'medium' });

export function formatNumber(value: number | null | undefined, precise = false) {
  return value == null ? '—' : (precise ? preciseNumbers : numbers).format(value);
}

export function formatTime(value: string | number | null | undefined) {
  return value == null ? '—' : times.format(new Date(value));
}
