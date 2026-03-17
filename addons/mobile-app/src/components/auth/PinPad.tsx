"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useHaptic } from "@/hooks/useHaptic";
import { PIN_LENGTH } from "@/lib/constants";

interface PinPadProps {
  onComplete: (pin: string) => void;
  error?: string | null;
  title: string;
  subtitle?: string;
  onAllDeleted?: () => void;
}

export function PinPad({
  onComplete,
  error,
  title,
  subtitle,
  onAllDeleted,
}: PinPadProps) {
  const [pin, setPin] = useState("");
  const [shake, setShake] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const haptic = useHaptic();

  const handlePress = useCallback(
    (digit: string) => {
      if (submitting) return;
      haptic("tick");
      setPin((prev) => {
        if (prev.length >= PIN_LENGTH) return prev;
        const next = prev + digit;
        if (next.length === PIN_LENGTH) {
          setSubmitting(true);
          setTimeout(() => {
            onComplete(next);
            setSubmitting(false);
          }, 200);
        }
        return next;
      });
    },
    [onComplete, haptic, submitting],
  );

  const handleDelete = useCallback(() => {
    if (submitting) return;
    haptic("light");
    setPin((prev) => {
      const next = prev.slice(0, -1);
      if (next.length === 0 && prev.length === 1 && onAllDeleted) {
        setTimeout(onAllDeleted, 50);
      }
      return next;
    });
  }, [haptic, submitting, onAllDeleted]);

  // Shake + clear on error
  const prevError = useRef(error);
  useEffect(() => {
    if (error && error !== prevError.current) {
      setShake(true);
      haptic("heavy");
      setTimeout(() => {
        setShake(false);
        setPin("");
      }, 500);
    }
    prevError.current = error;
  }, [error, haptic]);

  // Clear pin when title changes (transitioning between create/confirm)
  const prevTitle = useRef(title);
  useEffect(() => {
    if (title !== prevTitle.current) {
      setPin("");
      prevTitle.current = title;
    }
  }, [title]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "32px",
        width: "100%",
      }}
    >
      {/* Title */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", textAlign: "center" }}>
        <h2
          style={{
            fontSize: "22px",
            fontWeight: 600,
            color: "#d1d4dc",
            margin: 0,
            fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          }}
        >
          {title}
        </h2>
        {subtitle && (
          <p
            style={{
              fontSize: "14px",
              color: "#787b86",
              margin: 0,
              fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
            }}
          >
            {subtitle}
          </p>
        )}
      </div>

      {/* 4 PIN dots */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          animation: shake ? "shake 500ms ease-out" : undefined,
        }}
        role="status"
        aria-label={`${pin.length} of ${PIN_LENGTH} digits entered`}
      >
        {Array.from({ length: PIN_LENGTH }, (_, i) => {
          const filled = i < pin.length;
          const justFilled = i === pin.length - 1 && pin.length > 0;
          return (
            <div
              key={i}
              style={{
                width: "16px",
                height: "16px",
                borderRadius: "50%",
                backgroundColor: filled ? "#2962ff" : "transparent",
                border: filled ? "2px solid #2962ff" : "2px solid rgba(120,123,134,0.5)",
                transform: justFilled ? "scale(1.3)" : "scale(1)",
                transition: "all 150ms ease-out",
              }}
            />
          );
        })}
      </div>

      {/* Error */}
      {error && (
        <p
          style={{
            fontSize: "13px",
            fontWeight: 500,
            color: "#ef5350",
            margin: "-16px 0 0 0",
            fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          }}
        >
          {error}
        </p>
      )}

      {/* 3x4 Keypad */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 80px)",
          gap: "12px",
          justifyContent: "center",
        }}
      >
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "delete"].map(
          (key, i) => {
            if (key === "") {
              return <div key={i} style={{ width: "80px", height: "64px" }} />;
            }

            if (key === "delete") {
              return (
                <button
                  key={i}
                  onClick={handleDelete}
                  disabled={pin.length === 0 || submitting}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "80px",
                    height: "64px",
                    borderRadius: "16px",
                    border: "none",
                    backgroundColor: "transparent",
                    cursor: "pointer",
                    opacity: pin.length === 0 ? 0.3 : 1,
                    transition: "opacity 150ms",
                    WebkitTapHighlightColor: "transparent",
                  }}
                  aria-label="Delete last digit"
                >
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#d1d4dc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 4H8l-7 8 7 8h13a2 2 0 002-2V6a2 2 0 00-2-2z" />
                    <line x1="18" y1="9" x2="12" y2="15" />
                    <line x1="12" y1="9" x2="18" y2="15" />
                  </svg>
                </button>
              );
            }

            return (
              <KeyButton
                key={i}
                digit={key}
                onPress={handlePress}
                disabled={pin.length >= PIN_LENGTH || submitting}
              />
            );
          },
        )}
      </div>
    </div>
  );
}

function KeyButton({
  digit,
  onPress,
  disabled,
}: {
  digit: string;
  onPress: (digit: string) => void;
  disabled: boolean;
}) {
  const [pressed, setPressed] = useState(false);

  return (
    <button
      onClick={() => { if (!disabled) onPress(digit); }}
      onTouchStart={() => setPressed(true)}
      onTouchEnd={() => setPressed(false)}
      onTouchCancel={() => setPressed(false)}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: "80px",
        height: "64px",
        borderRadius: "16px",
        border: "1px solid rgba(42,46,57,0.5)",
        backgroundColor: pressed ? "rgba(41,98,255,0.15)" : "rgba(42,46,57,0.25)",
        cursor: "pointer",
        transform: pressed ? "scale(0.93)" : "scale(1)",
        transition: "transform 100ms ease-out, background-color 100ms ease-out",
        WebkitTapHighlightColor: "transparent",
        userSelect: "none",
      }}
      aria-label={`Digit ${digit}`}
    >
      <span
        style={{
          fontSize: "26px",
          fontWeight: 500,
          color: "#d1d4dc",
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          lineHeight: 1,
          pointerEvents: "none",
        }}
      >
        {digit}
      </span>
    </button>
  );
}
