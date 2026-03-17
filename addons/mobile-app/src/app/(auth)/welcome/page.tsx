"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { InstallPrompt } from "@/components/auth/InstallPrompt";
import { useAuth } from "@/hooks/useAuth";
import { Logo } from "@/components/ui/Logo";

export default function WelcomePage() {
  const router = useRouter();
  const { isSetup } = useAuth();
  const [showContent, setShowContent] = useState(false);
  const [logoVisible, setLogoVisible] = useState(false);
  const [textVisible, setTextVisible] = useState(false);

  useEffect(() => {
    if (isSetup) {
      router.replace("/lock");
      return;
    }
    const t1 = setTimeout(() => setLogoVisible(true), 100);
    const t2 = setTimeout(() => setTextVisible(true), 500);
    const t3 = setTimeout(() => setShowContent(true), 900);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [isSetup, router]);

  const handleContinue = () => {
    router.push("/pin-setup");
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "100%",
        maxWidth: "400px",
        padding: "0 24px",
        gap: "40px",
      }}
    >
      {/* Subtle background radial glow */}
      <div
        style={{
          position: "fixed",
          top: "20%",
          left: "50%",
          transform: "translateX(-50%)",
          width: "300px",
          height: "300px",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(41,98,255,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* Logo */}
      <div
        style={{
          opacity: logoVisible ? 1 : 0,
          transform: logoVisible ? "translateY(0) scale(1)" : "translateY(20px) scale(0.9)",
          transition: "all 700ms ease-out",
        }}
      >
        <Logo size={96} glow />
      </div>

      {/* Title & tagline */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "8px",
          opacity: textVisible ? 1 : 0,
          transform: textVisible ? "translateY(0)" : "translateY(16px)",
          transition: "all 700ms ease-out",
        }}
      >
        <h1
          style={{
            fontSize: "32px",
            fontWeight: 700,
            letterSpacing: "-0.5px",
            color: "#d1d4dc",
            margin: 0,
            fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          }}
        >
          HyperTrader
        </h1>
        <p
          style={{
            fontSize: "14px",
            color: "#787b86",
            margin: 0,
            fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
          }}
        >
          Automated BTC Trading Dashboard
        </p>
      </div>

      {/* Install prompt / Get started */}
      <div
        style={{
          width: "100%",
          opacity: showContent ? 1 : 0,
          transform: showContent ? "translateY(0)" : "translateY(12px)",
          transition: "all 500ms ease-out",
        }}
      >
        {showContent && <InstallPrompt onContinue={handleContinue} />}
      </div>
    </div>
  );
}
