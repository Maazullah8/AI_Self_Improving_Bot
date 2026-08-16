"use client";

import { useEffect, useState } from "react";
import {
  Bell,
  Check,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Palette,
  Plus,
  Save,
  Settings2,
  Shield,
  Trash2,
  User,
  Zap,
} from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card } from "@/components/ui";
import { activateModel, deleteModel, getModels, saveModel, testModel } from "@/lib/data";

const TABS = [
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "trading", label: "Trading Prefs", icon: Settings2 },
  { id: "ai", label: "AI Connections", icon: Cpu },
  { id: "account", label: "Account", icon: User },
  { id: "security", label: "Security", icon: Shield },
];

const ACCENTS = [
  { name: "Violet", color: "#8b5cf6" },
  { name: "Emerald", color: "#10b981" },
  { name: "Sky", color: "#0ea5e9" },
  { name: "Amber", color: "#f59e0b" },
  { name: "Rose", color: "#f43f5e" },
  { name: "Fuchsia", color: "#d946ef" },
];

const PROVIDERS = {
  ollama: { label: "Ollama (Local)", defaultBase: "http://localhost:11434", defaultModel: "llama3.1:8b", needsKey: false, hint: "Run models on your own computer — no API key required" },
  openai: { label: "OpenAI", defaultBase: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini", needsKey: true, hint: "GPT-4o, GPT-4 Turbo — best for strategy analysis" },
  openrouter: { label: "OpenRouter", defaultBase: "https://openrouter.ai/api/v1", defaultModel: "openai/gpt-4o-mini", needsKey: true, hint: "Access GPT-4o, Claude, Llama, and 100+ models via one key" },
  groq: { label: "Groq", defaultBase: "https://api.groq.com/openai/v1", defaultModel: "llama-3.3-70b-versatile", needsKey: true, hint: "Ultra-fast inference for real-time signals" },
  anthropic: { label: "Anthropic (Claude)", defaultBase: "https://api.anthropic.com/v1", defaultModel: "claude-3-5-haiku-latest", needsKey: true, hint: "Claude — excellent for nuanced trade reasoning" },
  gemini: { label: "Google Gemini", defaultBase: "https://generativelanguage.googleapis.com/v1beta/openai", defaultModel: "gemini-1.5-flash", needsKey: true, hint: "Long context for chart analysis" },
  custom: { label: "Custom (OpenAI-compatible)", defaultBase: "", defaultModel: "", needsKey: true, hint: "Any OpenAI-compatible chat completions endpoint" },
};

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

function SliderRow({ title, desc, value, onChange, min, max, step, unit, valueColor = "text-ai" }) {
  return (
    <SettingRow title={title} desc={desc}>
      <div className="flex items-center gap-2 w-44">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-[#8b5cf6]"
        />
        <span className={`text-xs font-bold tabular-nums w-10 text-right ${valueColor}`}>
          {value}
          {unit}
        </span>
      </div>
    </SettingRow>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState("appearance");
  const [saved, setSaved] = useState(false);

  // appearance
  const [theme, setTheme] = useState("dark");
  const [accentIdx, setAccentIdx] = useState(0);
  const [animations, setAnimations] = useState(true);
  const [compact, setCompact] = useState(false);

  // notifications
  const [notif, setNotif] = useState({ drawdown: true, newTrade: true, aiCycle: true, strategies: true, alerts: false });

  // trading prefs
  const [risk, setRisk] = useState(1.5);
  const [ddThreshold, setDdThreshold] = useState(10);
  const [autoDeploy, setAutoDeploy] = useState(false);
  const [newsFilter, setNewsFilter] = useState(true);

  // AI models
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ provider: "ollama", label: "", base_url: "", model: "", api_key: "" });
  const [showKey, setShowKey] = useState(false);
  const [savingModel, setSavingModel] = useState(false);
  const [testBusy, setTestBusy] = useState(null);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    document.documentElement.style.setProperty("--color-ai", ACCENTS[accentIdx].color);
    localStorage.setItem("accent-color-idx", String(accentIdx));
  }, [accentIdx]);

  useEffect(() => {
    localStorage.setItem("aibot-theme", theme);
  }, [theme]);

  useEffect(() => {
    getModels().then((m) => {
      setModels(m);
      setLoadingModels(false);
    });
  }, []);

  function selectProvider(provider) {
    const meta = PROVIDERS[provider];
    setForm((f) => ({
      ...f,
      provider,
      base_url: f.base_url || meta.defaultBase,
      model: f.model || meta.defaultModel,
    }));
  }

  function openNew() {
    setEditingId(null);
    setForm({ provider: "ollama", label: "", base_url: PROVIDERS.ollama.defaultBase, model: PROVIDERS.ollama.defaultModel, api_key: "" });
    setTestResult(null);
    setFormOpen(true);
  }

  function openEdit(m) {
    setEditingId(m.id);
    setForm({ provider: m.provider, label: m.label, base_url: m.base_url, model: m.model, api_key: "" });
    setTestResult(null);
    setFormOpen(true);
  }

  async function handleSave() {
    setSavingModel(true);
    setTestResult(null);
    try {
      const saved = await saveModel({ ...form, is_active: models.length === 0 });
      const list = await getModels();
      setModels(list);
      setFormOpen(false);
      setEditingId(null);
      setTestResult({ ok: true, note: saved.id ? "Saved" : "" });
    } catch (e) {
      setTestResult({ ok: false, error: String(e) });
    } finally {
      setSavingModel(false);
    }
  }

  async function handleTest() {
    setTestBusy(true);
    setTestResult(null);
    try {
      let id = editingId;
      if (!id) {
        const saved = await saveModel({ ...form, is_active: models.length === 0 });
        const list = await getModels();
        setModels(list);
        id = saved.id;
        setEditingId(id);
      }
      const res = await testModel(id);
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, error: String(e) });
    } finally {
      setTestBusy(false);
    }
  }

  async function handleDelete(id) {
    await deleteModel(id);
    const list = await getModels();
    setModels(list);
    if (editingId === id) setFormOpen(false);
  }

  async function handleActivate(id) {
    await activateModel(id);
    setModels(await getModels());
  }

  function saveChanges() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const input = `w-full rounded-md bg-muted/20 border border-border px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:border-ai/50`;

  return (
    <AppShell>
      <div className="flex flex-col lg:flex-row gap-4">
        {/* tab rail */}
        <nav className="flex lg:flex-col gap-1 overflow-x-auto shrink-0 lg:w-52">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-3 py-2 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
                  active ? "bg-ai/10 text-ai" : "text-muted-foreground hover:text-foreground hover:bg-white/5"
                }`}
              >
                <Icon className="size-4" />
                {t.label}
              </button>
            );
          })}
        </nav>

        <div className="flex-1 min-w-0 max-w-[1000px] space-y-4">
          {tab === "appearance" && (
            <Card title="Appearance" subtitle="Customize how the platform looks">
              <div className="space-y-5">
                <div>
                  <div className="text-xs font-medium mb-2">Theme</div>
                  <div className="inline-flex rounded-md bg-muted/20 border border-border/60 p-0.5">
                    {["dark", "light", "system"].map((t) => (
                      <button
                        key={t}
                        onClick={() => setTheme(t)}
                        className={`px-3 py-1 rounded text-[11px] font-medium capitalize transition-colors ${
                          theme === t ? "border-ai bg-ai/10 text-ai" : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium mb-2">Accent Color</div>
                  <div className="flex flex-wrap gap-2">
                    {ACCENTS.map((a, i) => (
                      <button
                        key={a.name}
                        onClick={() => setAccentIdx(i)}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-[11px] transition-all ${
                          accentIdx === i
                            ? "border-ai bg-ai/10 text-ai scale-105"
                            : "border-border text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <span className="size-3 rounded-full" style={{ background: a.color }} />
                        {a.name}
                        {accentIdx === i && <Check className="size-3" />}
                      </button>
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-2">
                    Changes the accent color used across the entire platform instantly.
                  </p>
                </div>

                <SettingRow title="Animations" desc="Smooth transitions and micro-interactions throughout the platform.">
                  <Toggle on={animations} onChange={setAnimations} />
                </SettingRow>
                <SettingRow title="Compact Mode" desc="Reduce spacing for more information density.">
                  <Toggle on={compact} onChange={setCompact} />
                </SettingRow>
              </div>
            </Card>
          )}

          {tab === "notifications" && (
            <Card title="Notifications" subtitle="Control what you get notified about">
              {Object.entries(notif).map(([k, v]) => (
                <SettingRow key={k} title={k.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase())} desc={`Receive alerts for ${k.replace(/([A-Z])/g, " $1").toLowerCase()} events`}>
                  <Toggle on={v} onChange={(nv) => setNotif((n) => ({ ...n, [k]: nv }))} />
                </SettingRow>
              ))}
            </Card>
          )}

          {tab === "trading" && (
            <Card title="Trading Preferences" subtitle="Risk and execution settings">
              <SliderRow title="Max Risk Per Trade" desc="Maximum allowed risk exposure per individual trade." value={risk} onChange={setRisk} min={0.1} max={5} step={0.1} unit="%" />
              <SliderRow title="Max Drawdown Threshold" desc="Pause AI trading if drawdown exceeds this threshold." value={ddThreshold} onChange={setDdThreshold} min={5} max={25} step={0.5} unit="%" valueColor="text-warning" />
              <SettingRow title="Auto-Deploy Strategies" desc="Automatically deploy strategies that pass all validation gates.">
                <Toggle on={autoDeploy} onChange={setAutoDeploy} />
              </SettingRow>
              <SettingRow title="News Filter" desc="Skip trades 30 min before/after high-impact news events.">
                <Toggle on={newsFilter} onChange={setNewsFilter} />
              </SettingRow>
            </Card>
          )}

          {tab === "ai" && (
            <Card title="AI Connections" subtitle="Connect your AI provider — Ollama locally or an API key for online models">
              <div className="rounded-md bg-ai/5 border border-ai/20 p-3 text-[11px] text-muted-foreground leading-relaxed">
                Ollama runs entirely on your computer — point the base URL at your local server (e.g.{" "}
                <code className="text-ai">http://localhost:11434</code>). For online models, keys are stored in the
                database and used server-side — your key never touches the browser. The AI engine uses the active model
                for strategy analysis, trade review and recommendations. If no model is reachable, the system fails
                closed and uses deterministic analysis.
              </div>

              {loadingModels ? (
                <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">
                  <Loader2 className="size-4 animate-spin mr-2" /> Loading models…
                </div>
              ) : models.length === 0 ? (
                <div className="rounded-lg bg-muted/10 border border-dashed border-border p-6 text-center">
                  <Cpu className="size-6 text-muted-foreground mx-auto mb-2" />
                  <p className="text-xs text-muted-foreground mb-3">No models configured yet.</p>
                  <button
                    onClick={openNew}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-ai text-white text-xs font-medium hover:bg-ai/90 transition-colors"
                  >
                    <Plus className="size-3.5" /> Add a model
                  </button>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {models.map((m) => {
                    const meta = PROVIDERS[m.provider] || { label: m.provider, needsKey: true };
                    return (
                      <div key={m.id} className="rounded-lg bg-muted/10 border border-border/60 p-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-semibold">{m.label || meta.label}</span>
                          {m.is_active && <Badge variant="profit">Active</Badge>}
                          <Badge variant="outline">{m.provider}</Badge>
                          {m.has_key && <Badge variant="outline">Key stored</Badge>}
                          {m.provider === "ollama" && <Badge variant="outline">Local</Badge>}
                          <div className="ml-auto flex items-center gap-1.5">
                            {!m.is_active && (
                              <button
                                onClick={() => handleActivate(m.id)}
                                className="px-2 py-1 rounded-md text-[10px] font-medium bg-ai/10 text-ai border border-ai/20 hover:bg-ai/20 transition-colors"
                              >
                                Activate
                              </button>
                            )}
                            <button
                              onClick={() => openEdit(m)}
                              className="px-2 py-1 rounded-md text-[10px] font-medium bg-muted/20 text-muted-foreground border border-border hover:text-foreground transition-colors"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDelete(m.id)}
                              className="px-2 py-1 rounded-md text-[10px] font-medium bg-loss/10 text-loss border border-loss/20 hover:bg-loss/20 transition-colors"
                            >
                              <Trash2 className="size-3" />
                            </button>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px] text-muted-foreground">
                          <span>Model: <span className="text-foreground/90 font-mono">{m.model || "—"}</span></span>
                          <span>Base URL: <span className="text-foreground/90 font-mono">{m.base_url || "default"}</span></span>
                          {m.masked_key && <span>Key: <span className="font-mono">{m.masked_key}</span></span>}
                        </div>
                        {m.is_active && (
                          <div className="flex items-center gap-1.5 mt-2 text-[11px] text-profit">
                            <CheckCircle2 className="size-3" /> Used by the AI engine
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <button
                    onClick={openNew}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-md bg-ai/10 text-ai text-xs font-medium border border-ai/20 hover:bg-ai/20 transition-colors"
                  >
                    <Plus className="size-3.5" /> Add another model
                  </button>
                </div>
              )}

              {formOpen && (
                <div className="rounded-lg bg-muted/10 border border-border/60 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold">{editingId ? "Edit model" : "Add a model"}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {form.provider === "ollama" ? "Runs on your computer" : "Online via API key"}
                    </span>
                  </div>

                  <div>
                    <label className="block text-[11px] text-muted-foreground mb-1">Provider</label>
                    <select
                      value={form.provider}
                      onChange={(e) => selectProvider(e.target.value)}
                      className={input}
                    >
                      {Object.entries(PROVIDERS).map(([k, v]) => (
                        <option key={k} value={k}>{v.label}</option>
                      ))}
                    </select>
                    <p className="text-[10px] text-muted-foreground mt-1">{PROVIDERS[form.provider].hint}</p>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">Label</label>
                      <input
                        value={form.label}
                        onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
                        placeholder={form.provider === "ollama" ? "My local LLM" : "My online model"}
                        className={input}
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">Model name</label>
                      <input
                        value={form.model}
                        onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                        placeholder={PROVIDERS[form.provider].defaultModel || "model-name"}
                        className={input}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] text-muted-foreground mb-1">
                      Base URL {form.provider === "ollama" && "(Ollama server)"}
                    </label>
                    <input
                      value={form.base_url}
                      onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                      placeholder={form.provider === "ollama" ? "http://localhost:11434" : "https://…/v1"}
                      className={input}
                    />
                  </div>

                  {PROVIDERS[form.provider].needsKey && (
                    <div>
                      <label className="block text-[11px] text-muted-foreground mb-1">API Key</label>
                      <div className="relative">
                        <input
                          type={showKey ? "text" : "password"}
                          value={form.api_key}
                          onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                          placeholder="sk-…"
                          className={`${input} pr-8`}
                        />
                        <button
                          onClick={() => setShowKey((s) => !s)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                        </button>
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Stored in the database and used server-side only — never exposed to the browser.
                      </p>
                    </div>
                  )}

                  {testResult && (
                    <div className={`rounded-md border p-2.5 text-[11px] ${testResult.ok ? "bg-profit/5 border-profit/30 text-profit" : "bg-loss/5 border-loss/30 text-loss"}`}>
                      {testResult.ok
                        ? testResult.reply
                          ? `Connected — latency ${testResult.latency_ms ?? "?"}ms · reply: "${testResult.reply}"`
                          : testResult.note || "Saved"
                        : `Connection failed: ${testResult.error || "unknown error"}`}
                    </div>
                  )}

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSave}
                      disabled={savingModel}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-ai text-white text-xs font-medium hover:bg-ai/90 disabled:opacity-50 transition-colors"
                    >
                      {savingModel ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                      {editingId ? "Update model" : "Save model"}
                    </button>
                    <button
                      onClick={handleTest}
                      disabled={testBusy === "form"}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-muted/20 text-muted-foreground border border-border hover:text-foreground disabled:opacity-50 transition-colors"
                    >
                      {testBusy === "form" ? <Loader2 className="size-3.5 animate-spin" /> : <Zap className="size-3.5" />}
                      Test connection
                    </button>
                    <button
                      onClick={() => setFormOpen(false)}
                      className="ml-auto px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </Card>
          )}

          {tab === "account" && (
            <Card title="Account" subtitle="Local installation profile">
              <div className="flex items-center gap-3">
                <div className="size-12 rounded-lg bg-ai/15 text-ai flex items-center justify-center">
                  <User className="size-6" />
                </div>
                <div>
                  <div className="text-sm font-bold">Local Installation</div>
                  <div className="text-[11px] text-muted-foreground">Self-hosted trading bot</div>
                </div>
                <div className="ml-auto"><Badge variant="outline">Local</Badge></div>
              </div>
              <div className="grid grid-cols-2 gap-3 mt-4">
                {[["Deployment", "Self-hosted"], ["Status", "Active"], ["Data", "Integrated provider"], ["Models", "Configured in AI Connections"]].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-muted/10 border border-border/40 p-3">
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
                    <div className="text-sm font-bold tabular-nums mt-0.5">{v}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {tab === "security" && (
            <Card title="Security" subtitle="">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Two-factor authentication and session management coming soon.
              </p>
              <div className="pt-3 flex items-start gap-2 rounded-lg bg-muted/15 border border-border/40 p-3">
                <Shield className="size-4 text-profit shrink-0 mt-0.5" />
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Fail-closed by design: any unknown or unhealthy state results in no trade. Risk controls can never be
                  overridden by AI-generated candidates, and API keys never leave the server.
                </p>
              </div>
            </Card>
          )}

          <div className="flex items-center justify-end gap-2">
            <button className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
              Cancel
            </button>
            <button
              onClick={saveChanges}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-ai text-white text-xs font-medium hover:bg-ai/90 transition-colors"
            >
              {saved ? <Check className="size-3.5" /> : <Save className="size-3.5" />}
              {saved ? "Saved" : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
