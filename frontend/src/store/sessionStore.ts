import { create } from "zustand";
import { persist } from "zustand/middleware";
import { setAuthToken } from "@/lib/api_sessions";

// ── Type Definitions ───────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  name: string;
  learning_profile?: Record<string, any>;
  mastery_scores?: Record<string, number>;
  created_at?: string;
}

export interface UserPreferences {
  reducedMotion: boolean;
  fontSize: "small" | "normal" | "large";
}

export interface SessionStoreState {
  user: User | null;
  preferences: UserPreferences;
  agreedToTerms: boolean;
  /** True once the persisted store has rehydrated from localStorage on the
   *  client. Routes must wait for this before redirecting on `user`, otherwise
   *  the first render (user === null, pre-hydration) bounces logged-in users to
   *  /welcome. */
  hasHydrated: boolean;

  setUser: (user: User | null) => void;
  setAgreedToTerms: (v: boolean) => void;
  logout: () => void;
  setHasHydrated: (v: boolean) => void;
}

// ── Store Implementation ───────────────────────────────────────

export const useSessionStore = create<SessionStoreState>()(
  persist(
    (set) => ({
      user: null,
      preferences: { reducedMotion: false, fontSize: "normal" },
      agreedToTerms: false,
      hasHydrated: false,

      setUser: (user) => {
        if (!user || !user.id || !user.email || !user.name) {
          set({ user: null });
          return;
        }
        set({ user });
      },
      setAgreedToTerms: (v) => set({ agreedToTerms: v }),
      logout: () => {
        // Drop the persisted JWT alongside the user so a signed-out session
        // can't be resurrected by getCurrentUser() on a shared machine.
        setAuthToken(null);
        set({ user: null, agreedToTerms: false });
      },
      setHasHydrated: (v) => set({ hasHydrated: v }),
    }),
    {
      name: "Sarasvi-session-store",
      // Only persist durable identity/preferences — never the hydration flag.
      partialize: (s) => ({ user: s.user, preferences: s.preferences, agreedToTerms: s.agreedToTerms }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);
