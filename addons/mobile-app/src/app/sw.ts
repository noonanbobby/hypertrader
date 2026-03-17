import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { Serwist } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

// Serwist requires self.__SW_MANIFEST verbatim
const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: defaultCache,
});

// Vibration patterns per event type (used when app is in background)
const VIBRATION_PATTERNS: Record<string, number[]> = {
  buy_open: [100],
  sell_open: [100, 50, 100],
  trade_profit: [80, 40, 80],
  big_win: [100, 50, 100, 50, 100, 50, 200],
  trade_loss: [400],
  big_loss: [300, 100, 300, 100, 300],
  system_error: [200, 100, 200, 100, 200],
  signal_recovery: [50, 30, 50, 30, 100],
  position_aligned: [30],
};

// Push notification handler with sound event support
self.addEventListener("push", (event: PushEvent) => {
  if (!event.data) return;

  let data: { type?: string; title?: string; body?: string; icon?: string; badge?: string; tag?: string };
  try {
    data = event.data.json();
  } catch {
    data = { title: "HyperTrader", body: event.data.text() };
  }

  const eventType = data.type ?? "";
  const vibrate = VIBRATION_PATTERNS[eventType] ?? [200, 100, 200];

  event.waitUntil(
    self.registration.showNotification(data.title ?? "HyperTrader", {
      body: data.body ?? "",
      icon: data.icon ?? "/icons/icon-192.png",
      badge: data.badge ?? "/icons/favicon-32.png",
      tag: data.tag ?? `ht-${eventType || "notification"}`,
      vibrate,
    })
  );
});

// Notification click handler — focus or open app
self.addEventListener("notificationclick", (event: NotificationEvent) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients: readonly WindowClient[]) => {
      const existing = clients.find((c: WindowClient) => c.url.includes(self.location.origin));
      if (existing) {
        return existing.focus();
      }
      return self.clients.openWindow("/");
    })
  );
});

serwist.addEventListeners();
