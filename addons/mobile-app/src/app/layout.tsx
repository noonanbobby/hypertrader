import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#131722",
};

export const metadata: Metadata = {
  title: "HyperTrader",
  description: "Automated BTC Trading Dashboard",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "HyperTrader",
  },
  icons: {
    icon: [
      { url: "/mobile/icons/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/mobile/icons/favicon-16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: [
      { url: "/mobile/icons/apple-touch-icon-180.png", sizes: "180x180" },
      { url: "/mobile/icons/apple-touch-icon-167.png", sizes: "167x167" },
      { url: "/mobile/icons/apple-touch-icon-152.png", sizes: "152x152" },
      { url: "/mobile/icons/apple-touch-icon-120.png", sizes: "120x120" },
    ],
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
};

const splashScreens = [
  { media: "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1170x2532.png" },
  { media: "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1179x2556.png" },
  { media: "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1290x2796.png" },
  { media: "(device-width: 440px) and (device-height: 956px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1320x2868.png" },
  { media: "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)", href: "/mobile/splash/apple-splash-750x1334.png" },
  { media: "(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1125x2436.png" },
  { media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1242x2688.png" },
  { media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2)", href: "/mobile/splash/apple-splash-828x1792.png" },
  { media: "(device-width: 428px) and (device-height: 926px) and (-webkit-device-pixel-ratio: 3)", href: "/mobile/splash/apple-splash-1284x2778.png" },
  { media: "(device-width: 320px) and (device-height: 568px) and (-webkit-device-pixel-ratio: 2)", href: "/mobile/splash/apple-splash-640x1136.png" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        {splashScreens.map(({ media, href }) => (
          <link
            key={href}
            rel="apple-touch-startup-image"
            media={media}
            href={href}
          />
        ))}
      </head>
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
