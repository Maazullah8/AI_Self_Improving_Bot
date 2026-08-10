export const metadata = {
  title: 'Trading Bot Dashboard',
  description: 'Autonomous self-improving trading bot monitoring',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#0f1117', color: '#e6e6e6', fontFamily: 'system-ui, sans-serif' }}>
        {children}
      </body>
    </html>
  );
}
