"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { PinPad } from "@/components/auth/PinPad";
import { useAuth } from "@/hooks/useAuth";
import {
  isBiometricAvailable,
  registerBiometric,
} from "@/components/auth/BiometricPrompt";
import { useHaptic } from "@/hooks/useHaptic";
import { Logo } from "@/components/ui/Logo";

type Step = "create" | "confirm" | "biometric";

export default function PinSetupPage() {
  const router = useRouter();
  const { setupPin, setBiometrics } = useAuth();
  const haptic = useHaptic();

  const [step, setStep] = useState<Step>("create");
  const [firstPin, setFirstPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [bioAvailable, setBioAvailable] = useState(false);
  const [settingUpBio, setSettingUpBio] = useState(false);

  // Step 1: user enters 4 digits → auto-advance to confirm
  const handleCreatePin = useCallback((pin: string) => {
    setFirstPin(pin);
    setError(null);
    setStep("confirm");
  }, []);

  // Step 2: user re-enters 4 digits → match check → proceed
  const handleConfirmPin = useCallback(
    async (pin: string) => {
      if (pin !== firstPin) {
        // Mismatch: shake, clear, stay on confirm screen
        haptic("heavy");
        setError("PINs didn't match — try again");
        return;
      }
      // Match: save PIN and proceed
      await setupPin(pin);
      haptic("medium");
      const available = await isBiometricAvailable();
      if (available) {
        setBioAvailable(true);
        setStep("biometric");
      } else {
        router.replace("/chart");
      }
    },
    [firstPin, setupPin, router, haptic],
  );

  // If user deletes all digits on confirm screen, go back to create
  const handleAllDeletedOnConfirm = useCallback(() => {
    setError(null);
    setFirstPin("");
    setStep("create");
  }, []);

  const handleEnableBiometrics = useCallback(async () => {
    setSettingUpBio(true);
    const success = await registerBiometric();
    if (success) {
      setBiometrics(true);
      haptic("medium");
    }
    setSettingUpBio(false);
    router.replace("/chart");
  }, [setBiometrics, router, haptic]);

  const handleSkipBiometrics = useCallback(() => {
    router.replace("/chart");
  }, [router]);

  // Biometric enrollment step
  if (step === "biometric" && bioAvailable) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "32px",
          width: "100%",
          maxWidth: "400px",
          padding: "0 24px",
        }}
      >
        <div style={{ position: "relative" }}>
          <div
            style={{
              position: "absolute",
              inset: "-16px",
              borderRadius: "50%",
              backgroundColor: "#2962ff",
              opacity: 0.15,
              filter: "blur(16px)",
            }}
          />
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "80px",
              height: "80px",
              borderRadius: "50%",
              backgroundColor: "rgba(41,98,255,0.15)",
              border: "2px solid rgba(41,98,255,0.3)",
            }}
          >
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#2962ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 10a2 2 0 00-2 2c0 1.02.1 2.51.4 4" />
              <path d="M8.65 22c.21-.66.45-1.32.57-2 .18-.98.29-2 .29-3v-1a4 4 0 018 0" />
              <path d="M6.53 18c.33-2 .53-4 .53-6v-1a6 6 0 0112 0v4" />
              <path d="M4.34 15a10 10 0 01-.34-2.53V11a8 8 0 0116 0v.5" />
              <path d="M2 12.53A12 12 0 0114 2" />
            </svg>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", textAlign: "center" }}>
          <h2 style={{ fontSize: "22px", fontWeight: 600, color: "#d1d4dc", margin: 0, fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif" }}>
            Enable Biometric Unlock
          </h2>
          <p style={{ fontSize: "14px", color: "#787b86", margin: 0, fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif" }}>
            Use Face ID or fingerprint for quick access
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "12px", width: "100%", maxWidth: "300px" }}>
          <button
            onClick={handleEnableBiometrics}
            disabled={settingUpBio}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "52px",
              borderRadius: "14px",
              border: "none",
              backgroundColor: "#2962ff",
              color: "#fff",
              fontSize: "16px",
              fontWeight: 600,
              fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
              cursor: "pointer",
              opacity: settingUpBio ? 0.5 : 1,
              WebkitTapHighlightColor: "transparent",
            }}
          >
            {settingUpBio ? "Setting up..." : "Enable Biometrics"}
          </button>
          <button
            onClick={handleSkipBiometrics}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "48px",
              borderRadius: "14px",
              border: "none",
              backgroundColor: "transparent",
              color: "#787b86",
              fontSize: "14px",
              fontWeight: 500,
              fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
              cursor: "pointer",
              WebkitTapHighlightColor: "transparent",
            }}
          >
            Skip for now
          </button>
        </div>
      </div>
    );
  }

  // Create / Confirm PIN screen
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "24px",
        width: "100%",
        maxWidth: "400px",
        padding: "0 24px",
      }}
    >
      <Logo size={56} />
      <PinPad
        onComplete={step === "create" ? handleCreatePin : handleConfirmPin}
        error={error}
        title={step === "create" ? "Create a PIN" : "Confirm your PIN"}
        subtitle={
          step === "create"
            ? "Choose a 4-digit PIN to secure your app"
            : "Enter the same PIN again"
        }
        onAllDeleted={step === "confirm" ? handleAllDeletedOnConfirm : undefined}
      />
    </div>
  );
}
