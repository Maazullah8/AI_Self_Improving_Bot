"use client";

import { useState } from "react";
import { Check, KeyRound, Moon, Save, Shield } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card } from "@/components/ui";

function Toggle({ on, onChange }) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
        on ? "bg-ai" : "bg-muted"
      }`}
      aria-pressed={on}
    >
      <span
        className={`inline-block size-4 transform rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-[18px]" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

function SettingRow({ title, desc, children }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-border/30 last:border-0">
      <div className="min-w-0">
        <div className="text-xs font-medium">{title}</div>
        {desc && <div className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{desc}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Slider({ value, onChange, min = 0, max = 10, step = 0.5 }) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-36 accent-[#8b5cf6]"
    />
  );
}

export default function SettingsPage() {
  const [risk, setRisk] = useState(1);
  const [ddThreshold, setDdThreshold] = useState(10);
  const [maxPositions, setMaxPositions] = useState(5);
  const [saved, setSaved] = useState(false);
  const [toggles, setToggles] = useState({
    newsFilter: true,
    trailingStop: true,
    confirm: true,
    reduceSpacing: false,
  });

  function save() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Platform configuration</h2>
          <p className="text-xs text-muted-foreground">Risk controls, trading preferences and integration settings.</p>
        </div>
        <button
          onClick={save}
          className="flex items-center gap-2 px-3 py-2 rounded-md bg-ai text-white text-xs font-medium hover:bg-ai/90 transition-colors"
        >
          {saved ? <Check className="size-4" /> : <Save className="size-4" />}
          {saved ? "Saved" : "Save Changes"}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Risk Management" subtitle="Risk and execution settings" className="p-4">
          <SettingRow title="Max Risk Per Trade" desc="Maximum allowed risk exposure per individual trade.">
            <div className="flex items-center gap-2 w-40">
              <Slider value={risk} onChange={setRisk} min={0.5} max={5} step={0.1} />
              <span className="text-xs font-semibold tabular-nums w-10 text-right">{risk.toFixed(1)}%</span>
            </div>
          </SettingRow>
          <SettingRow title="Max Drawdown Threshold" desc="Pause AI trading if drawdown exceeds this threshold.">
            <div className="flex items-center gap-2 w-40">
              <Slider value={ddThreshold} onChange={setDdThreshold} min={2} max={30} step={1} />
              <span className="text-xs font-semibold tabular-nums w-10 text-right">-{ddThreshold}%</span>
            </div>
          </SettingRow>
          <SettingRow title="Max Open Positions" desc="Concurrent positions the strategy may hold.">
            <div className="flex items-center gap-2 w-40">
              <Slider value={maxPositions} onChange={setMaxPositions} min={1} max={10} step={1} />
              <span className="text-xs font-semibold tabular-nums w-10 text-right">{maxPositions}</span>
            </div>
          </SettingRow>
          <SettingRow title="Session Filter" desc="Only trade during configured sessions.">
            <div className="flex flex-wrap gap-1.5 max-w-56 justify-end">
              {["Asian", "London", "NY", "Overlap"].map((s) => (
                <span key={s} className="text-[10px] px-2 py-0.5 rounded-md bg-ai/20 text-ai border border-ai/20">{s}</span>
              ))}
            </div>
          </SettingRow>
        </Card>

        <Card title="Trading Preferences" subtitle="Execution behaviour" className="p-4">
          <SettingRow title="News Filter" desc="Skip trades 30 min before/after high-impact news events.">
            <Toggle on={toggles.newsFilter} onChange={(v) => setToggles((t) => ({ ...t, newsFilter: v }))} />
          </SettingRow>
          <SettingRow title="Trailing Stop" desc="Let winning trades run with ATR-based trailing stops.">
            <Toggle on={toggles.trailingStop} onChange={(v) => setToggles((t) => ({ ...t, trailingStop: v }))} />
          </SettingRow>
          <SettingRow title="Reduced confirmation signals" desc="Tighten SL during NY session overlap.">
            <Toggle on={toggles.confirm} onChange={(v) => setToggles((t) => ({ ...t, confirm: v }))} />
          </SettingRow>
          <SettingRow title="Reduce spacing for density" desc="Smooth transitions and micro-interactions throughout the platform.">
            <Toggle on={toggles.reduceSpacing} onChange={(v) => setToggles((t) => ({ ...t, reduceSpacing: v }))} />
          </SettingRow>
        </Card>

        <Card title="Platform" subtitle="Integrations and appearance" className="p-4">
          <SettingRow title="API Key" desc="Stored securely. Never displayed.">
            <div className="flex items-center gap-2">
              <Badge variant="outline"><KeyRound className="size-3" /> sk-••••••••••••••</Badge>
              <span className="text-[10px] text-muted-foreground">Update Key</span>
            </div>
          </SettingRow>
          <SettingRow title="AI Model" desc="Strategy generation and review backend.">
            <Badge variant="ai">GPT-4o-trading-v3.1</Badge>
          </SettingRow>
          <SettingRow title="Learning Speed" desc="Trades reviewed per cycle.">
            <div className="text-xs font-semibold tabular-nums text-foreground/90">47 trades/min</div>
          </SettingRow>
          <SettingRow title="Theme" desc="Appearance.">
            <div className="flex items-center gap-2">
              <Badge variant="outline"><Moon className="size-3" /> Dark</Badge>
            </div>
          </SettingRow>
        </Card>

        <Card title="Account" subtitle="Your profile and subscription" className="p-4">
          <SettingRow title="Trader Account" desc="Plan and renewal.">
            <Badge variant="ai">Pro Plan</Badge>
          </SettingRow>
          <SettingRow title="Next renewal" desc="Billing cycle.">
            <span className="text-xs font-semibold tabular-nums text-foreground/90">2026-09-01</span>
          </SettingRow>
          <SettingRow title="Two-factor authentication" desc="Two-factor authentication and session management coming soon.">
            <Badge variant="outline">Coming soon</Badge>
          </SettingRow>
          <div className="pt-3 flex items-start gap-2 rounded-lg bg-muted/15 border border-border/40 p-3">
            <Shield className="size-4 text-profit shrink-0 mt-0.5" />
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Fail-closed by design: any unknown or unhealthy state results in no trade. Risk controls can never be
              overridden by AI-generated candidates.
            </p>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
