import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ridoy AI",
  description: "Self-hosted personal AI assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
