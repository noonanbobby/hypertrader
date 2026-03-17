"use client";

import { useCallback, useState } from "react";
import { storage, AUTH_KEYS } from "@/lib/storage";

interface BiometricPromptProps {
  onSuccess: () => void;
  onFallback: () => void;
}

export function BiometricPrompt({ onSuccess, onFallback }: BiometricPromptProps) {
  const [authenticating, setAuthenticating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authenticate = useCallback(async () => {
    setAuthenticating(true);
    setError(null);

    try {
      const credentialIdB64 = storage.get<string>(AUTH_KEYS.credentialId);
      if (!credentialIdB64) {
        onFallback();
        return;
      }

      const credentialId = Uint8Array.from(atob(credentialIdB64), (c) => c.charCodeAt(0));

      const assertion = await navigator.credentials.get({
        publicKey: {
          challenge: crypto.getRandomValues(new Uint8Array(32)),
          rpId: window.location.hostname,
          allowCredentials: [
            {
              type: "public-key",
              id: credentialId,
              transports: ["internal"],
            },
          ],
          userVerification: "required",
          timeout: 60000,
        },
      });

      if (assertion) {
        onSuccess();
      } else {
        setError("Authentication failed");
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        setError("Authentication cancelled");
      } else {
        onFallback();
      }
    } finally {
      setAuthenticating(false);
    }
  }, [onSuccess, onFallback]);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "24px" }}>
      <button
        onClick={authenticate}
        disabled={authenticating}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "72px",
          height: "72px",
          borderRadius: "50%",
          border: "2px solid rgba(41,98,255,0.3)",
          backgroundColor: "rgba(41,98,255,0.15)",
          cursor: "pointer",
          opacity: authenticating ? 0.5 : 1,
          WebkitTapHighlightColor: "transparent",
        }}
        aria-label="Authenticate with biometrics"
      >
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2962ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 10a2 2 0 00-2 2c0 1.02.1 2.51.4 4" />
          <path d="M8.65 22c.21-.66.45-1.32.57-2 .18-.98.29-2 .29-3v-1a4 4 0 018 0" />
          <path d="M6.53 18c.33-2 .53-4 .53-6v-1a6 6 0 0112 0v4" />
          <path d="M4.34 15a10 10 0 01-.34-2.53V11a8 8 0 0116 0v.5" />
          <path d="M2 12.53A12 12 0 0114 2" />
        </svg>
      </button>

      {error && (
        <p style={{ fontSize: "13px", color: "#ef5350", margin: 0, fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif" }}>
          {error}
        </p>
      )}

      <button
        onClick={onFallback}
        style={{
          fontSize: "13px",
          fontWeight: 500,
          color: "#787b86",
          border: "none",
          backgroundColor: "transparent",
          cursor: "pointer",
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          WebkitTapHighlightColor: "transparent",
        }}
      >
        Use PIN instead
      </button>
    </div>
  );
}

export async function registerBiometric(): Promise<boolean> {
  try {
    if (!window.PublicKeyCredential) return false;
    const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
    if (!available) return false;

    const credential = await navigator.credentials.create({
      publicKey: {
        challenge: crypto.getRandomValues(new Uint8Array(32)),
        rp: { name: "HyperTrader", id: window.location.hostname },
        user: {
          id: new Uint8Array(16),
          name: "hypertrader-user",
          displayName: "HyperTrader User",
        },
        pubKeyCredParams: [
          { type: "public-key", alg: -7 },
          { type: "public-key", alg: -257 },
        ],
        authenticatorSelection: {
          authenticatorAttachment: "platform",
          userVerification: "required",
          residentKey: "preferred",
        },
        timeout: 60000,
        attestation: "none",
      },
    });

    if (credential && "rawId" in credential) {
      const rawId = new Uint8Array((credential as PublicKeyCredential).rawId);
      const b64 = btoa(String.fromCharCode(...rawId));
      storage.set(AUTH_KEYS.credentialId, b64);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

export async function isBiometricAvailable(): Promise<boolean> {
  try {
    if (!window.PublicKeyCredential) return false;
    return PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}
