"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { Logo } from "@/components/ui/Logo";

export default function RootPage() {
  const router = useRouter();
  const { isSetup, isLocked } = useAuth();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (!isSetup) {
      router.replace("/welcome");
    } else if (isLocked) {
      router.replace("/lock");
    } else {
      router.replace("/chart");
    }
  }, [mounted, isSetup, isLocked, router]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100dvh",
        backgroundColor: "#131722",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "16px" }}>
        <Logo size={80} glow />
        <div style={{ display: "flex", gap: "6px" }}>
          {[0, 200, 400].map((delay) => (
            <span
              key={delay}
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                backgroundColor: "#787b86",
                animation: "pulseSubtle 2s ease-in-out infinite",
                animationDelay: `${delay}ms`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
