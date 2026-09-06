import type { MetadataRoute } from "next";

// Next.js serves this at /manifest.webmanifest automatically and injects
// the right <link rel="manifest"> tag -- this is what makes "Add to Dock"
// (Mac) and "Add to Home Screen" (iPhone) treat the site as an
// installable app instead of just a bookmark.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DayBook AI",
    short_name: "DayBook AI",
    description: "Ridoy Khan's personal AI assistant for tasks, notes, budget, and calendar.",
    start_url: "/",
    display: "standalone",
    background_color: "#0f1115",
    theme_color: "#0f1115",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
