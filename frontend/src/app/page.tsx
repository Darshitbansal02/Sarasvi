"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSessionStore } from "@/store/sessionStore";

export default function Home() {
  const router = useRouter();
  const user = useSessionStore((s) => s.user);
  const hasHydrated = useSessionStore((s) => s.hasHydrated);

  useEffect(() => {
    // Wait until the persisted store has rehydrated, otherwise a refresh sees
    // user === null pre-hydration and bounces logged-in users to /welcome.
    if (!hasHydrated) return;
    if (user) {
      router.replace("/dashboard");
    } else {
      router.replace("/welcome");
    }
  }, [user, hasHydrated, router]);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="animate-pulse label-mono">initializing Sarasvi…</div>
    </div>
  );
}
