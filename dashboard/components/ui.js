"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

export function Badge({ variant = "default", children, className = "" }) {
  const styles = {
    default: "bg-muted text-muted-foreground border border-border",
    secondary: "bg-ai/20 text-ai border border-ai/20",
    outline: "border border-border bg-transparent text-muted-foreground",
    profit: "bg-profit/15 text-profit border border-profit/30",
    loss: "bg-loss/15 text-loss border border-loss/30",
    ai: "bg-ai/10 text-ai border border-ai/30",
    active: "bg-profit/15 text-profit border border-profit/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium ${styles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Card({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`card-elevated p-5 space-y-4 ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
            {subtitle && <p className="text-[11px] text-muted-foreground mt-0.5">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

const trendIcon = {
  up: ArrowUpRight,
  down: ArrowDownRight,
  neutral: Minus,
};

export function StatCard({
  label,
  value,
  subvalue,
  trend,
  trendValue,
  icon,
  variant = "default",
  size = "md",
  className = "",
}) {
  const Icon = trend ? trendIcon[trend] : null;
  const TrendIcon = trendIcon[trend];
  const variants = {
    default: "text-foreground",
    profit: "text-profit",
    loss: "text-loss",
    ai: "text-ai",
  };
  const trendColors = {
    up: "text-profit bg-profit/10 border-profit/20",
    down: "text-loss bg-loss/10 border-loss/20",
    neutral: "text-muted-foreground bg-muted border-border",
  };
  const valueSize = size === "lg" ? "text-3xl" : "text-2xl";

  return (
    <div
      className={`card-elevated p-4 flex flex-col gap-2 hover:border-border-strong transition-colors duration-200 fade-up ${className}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
        {icon && <span className="text-muted-foreground [&>svg]:size-4">{icon}</span>}
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className={`font-bold tabular-nums tracking-tight ${valueSize} ${variants[variant]}`}>{value}</div>
          {subvalue && <div className="text-xs text-muted-foreground mt-0.5">{subvalue}</div>}
        </div>
        {trend && (
          <div className="flex items-center gap-1">
            <span
              className={`inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${trendColors[trend]}`}
            >
              {TrendIcon && <TrendIcon className="size-3" />}
              {trendValue}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export function ProgressBar({ value, tone = "ai" }) {
  const tones = {
    ai: "bg-ai",
    profit: "bg-profit",
    loss: "bg-loss",
    muted: "bg-muted-foreground",
  };
  return (
    <div className="h-1.5 w-full rounded-full bg-muted/60 overflow-hidden">
      <div
        className={`h-full rounded-full ${tones[tone]} transition-all duration-500`}
        style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }}
      />
    </div>
  );
}
