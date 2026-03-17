const STORAGE_PREFIX = "ht-";

export const storage = {
  get<T>(key: string): T | null {
    if (typeof window === "undefined") return null;
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + key);
      if (raw === null) return null;
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  },

  set<T>(key: string, value: T): void {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage full or unavailable — silently fail
    }
  },

  remove(key: string): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(STORAGE_PREFIX + key);
  },

  has(key: string): boolean {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(STORAGE_PREFIX + key) !== null;
  },
} as const;

// Auth-specific storage keys
export const AUTH_KEYS = {
  pinHash: "pin-hash",
  biometricsEnabled: "biometrics-enabled",
  autoLockMinutes: "auto-lock-minutes",
  isSetup: "is-setup",
  lastActivity: "last-activity",
  credentialId: "webauthn-credential-id",
} as const;
