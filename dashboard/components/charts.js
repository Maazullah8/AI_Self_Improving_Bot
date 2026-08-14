"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
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

export function BarChartSimple({ data, height = 220, dataKey = "value", colorMode = "sign", layout = "vertical" }) {
  if (layout === "horizontal") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
          <XAxis type="number" tick={axisStyle} tickLine={false} axisLine={false} />
          <YAxis
            type="category"
            dataKey="label"
            tick={axisStyle}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={{ color: "var(--color-muted-foreground)" }}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
          />
          <Bar dataKey={dataKey} radius={[0, 4, 4, 0]} maxBarSize={14}>
            {data.map((d, i) => (
              <Cell
                key={i}
                fill={colorMode === "sign" ? (d[dataKey] >= 0 ? "var(--color-profit)" : "var(--color-loss)") : "var(--color-ai)"}
                fillOpacity={0.85}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }
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

export function ScoreRadarChart({ data, height = 220 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="rgba(255,255,255,0.1)" />
        <PolarAngleAxis dataKey="metric" tick={{ fill: "var(--color-muted-foreground)", fontSize: 10 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar
          dataKey="value"
          name="Score"
          stroke="var(--color-ai)"
          strokeWidth={1.5}
          fill="var(--color-ai)"
          fillOpacity={0.15}
        />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "var(--color-muted-foreground)" }} />
      </RadarChart>
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

export function MonteCarloChart({ mode, paths, distribution, height = 280 }) {
  if (mode === "distribution" && distribution && distribution.length) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={distribution} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis dataKey="bin" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={36} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={{ color: "var(--color-muted-foreground)" }}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            formatter={(value, name, props) => [
              `${value} sims · ${props.payload.bin}`,
              "Final return",
            ]}
          />
          <ReferenceLine x={0} stroke="rgba(255,255,255,0.15)" />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={16}>
            {distribution.map((d, i) => (
              <Cell
                key={i}
                fill={d.value >= 0 ? "var(--color-ai)" : "var(--color-loss)"}
                fillOpacity={d.value >= 0 ? 0.85 : 0.65}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (!paths || !paths.rows || !paths.keys.length) return null;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={paths.rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="pct" tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
        <YAxis
          tick={axisStyle}
          tickLine={false}
          axisLine={false}
          width={70}
          domain={["auto", "auto"]}
          tickFormatter={(v) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
          labelFormatter={(_, p) => `${p?.[0]?.payload?.bar ?? ""}th bar`}
        />
        <ReferenceLine
          y={paths.initial}
          stroke="rgba(255,255,255,0.2)"
          strokeDasharray="4 4"
        />
        {paths.keys.map((k, i) => (
          <Line
            key={k}
            type="monotone"
            dataKey={k}
            stroke="var(--color-ai)"
            strokeOpacity={k === "median" ? 1 : 0.22}
            strokeWidth={k === "median" ? 1.8 : 0.6}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function WalkForwardChart({ data, height = 260 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis dataKey="segment" tick={axisStyle} tickLine={false} axisLine={false} />
        <YAxis
          tick={axisStyle}
          tickLine={false}
          axisLine={false}
          width={36}
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "var(--color-muted-foreground)" }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line
          type="monotone"
          dataKey="train_win_rate"
          name="Train win rate"
          stroke="var(--color-ai)"
          strokeWidth={1.6}
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="test_win_rate"
          name="Test win rate"
          stroke="var(--color-profit)"
          strokeWidth={1.6}
          dot={{ r: 3, strokeWidth: 0 }}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
