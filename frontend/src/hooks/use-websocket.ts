"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { WS_URL } from "@/lib/constants";
import type { WSEvent } from "@/types";

type EventHandler = (data: Record<string, unknown>) => void;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef<Map<string, Set<EventHandler>>>(new Map());
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSEvent = JSON.parse(event.data);
        const handlers = handlersRef.current.get(msg.event);
        if (handlers) {
          handlers.forEach((handler) => handler(msg.data));
        }
      } catch {
        // ignore malformed messages
      }
    };

    wsRef.current = ws;
  }, []);

  const subscribe = useCallback((event: string, handler: EventHandler) => {
    if (!handlersRef.current.has(event)) {
      handlersRef.current.set(event, new Set());
    }
    handlersRef.current.get(event)!.add(handler);

    return () => {
      handlersRef.current.get(event)?.delete(handler);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, subscribe };
}
