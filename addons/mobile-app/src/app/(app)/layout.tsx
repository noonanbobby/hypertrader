"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BottomNav } from "@/components/ui/BottomNav";
import { OfflineBanner } from "@/components/ui/OfflineBanner";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useAuth } from "@/hooks/useAuth";
import { useInactivityLock } from "@/hooks/useInactivityLock";

function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { isSetup, isLocked } = useAuth();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isSetup) {
      router.replace("/welcome");
    } else if (isLocked) {
      router.replace("/lock");
    } else {
      setReady(true);
    }
  }, [isSetup, isLocked, router]);

  if (!ready) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100dvh", backgroundColor: "#131722" }}>
        <div style={{ width: "32px", height: "32px", borderRadius: "50%", border: "2px solid #2962ff", borderTopColor: "transparent", animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  return <>{children}</>;
}

function InactivityLockProvider({ children }: { children: React.ReactNode }) {
  useInactivityLock();
  return <>{children}</>;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <InactivityLockProvider>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            height: "100dvh",
            backgroundColor: "#131722",
            overflow: "hidden",
            paddingTop: "env(safe-area-inset-top, 0px)",
          }}
        >
          <OfflineBanner />
          <ErrorBoundary>
            <main className="app-main">
              {children}
            </main>
          </ErrorBoundary>
          <BottomNav />
        </div>
      </InactivityLockProvider>
    </AuthGuard>
  );
}
