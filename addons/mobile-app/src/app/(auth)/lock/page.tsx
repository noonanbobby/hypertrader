"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PinPad } from "@/components/auth/PinPad";
import { BiometricPrompt, isBiometricAvailable } from "@/components/auth/BiometricPrompt";
import { useAuth } from "@/hooks/useAuth";
import { storage, AUTH_KEYS } from "@/lib/storage";
import { Logo } from "@/components/ui/Logo";

export default function LockPage() {
  const router = useRouter();
  const { isSetup, isLocked, unlock, unlockBiometric, biometricsEnabled } = useAuth();
  const [mode, setMode] = useState<"biometric" | "pin">("pin");
  const [error, setError] = useState<string | null>(null);
  const [bioReady, setBioReady] = useState(false);

  useEffect(() => {
    if (!isSetup) {
      router.replace("/welcome");
      return;
    }
    if (!isLocked) {
      router.replace("/chart");
    }
  }, [isSetup, isLocked, router]);

  useEffect(() => {
    if (biometricsEnabled) {
      const credId = storage.get<string>(AUTH_KEYS.credentialId);
      if (credId) {
        isBiometricAvailable().then((available) => {
          if (available) {
            setBioReady(true);
            setMode("biometric");
          }
        });
      }
    }
  }, [biometricsEnabled]);

  // Auto-submit on 4th digit, shake on wrong PIN
  const handlePinComplete = useCallback(
    async (pin: string) => {
      setError(null);
      const success = await unlock(pin);
      if (success) {
        router.replace("/chart");
      } else {
        setError("Incorrect PIN");
      }
    },
    [unlock, router],
  );

  const handleBiometricSuccess = useCallback(() => {
    unlockBiometric();
    router.replace("/chart");
  }, [unlockBiometric, router]);

  const handleBiometricFallback = useCallback(() => {
    setMode("pin");
  }, []);

  if (!isSetup || !isLocked) return null;

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
        position: "relative",
      }}
    >
      {/* Background glow */}
      <div
        style={{
          position: "fixed",
          top: "30%",
          left: "50%",
          transform: "translateX(-50%)",
          width: "300px",
          height: "300px",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(41,98,255,0.06) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
        aria-hidden="true"
      />

      <div style={{ position: "relative", zIndex: 1, marginBottom: "8px" }}>
        <Logo size={56} />
      </div>

      <div style={{ position: "relative", zIndex: 1, width: "100%" }}>
        {mode === "biometric" && bioReady ? (
          <BiometricPrompt
            onSuccess={handleBiometricSuccess}
            onFallback={handleBiometricFallback}
          />
        ) : (
          <PinPad
            onComplete={handlePinComplete}
            error={error}
            title="Unlock HyperTrader"
            subtitle="Enter your PIN"
          />
        )}
      </div>
    </div>
  );
}
