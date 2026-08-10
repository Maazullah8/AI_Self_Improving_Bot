'use client';

import { useEffect, useState } from 'react';

function useFetch(path) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, [path]);
  return { data, err };
}

function Card({ title, children }) {
  return (
    <div style={{ background: '#1a1d26', borderRadius: 8, padding: 16, margin: 8 }}>
      <h3 style={{ marginTop: 0, fontSize: 13, color: '#8b93a7' }}>{title}</h3>
      {children}
    </div>
  );
}

function fmt(v) {
  if (v === null || v === undefined) return '-';
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(v);
}

export default function Page() {
  const health = useFetch('/api/health');
  const metrics = useFetch('/api/metrics');
  const trades = useFetch('/api/trades?limit=200');
  const strategies = useFetch('/api/strategies');
  const reviews = useFetch('/api/reviews');

  const m = metrics.data || {};
  const metricRows = [
    ['Equity', m.final_equity],
    ['Return %', m.total_return_pct],
    ['Trades', m.n_trades],
    ['Win rate %', m.win_rate],
    ['Profit factor', m.profit_factor],
    ['Expectancy (R)', m.expectancy_r],
    ['Max drawdown %', m.max_drawdown_pct],
    ['Recovery factor', m.recovery_factor],
    ['Sharpe (R)', m.sharpe_r],
  ];

  return (
    <main style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22 }}>
        Autonomous Trading Bot{' '}
        <span style={{ color: health.data?.status === 'ok' ? '#3fb950' : '#f85149', fontSize: 14 }}>
          {health.err ? 'backend offline' : health.data?.status}
        </span>
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
        <Card title="Performance">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <tbody>
              {metricRows.map(([k, v]) => (
                <tr key={k}>
                  <td style={{ color: '#8b93a7', padding: '3px 0' }}>{k}</td>
                  <td style={{ textAlign: 'right' }}>{fmt(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Strategy Versions">
          {strategies.err ? (
            <p style={{ color: '#f85149', fontSize: 13 }}>unavailable</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <tbody>
                {(strategies.data || []).slice(-10).map((s) => (
                  <tr key={s.version}>
                    <td>{s.name}</td>
                    <td style={{ color: '#8b93a7' }}>{s.version}</td>
                    <td style={{ color: '#8b93a7' }}>{s.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="AI Reviews">
          {reviews.err ? (
            <p style={{ color: '#f85149', fontSize: 13 }}>unavailable</p>
          ) : (
            <div style={{ maxHeight: 260, overflow: 'auto', fontSize: 12 }}>
              {(reviews.data || []).slice(-5).map((r) => (
                <p key={r.id} style={{ borderBottom: '1px solid #2a2e3a', padding: '6px 0', margin: 0 }}>
                  <b>{r.strategy_version}</b> · {r.n_trades} trades
                  <br />
                  <span style={{ color: '#8b93a7' }}>{r.summary}</span>
                </p>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title={`Recent Trades (${(trades.data || []).length})`}>
        {trades.err ? (
          <p style={{ color: '#f85149', fontSize: 13 }}>unavailable</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: '#8b93a7', textAlign: 'left' }}>
                <th>Entry</th>
                <th>Side</th>
                <th>Price</th>
                <th>R</th>
                <th>Exit</th>
                <th>Zone</th>
                <th>Conf</th>
              </tr>
            </thead>
            <tbody>
              {(trades.data || []).slice(-20).reverse().map((t) => (
                <tr key={t.trade_id} style={{ borderTop: '1px solid #2a2e3a' }}>
                  <td>{new Date(t.entry_time * 1000).toISOString().slice(0, 16)}</td>
                  <td style={{ color: t.side === 'buy' ? '#3fb950' : '#f85149' }}>{t.side}</td>
                  <td>{fmt(t.entry_price)}</td>
                  <td style={{ color: t.r >= 0 ? '#3fb950' : '#f85149' }}>{fmt(t.r)}</td>
                  <td>{t.exit_reason}</td>
                  <td>{t.zone_type}</td>
                  <td>{t.confluence_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
