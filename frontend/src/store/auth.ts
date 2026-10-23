import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { api, ApiError } from "../api/client";
import { hasAction } from "../lib/permissions";
import type { ActionName, LoginResponse, ResourceName, UserProfile } from "../types";

interface AuthState {
  token: string | null;
  profile: UserProfile | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  /** Re-read permissions from the server (they may change while a session is open). */
  refreshProfile: () => Promise<void>;
  can: (resource: ResourceName, action: ActionName) => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      profile: null,
      loading: false,
      error: null,

      async login(email, password) {
        set({ loading: true, error: null });
        try {
          const res = await api<LoginResponse>("/auth/login", { method: "POST", body: { email, password } });
          set({ token: res.access_token, profile: res.profile, loading: false });
          return true;
        } catch (err) {
          set({ loading: false, error: err instanceof ApiError ? err.message : "Unable to sign in" });
          return false;
        }
      },

      logout() {
        set({ token: null, profile: null, error: null });
      },

      async refreshProfile() {
        if (!get().token) return;
        try {
          set({ profile: await api<UserProfile>("/auth/me") });
        } catch {
          /* a 401 already triggers logout via the client handler */
        }
      },

      can: (resource, action) => hasAction(get().profile, resource, action),
    }),
    {
      name: "omnidata.auth",
      // sessionStorage: the session ends with the tab, limiting token exposure.
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ token: state.token, profile: state.profile }),
    },
  ),
);
