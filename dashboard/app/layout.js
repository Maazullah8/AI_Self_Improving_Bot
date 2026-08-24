import "./globals.css";

export const metadata = {
  title: "AI ImprovBot · Trading Intelligence",
  description: "Autonomous self-improving trading bot monitoring",
};

export default function RootLayout({ children }) {
  return (
    {/* suppressHydrationWarning: browser extensions like Dark Reader inject
        attributes (data-darkreader-*) into <html> before React hydrates,
        causing harmless hydration-mismatch warnings in dev. */}
    <html lang="en" suppressHydrationWarning>
      <body>
        {children}
      </body>
    </html>
  );
}
