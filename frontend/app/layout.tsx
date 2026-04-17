import type { Metadata } from "next";
import "./globals.css";
import AppProviders from "./NavBarWrapper";

export const metadata: Metadata = {
  title: "DataLens — AI Data Analysis",
  description: "Upload a CSV and analyse it with AI agents",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="h-screen overflow-hidden flex flex-col">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
