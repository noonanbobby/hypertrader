"use client";

import { useCallback, useRef, useState } from "react";
import { useHaptic } from "@/hooks/useHaptic";

interface SlideToConfirmProps {
  onConfirm: () => void;
  label?: string;
  confirmLabel?: string;
  variant?: "danger" | "default";
  disabled?: boolean;
}

export function SlideToConfirm({
  onConfirm,
  label = "Slide to confirm",
  confirmLabel = "Confirmed",
  variant = "danger",
  disabled = false,
}: SlideToConfirmProps) {
  const haptic = useHaptic();
  const trackRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const dragRef = useRef({ startX: 0, dragging: false });

  const trackWidth = trackRef.current?.offsetWidth ?? 300;
  const thumbSize = 52;
  const maxOffset = trackWidth - thumbSize - 8; // 4px padding each side
  const progress = maxOffset > 0 ? offset / maxOffset : 0;

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (disabled || confirmed) return;
    dragRef.current.startX = e.touches[0].clientX - offset;
    dragRef.current.dragging = true;
  }, [disabled, confirmed, offset]);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!dragRef.current.dragging) return;
    const x = e.touches[0].clientX - dragRef.current.startX;
    setOffset(Math.max(0, Math.min(x, maxOffset)));
  }, [maxOffset]);

  const handleTouchEnd = useCallback(() => {
    dragRef.current.dragging = false;
    if (progress >= 0.9) {
      setOffset(maxOffset);
      setConfirmed(true);
      haptic("heavy");
      onConfirm();
    } else {
      setOffset(0);
    }
  }, [progress, maxOffset, haptic, onConfirm]);

  const bgColor = variant === "danger" ? "#ef5350" : "#2962ff";
  const bgFill = variant === "danger" ? "rgba(239,83,80,0.15)" : "rgba(41,98,255,0.15)";

  return (
    <div
      ref={trackRef}
      className="relative flex h-[60px] w-full items-center overflow-hidden rounded-full"
      style={{
        backgroundColor: bgFill,
        border: `1px solid ${variant === "danger" ? "rgba(239,83,80,0.3)" : "rgba(41,98,255,0.3)"}`,
      }}
    >
      {/* Progress fill */}
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{
          width: `${(offset + thumbSize + 8)}px`,
          backgroundColor: bgColor,
          opacity: 0.2,
          transition: dragRef.current.dragging ? "none" : "width 300ms ease-out",
        }}
      />

      {/* Label */}
      <span
        className="absolute inset-0 flex items-center justify-center text-sm font-medium select-none"
        style={{
          color: confirmed ? "#fff" : variant === "danger" ? "#ef5350" : "#2962ff",
          opacity: confirmed ? 1 : 1 - progress * 0.5,
          transition: "opacity 200ms",
        }}
      >
        {confirmed ? confirmLabel : label}
      </span>

      {/* Thumb */}
      <div
        className="relative z-10 flex items-center justify-center rounded-full"
        style={{
          width: `${thumbSize}px`,
          height: `${thumbSize - 8}px`,
          marginLeft: "4px",
          backgroundColor: bgColor,
          transform: `translateX(${offset}px)`,
          transition: dragRef.current.dragging ? "none" : "transform 300ms ease-out",
          opacity: confirmed ? 0 : 1,
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        role="slider"
        aria-label={label}
        aria-valuenow={Math.round(progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        tabIndex={0}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#fff"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </div>
    </div>
  );
}
