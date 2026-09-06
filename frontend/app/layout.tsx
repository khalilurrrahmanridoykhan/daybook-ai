import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DayBook AI",
  description: "Ridoy Khan's personal AI assistant",
  appleWebApp: {
    // Makes "Add to Home Screen" open full-screen with no Safari chrome --
    // without this, an installed icon still opens inside a browser tab.
    capable: true,
    statusBarStyle: "black-translucent",
    title: "DayBook AI",
  },
  icons: {
    icon: [
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#0f1115",
  width: "device-width",
  initialScale: 1,
  // Lets the app draw behind the iPhone's notch/status bar -- needed for
  // a true full-screen, no-chrome feel once installed, matching
  // statusBarStyle: "black-translucent" above.
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
