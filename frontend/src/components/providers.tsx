"use client";

import { useEffect, ReactNode } from "react";
import { Toaster } from "sonner";
import { useSessionStore } from "@/store/sessionStore";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const preferences = useSessionStore((s) => s.preferences);

  useEffect(() => {
    if (!preferences) return;
    if (typeof document === "undefined") return;

    // Light theme is the default — do NOT force dark class globally.
    // The .dark class is only applied to specific elements (e.g. welcome right panel).
    document.documentElement.classList.remove("dark");
    document.documentElement.classList.remove("light");

    // Apply reduced-motion preference.
    document.documentElement.classList.toggle(
      "reduced-motion",
      !!preferences.reducedMotion
    );

    // Map the named font-size preference to a real root px value.
    const FONT_SIZE_PX: Record<string, number> = { small: 13, normal: 15, large: 17 };
    const px = FONT_SIZE_PX[preferences.fontSize] ?? FONT_SIZE_PX.normal;
    document.documentElement.style.fontSize = `${px}px`;
  }, [preferences]);

  return (
    <>
      {children}
      <Toaster theme="light" position="bottom-right" />
    </>
  );
}
