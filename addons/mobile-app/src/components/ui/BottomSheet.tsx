"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useHaptic } from "@/hooks/useHaptic";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  snapPoints?: number[];
}

export function BottomSheet({
  open,
  onClose,
  title,
  children,
  snapPoints = [0.5],
}: BottomSheetProps) {
  const haptic = useHaptic();
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ startY: 0, currentY: 0, isDragging: false });
  const [translateY, setTranslateY] = useState(0);
  const [isVisible, setIsVisible] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);

  useEffect(() => {
    if (open) {
      setIsVisible(true);
      haptic("light");
      requestAnimationFrame(() => {
        setIsAnimating(true);
      });
    } else {
      setIsAnimating(false);
      const timer = setTimeout(() => setIsVisible(false), 300);
      return () => clearTimeout(timer);
    }
  }, [open, haptic]);

  // Prevent body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = "";
      };
    }
  }, [open]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    dragRef.current.startY = e.touches[0].clientY;
    dragRef.current.isDragging = true;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!dragRef.current.isDragging) return;
    const deltaY = e.touches[0].clientY - dragRef.current.startY;
    if (deltaY > 0) {
      setTranslateY(deltaY);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    dragRef.current.isDragging = false;
    if (translateY > 100) {
      onClose();
    }
    setTranslateY(0);
  }, [translateY, onClose]);

  if (!isVisible) return null;

  const maxHeight = `${Math.max(...snapPoints) * 100}vh`;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 transition-opacity duration-300"
        style={{
          backgroundColor: "rgba(0,0,0,0.5)",
          opacity: isAnimating ? 1 : 0,
        }}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? "Bottom sheet"}
        className="fixed bottom-0 left-0 right-0 z-50 flex flex-col overflow-hidden safe-bottom"
        style={{
          maxHeight,
          backgroundColor: "#1e222d",
          borderTopLeftRadius: "20px",
          borderTopRightRadius: "20px",
          boxShadow: "0 -4px 30px rgba(0,0,0,0.5)",
          transform: isAnimating ? `translateY(${translateY}px)` : "translateY(100%)",
          transition: dragRef.current.isDragging ? "none" : "transform 300ms cubic-bezier(0.32, 0.72, 0, 1)",
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle */}
        <div className="flex justify-center py-3">
          <div
            className="h-1 w-9 rounded-full"
            style={{ backgroundColor: "rgba(120,123,134,0.4)" }}
          />
        </div>

        {/* Title */}
        {title && (
          <div
            className="border-b px-4 pb-3"
            style={{ borderColor: "rgba(42,46,57,0.5)" }}
          >
            <h3 className="text-base font-semibold" style={{ color: "#d1d4dc" }}>
              {title}
            </h3>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-3">
          {children}
        </div>
      </div>
    </>
  );
}
