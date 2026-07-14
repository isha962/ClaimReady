import type { Metadata } from "next";

import { AppShell } from "@/components/ui";

import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimReady",
  description: "Biller-facing reconciliation dashboard for wound-care claims operations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
