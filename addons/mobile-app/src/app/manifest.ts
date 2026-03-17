import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "HyperTrader",
    short_name: "HyperTrader",
    description: "Automated BTC Trading Dashboard",
    start_url: "/mobile/",
    display: "standalone",
    orientation: "portrait",
    theme_color: "#131722",
    background_color: "#131722",
    icons: [
      {
        src: "/mobile/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/mobile/icons/icon-384.png",
        sizes: "384x384",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/mobile/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/mobile/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    // Screenshots will be added after app is fully built
  };
}
