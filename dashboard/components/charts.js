"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const tooltipStyle = {
  background: "var(--color-surface-raised)",
  border: "1px solid var(--color-border)",
  borderRadius: 8,
  fontSize: 11,
  color: "var(--color-foreground)",
};

const axisStyle = { fontSize: 10, fill: "var(--color-muted-foreground)" };

export function EquityChart({ data, height = 300, positive = true }) {
  const stroke = positive ? "var(--color-profit)" : "var(--color-loss)";
  const fill = positive ? "#2fdf7f" : "#f0526e";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={fill} stopOpacity={0.35} />
            <stop offset="100%" stopColor={fill} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="name" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={40} />
        <YAxis
          tick={axisStyle}
          tickLine={false}
          axisLine={false}
          width={70}
          domain={["auto", "auto"]}
          tickFormatter={(v) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "var(--color-muted-foreground)" }} />
        <Area
          type="monotone"
          dataKey="value"
          stroke={stroke}
          strokeWidth={1.5}
          fill="url(#eqGrad)"
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({ data, height = 120 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f0526e" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#f0526e" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="name" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={40} />
        <YAxis
          tick={axisStyle}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "var(--color-muted-foreground)" }} />
        <Area
          type="monotone"
          dataKey="value"
          stroke="var(--color-loss)"
          strokeWidth={1.5}
          fill="url(#ddGrad)"
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function BarChartSimple({ data, height = 220, dataKey = "value", colorMode = "sign" }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="label" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={20} />
        <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={40} />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Bar dataKey={dataKey} radius={[3, 3, 0, 0]} maxBarSize={26}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={colorMode === "sign" ? (d[dataKey] >= 0 ? "var(--color-profit)" : "var(--color-loss)") : "var(--color-ai)"}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
        {colorMode === "sign" && <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TrendLineChart({ data, height = 220, color = "var(--color-ai)" }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="label" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={30} />
        <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={40} domain={[0, 100]} />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "var(--color-muted-foreground)" }} />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          fill="url(#trendGrad)"
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
