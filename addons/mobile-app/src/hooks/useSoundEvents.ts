"use client";

import { useCallback, useEffect, useRef } from "react";
import { getSoundManager } from "@/lib/sounds";
import type { SoundEventType } from "@/lib/sound-generator";
import type { WsEvent, TradeEvent, PositionEvent } from "@/types";

/**
 * Hook that initializes the SoundManager and provides
 * a callback to play sounds for WebSocket events.
 */
export function useSoundEvents() {
  const initRef = useRef(false);

  // Initialize SoundManager on first user gesture
  useEffect(() => {
    if (initRef.current) return;

    const unlock = () => {
      if (!initRef.current) {
        initRef.current = true;
        getSoundManager().init();
      }
    };

    // Listen for first interaction
    const events = ["touchstart", "mousedown", "keydown"] as const;
    events.forEach((e) => window.addEventListener(e, unlock, { once: true, passive: true }));

    return () => {
      events.forEach((e) => window.removeEventListener(e, unlock));
    };
  }, []);

  /**
   * Determine the sound event type from a WebSocket event and play it.
   */
  const handleWsEvent = useCallback((event: WsEvent) => {
    const sm = getSoundManager();
    let eventType: SoundEventType | null = null;

    if (event.type === "position_update") {
      const data = event.data as PositionEvent;
      if (data.action === "opened") {
        eventType = data.side.toLowerCase() === "long" ? "buy_open" : "sell_open";
      }
    } else if (event.type === "trade_fill") {
      const data = event.data as TradeEvent;
      if (data.action === "closed") {
        const pnl = data.pnl;
        if (pnl > 0) {
          // Check if big win (>5% would need entry price, use absolute threshold)
          eventType = Math.abs(pnl) > 100 ? "big_win" : "trade_profit";
        } else {
          eventType = Math.abs(pnl) > 100 ? "big_loss" : "trade_loss";
        }
      }
    }

    if (eventType) {
      sm.play(eventType);
    }
  }, []);

  /**
   * Play a specific event sound directly.
   */
  const playEvent = useCallback((eventType: SoundEventType) => {
    getSoundManager().play(eventType);
  }, []);

  return { handleWsEvent, playEvent };
}
