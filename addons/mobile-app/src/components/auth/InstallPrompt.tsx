"use client";

import { useEffect } from "react";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";

interface InstallPromptProps {
  onContinue: () => void;
}

export function InstallPrompt({ onContinue }: InstallPromptProps) {
  const { canInstall, isIOS, isStandalone, promptInstall } = useInstallPrompt();

  // If already installed as PWA, redirect via effect (never during render)
  useEffect(() => {
    if (isStandalone) {
      onContinue();
    }
  }, [isStandalone, onContinue]);

  const handleInstall = async () => {
    if (canInstall) {
      await promptInstall();
    }
    onContinue();
  };

  if (isStandalone) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "20px",
        textAlign: "center",
        width: "100%",
      }}
    >
      {/* Android / Chrome install */}
      {canInstall && (
        <>
          <p style={{ fontSize: "14px", color: "#787b86", margin: 0 }}>
            Install HyperTrader for the best experience
          </p>
          <PrimaryButton onClick={handleInstall}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Install HyperTrader
          </PrimaryButton>
          <SecondaryButton onClick={onContinue}>
            Continue in browser
          </SecondaryButton>
        </>
      )}

      {/* iOS Safari */}
      {isIOS && !canInstall && (
        <>
          <p style={{ fontSize: "14px", color: "#787b86", margin: 0 }}>
            Add HyperTrader to your Home Screen
          </p>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "0",
              width: "100%",
              borderRadius: "16px",
              backgroundColor: "#1e222d",
              border: "1px solid rgba(42,46,57,0.6)",
              boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
              textAlign: "left",
              overflow: "hidden",
            }}
          >
            <IOSStep
              step={1}
              icon={
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2962ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8" />
                  <polyline points="16 6 12 2 8 6" />
                  <line x1="12" y1="2" x2="12" y2="15" />
                </svg>
              }
              action="Share"
              detail="Tap the Share button in Safari"
            />
            <div style={{ height: "1px", backgroundColor: "rgba(42,46,57,0.4)", margin: "0 16px" }} />
            <IOSStep
              step={2}
              icon={
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2962ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <line x1="12" y1="8" x2="12" y2="16" />
                  <line x1="8" y1="12" x2="16" y2="12" />
                </svg>
              }
              action="Add to Home Screen"
              detail="Scroll down in the share sheet"
            />
            <div style={{ height: "1px", backgroundColor: "rgba(42,46,57,0.4)", margin: "0 16px" }} />
            <IOSStep
              step={3}
              icon={
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#26a69a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              }
              action="Add"
              detail="Tap Add in the top-right corner"
            />
          </div>

          <SecondaryButton onClick={onContinue}>
            Continue in browser
          </SecondaryButton>
        </>
      )}

      {/* Fallback */}
      {!canInstall && !isIOS && (
        <PrimaryButton onClick={onContinue}>
          Get Started
        </PrimaryButton>
      )}
    </div>
  );
}

function PrimaryButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "8px",
        height: "52px",
        width: "100%",
        maxWidth: "300px",
        borderRadius: "14px",
        border: "none",
        backgroundColor: "#2962ff",
        color: "#ffffff",
        fontSize: "16px",
        fontWeight: 600,
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        cursor: "pointer",
        WebkitTapHighlightColor: "transparent",
      }}
    >
      {children}
    </button>
  );
}

function SecondaryButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "48px",
        width: "100%",
        maxWidth: "300px",
        borderRadius: "14px",
        border: "1px solid rgba(42,46,57,0.6)",
        backgroundColor: "transparent",
        color: "#787b86",
        fontSize: "14px",
        fontWeight: 500,
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        cursor: "pointer",
        WebkitTapHighlightColor: "transparent",
        marginTop: "4px",
      }}
    >
      {children}
    </button>
  );
}

function IOSStep({ step, icon, action, detail }: { step: number; icon: React.ReactNode; action: string; detail: string }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: "14px", padding: "16px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "28px",
          height: "28px",
          minWidth: "28px",
          borderRadius: "50%",
          backgroundColor: "rgba(41,98,255,0.12)",
          color: "#2962ff",
          fontSize: "13px",
          fontWeight: 700,
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        }}
      >
        {step}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "3px", paddingTop: "2px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {icon}
          <span style={{ fontSize: "15px", fontWeight: 600, color: "#d1d4dc", fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif" }}>
            {action}
          </span>
        </div>
        <p style={{ fontSize: "13px", color: "#787b86", margin: 0, lineHeight: 1.4, fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif" }}>
          {detail}
        </p>
      </div>
    </div>
  );
}
