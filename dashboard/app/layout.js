import "./globals.css";

export const metadata = {
  title: "AI ImprovBot · Trading Intelligence",
  description: "Autonomous self-improving trading bot monitoring",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}
