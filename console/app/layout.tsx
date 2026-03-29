import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MASA Operator Console",
  description: "Epistemic wall orchestration workbench",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
