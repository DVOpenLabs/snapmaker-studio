import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins, Tag, TrendingUp, ChevronDown, RotateCcw, RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { costToPrice, pricingDoctor, profitDoctor } from "@/api";
import { useFilament } from "@/store/filament";
import { useBusiness, bizFactors, MATERIAL_DENSITY } from "@/store/business";
import {
  draftFrom, splitDraft, validateBusinessDraft, isBusinessDirty, hasErrors, type BizDraft,
} from "@/lib/businessForm";

function NumField({ label, value, onChange, step = 1, helper, error, blankWhenZero }:
  { label: string; value: number; onChange: (v: number) => void; step?: number;
    helper?: string; error?: string; blankWhenZero?: boolean }) {
  const display = blankWhenZero && (!value || Number.isNaN(value)) ? "" : value;
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <input type="number" min={0} step={step} value={display}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value) || 0)}
        className={`w-full rounded-md border bg-background px-2 py-1 text-xs outline-none focus:border-primary ${error ? "border-doctor-cost" : "border-border"}`} />
      {error
        ? <span className="text-[10px] text-doctor-cost">{error}</span>
        : helper ? <span className="text-[10px] text-muted-foreground">{helper}</span> : null}
    </label>
  );
}

// The Business Intelligence Layer made visible: Cost / Pricing / Profit Doctors
// as three first-class cards. Beginner-friendly headline numbers up top; the
// breakdown, tiers, and projections live behind a "Show details" disclosure.
//
// Editing model: the assumptions form edits a *draft*. The three cards keep
// showing the last *applied* calculation (queries key on the applied store, not
// the draft) so typing "10" never recalculates mid-keystroke. Results update only
// when the user clicks Recalculate.
export function BusinessDoctors({ filePath, host }: { filePath: string; host?: string | null }) {
  const [open, setOpen] = useState(false);
  const { pricePerKg, currency } = useFilament();
  const biz = useBusiness();

  // Applied = what's currently in the stores. Draft = what the user is editing.
  const applied = draftFrom(biz, pricePerKg);
  const [draft, setDraft] = useState<BizDraft>(applied);
  const errors = validateBusinessDraft(draft);
  const dirty = isBusinessDirty(draft, applied);
  const setField = <K extends keyof BizDraft>(k: K, v: BizDraft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  function recalculate() {
    if (hasErrors(validateBusinessDraft(draft))) return; // inline errors shown; don't apply
    const { spoolPrice, assumptions } = splitDraft(draft);
    biz.set(assumptions);
    useFilament.getState().setPrice(spoolPrice);
  }
  function resetAll() {
    biz.reset();
    setDraft(draftFrom(useBusiness.getState(), useFilament.getState().pricePerKg));
  }

  // Queries key on the APPLIED factors, so editing the draft does not refetch.
  const factors = bizFactors(biz, pricePerKg);
  const fkey = JSON.stringify(factors) + currency;
  const cost = useQuery({ queryKey: ["bd-cost", filePath, host, fkey], queryFn: () => costToPrice(filePath, { host, currency, factors }), retry: false, staleTime: 30000 });
  const pricing = useQuery({ queryKey: ["bd-pricing", filePath, host, fkey], queryFn: () => pricingDoctor(filePath, host, { currency, factors }), retry: false, staleTime: 30000 });
  const profit = useQuery({ queryKey: ["bd-profit", filePath, host, fkey], queryFn: () => profitDoctor(filePath, host, { currency, factors }), retry: false, staleTime: 30000 });

  const c = cost.data, p = pricing.data, pr = profit.data;
  const loading = cost.isLoading || pricing.isLoading;
  if (loading && !c?.available && !p?.available) {
    return (
      <Card><CardContent className="space-y-1 p-5">
        <span className="text-sm font-semibold">Cost, Pricing &amp; Profit</span>
        <p className="text-xs text-muted-foreground">Estimating cost…</p>
      </CardContent></Card>
    );
  }
  // Studio couldn't read grams/volume from this file — do NOT dead-end. Show the
  // assumptions form below so the user can enter grams from Orca's filament
  // estimate and still get cost / price / profit.
  const unreadable = !c?.available && !p?.available;
  // Has the user supplied grams manually (so we can actually calculate)?
  const hasManualGrams = (draft.gramsOverride || 0) > 0 || (applied.gramsOverride || 0) > 0;
  const cur = c?.currency ?? p?.currency ?? "$";
  const mk = p?.tiers?.find((t) => t.label === "Marketplace");

  const Pillar = ({ icon: Icon, name, token, value, sub }: any) => (
    <div className="flex-1 rounded-lg border border-border p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md"
              style={{ color: `hsl(var(${token}))`, backgroundColor: `hsl(var(${token}) / 0.12)` }}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="text-xs font-semibold">{name}</span>
      </div>
      <p className="mt-2 text-lg font-bold tabular-nums">{value}</p>
      <p className="text-[11px] text-muted-foreground">{sub}</p>
    </div>
  );

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold">Cost, Pricing &amp; Profit</span>
          <span className="text-[11px] text-muted-foreground">rough estimates · your assumptions · not financial advice</span>
        </div>

        {unreadable && (
          <div className="rounded-md border border-doctor-cost/40 bg-doctor-cost/5 p-2.5 text-xs text-muted-foreground">
            Studio couldn&apos;t read grams from this file. Enter grams from Orca&apos;s filament estimate below, then click Recalculate.
          </div>
        )}

        {unreadable && !hasManualGrams ? (
          <div className="rounded-lg border border-border p-3 text-xs text-muted-foreground">
            Enter grams to calculate cost.
          </div>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Pillar icon={Coins} name="Cost Doctor" token="--doctor-cost"
                    value={c?.available ? `${cur}${c.true_cost}` : "—"}
                    sub="true cost to make" />
            <Pillar icon={Tag} name="Pricing Doctor" token="--stage-validate"
                    value={mk ? `${cur}${mk.price}` : "—"}
                    sub="suggested marketplace price" />
            <Pillar icon={TrendingUp} name="Profit Doctor" token="--stage-output"
                    value={pr?.available ? `${cur}${pr.profit_per_print}` : "—"}
                    sub={pr?.available ? `${pr.margin_pct}% margin / print` : "profit per print"} />
          </div>
        )}

        {!unreadable && (
          <button onClick={() => setOpen((o) => !o)}
                  className="flex items-center gap-1 text-xs font-medium text-primary">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            {open ? "Hide details" : "Show details & assumptions"}
          </button>
        )}

        {(open || unreadable) && (
          <div className="space-y-3 border-t border-border pt-3 text-xs">
            <div className="space-y-2 rounded-md border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold">Material &amp; business assumptions</p>
                <div className="flex items-center gap-2">
                  {dirty && <span className="text-[11px] text-doctor-cost">Changes not applied yet</span>}
                  <button onClick={recalculate} disabled={!dirty || hasErrors(errors)}
                    className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-50">
                    <RefreshCw className="h-3 w-3" /> Recalculate
                  </button>
                  <button onClick={resetAll} className="flex items-center gap-1 text-[11px] text-primary hover:underline">
                    <RotateCcw className="h-3 w-3" /> Reset
                  </button>
                </div>
              </div>
              <p className="text-muted-foreground">Saved locally. Enter your spool price, then click Recalculate to update the cards.</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <NumField label={`Spool price ${currency}`} value={draft.spoolPrice}
                  onChange={(v) => setField("spoolPrice", v)} step={0.5}
                  helper="Price you paid for the filament spool" error={errors.spoolPrice} />
                <NumField label="Spool weight (g)" value={draft.spoolWeightG}
                  onChange={(v) => setField("spoolWeightG", v)}
                  helper="Usually 1000 g for a 1 kg spool" error={errors.spoolWeightG} />
                <NumField label="Grams used" value={draft.gramsOverride}
                  onChange={(v) => setField("gramsOverride", v)} blankWhenZero
                  helper={unreadable ? "Enter grams from Orca's filament estimate." : `Leave blank to use Studio estimate: ${c?.grams ?? "—"} g`} error={errors.gramsOverride} />
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Material</span>
                  <select value={draft.material} onChange={(e) => setField("material", e.target.value)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs outline-none focus:border-primary">
                    {Object.keys(MATERIAL_DENSITY).map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </label>
                <NumField label="Markup / margin" value={draft.markupPct}
                  onChange={(v) => setField("markupPct", v)}
                  helper="Used to estimate a suggested selling price" error={errors.markupPct} />
              </div>
              {c?.available && c.grams != null && (
                <p className="text-muted-foreground">
                  Material: {c.grams} g × {currency}{pricePerKg} ÷ {biz.spoolWeightG} g ={" "}
                  <span className="font-medium text-foreground">{currency}{c.breakdown?.material}</span>
                  {" "}({c.basis}).
                </p>
              )}
              <details>
                <summary className="cursor-pointer text-primary">Advanced costs (electricity, machine, labour, fees, shipping)</summary>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  <NumField label="Print hours" value={draft.printHours} onChange={(v) => setField("printHours", v)} step={0.1}
                    blankWhenZero helper={`Leave blank to use slicer time${c?.time_known ? ` (${c.print_hours} h)` : ""}`} />
                  <NumField label="Electricity /kWh" value={draft.electricityPerKwh} onChange={(v) => setField("electricityPerKwh", v)} step={0.01} />
                  <NumField label="Printer watts" value={draft.powerW} onChange={(v) => setField("powerW", v)} />
                  <NumField label="Printer price" value={draft.machinePrice} onChange={(v) => setField("machinePrice", v)} />
                  <NumField label="Printer life (hrs)" value={draft.machineLifeHours} onChange={(v) => setField("machineLifeHours", v)} />
                  <NumField label="Labor (hrs/print)" value={draft.laborHours} onChange={(v) => setField("laborHours", v)} step={0.05} />
                  <NumField label={`Labor ${currency}/hr`} value={draft.laborRate} onChange={(v) => setField("laborRate", v)} />
                  <NumField label="Packaging" value={draft.packaging} onChange={(v) => setField("packaging", v)} step={0.25} />
                  <NumField label="Waste / failure %" value={draft.failureRatePct} onChange={(v) => setField("failureRatePct", v)} />
                  <NumField label="Marketplace fee %" value={draft.marketplaceFeePct} onChange={(v) => setField("marketplaceFeePct", v)} />
                  <NumField label="Shipping cost" value={draft.shippingCost} onChange={(v) => setField("shippingCost", v)} step={0.5} />
                  <NumField label="Shipping charged" value={draft.shippingCharged} onChange={(v) => setField("shippingCharged", v)} step={0.5} />
                </div>
              </details>
              {c?.available && !c.time_known && biz.printHours <= 0 && (
                <p className="text-doctor-cost">Print time unknown — enter print hours from Orca or your estimate above to include electricity, machine wear &amp; labour.</p>
              )}
              <p className="text-muted-foreground opacity-80">Rough estimate — not financial advice.</p>
            </div>
            {c?.available && c.breakdown && (
              <div>
                <p className="mb-1 font-semibold">Cost breakdown {c.basis ? `(${c.basis})` : ""}</p>
                <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-muted-foreground sm:grid-cols-3">
                  <li>Material: {cur}{c.breakdown.material}</li>
                  <li>Electricity: {cur}{c.breakdown.electricity}</li>
                  <li>Machine wear: {cur}{c.breakdown.depreciation}</li>
                  <li>Labour: {cur}{c.breakdown.labor}</li>
                  <li>Failure buffer: {cur}{c.breakdown.failure_buffer}</li>
                </ul>
                {!c.time_known && <p className="mt-1 text-muted-foreground opacity-70">Print time unknown — time-based costs shown as 0 until sliced or read from the printer.</p>}
              </div>
            )}
            {p?.available && p.tiers && (
              <div>
                <p className="mb-1 font-semibold">Pricing tiers</p>
                <ul className="space-y-0.5 text-muted-foreground">
                  {p.tiers.map((t) => (
                    <li key={t.label}><span className="font-medium text-foreground">{t.label}: {cur}{t.price}</span> — {t.why}</li>
                  ))}
                </ul>
              </div>
            )}
            {pr?.available && (
              <div>
                <p className="mb-1 font-semibold">Profit projection</p>
                <p className="text-muted-foreground">{pr.verdict}</p>
                {pr.batch && <p className="text-muted-foreground">Batch of {pr.batch.count}: {cur}{pr.batch.profit} profit.</p>}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
