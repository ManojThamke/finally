const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return usd.format(v);
}

export function formatPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatSignedUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${usd.format(Math.abs(v))}`;
}

export function formatPercent(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function formatQty(v: number): string {
  return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function toneClass(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || Math.abs(v) < 1e-9) return "text-ink-300";
  return v > 0 ? "text-up" : "text-down";
}
