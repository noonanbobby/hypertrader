"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { hashPin, verifyPin } from "@/lib/crypto";
import { storage, AUTH_KEYS } from "@/lib/storage";

interface AuthStore {
  isSetup: boolean;
  isLocked: boolean;
  pinHash: string | null;
  biometricsEnabled: boolean;
  autoLockMinutes: number;
}

const listeners = new Set<() => void>();
let currentState: AuthStore = {
  isSetup: false,
  isLocked: true,
  pinHash: null,
  biometricsEnabled: false,
  autoLockMinutes: 5,
};

function loadFromStorage(): AuthStore {
  return {
    isSetup: storage.get<boolean>(AUTH_KEYS.isSetup) ?? false,
    isLocked: true,
    pinHash: storage.get<string>(AUTH_KEYS.pinHash),
    biometricsEnabled: storage.get<boolean>(AUTH_KEYS.biometricsEnabled) ?? false,
    autoLockMinutes: storage.get<number>(AUTH_KEYS.autoLockMinutes) ?? 5,
  };
}

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): AuthStore {
  return currentState;
}

const SERVER_SNAPSHOT: AuthStore = {
  isSetup: false,
  isLocked: true,
  pinHash: null,
  biometricsEnabled: false,
  autoLockMinutes: 5,
};

function getServerSnapshot(): AuthStore {
  return SERVER_SNAPSHOT;
}

let initialized = false;

export function useAuth() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!initialized && typeof window !== "undefined") {
      initialized = true;
      currentState = loadFromStorage();
      emit();
    }
  }, []);

  const setupPin = useCallback(async (pin: string) => {
    setError(null);
    const hash = await hashPin(pin);
    storage.set(AUTH_KEYS.pinHash, hash);
    storage.set(AUTH_KEYS.isSetup, true);
    currentState = {
      ...currentState,
      isSetup: true,
      isLocked: false,
      pinHash: hash,
    };
    emit();
  }, []);

  const unlock = useCallback(async (pin: string): Promise<boolean> => {
    setError(null);
    const storedHash = storage.get<string>(AUTH_KEYS.pinHash);
    if (!storedHash) {
      setError("No PIN configured");
      return false;
    }
    const valid = await verifyPin(pin, storedHash);
    if (!valid) {
      setError("Incorrect PIN");
      return false;
    }
    storage.set(AUTH_KEYS.lastActivity, Date.now());
    currentState = { ...currentState, isLocked: false };
    emit();
    return true;
  }, []);

  const lock = useCallback(() => {
    currentState = { ...currentState, isLocked: true };
    emit();
  }, []);

  const unlockBiometric = useCallback(() => {
    storage.set(AUTH_KEYS.lastActivity, Date.now());
    currentState = { ...currentState, isLocked: false };
    emit();
  }, []);

  const changePin = useCallback(async (currentPin: string, newPin: string): Promise<boolean> => {
    const storedHash = storage.get<string>(AUTH_KEYS.pinHash);
    if (!storedHash) return false;
    const valid = await verifyPin(currentPin, storedHash);
    if (!valid) {
      setError("Current PIN is incorrect");
      return false;
    }
    const hash = await hashPin(newPin);
    storage.set(AUTH_KEYS.pinHash, hash);
    currentState = { ...currentState, pinHash: hash };
    emit();
    return true;
  }, []);

  const setBiometrics = useCallback((enabled: boolean) => {
    storage.set(AUTH_KEYS.biometricsEnabled, enabled);
    currentState = { ...currentState, biometricsEnabled: enabled };
    emit();
  }, []);

  const setAutoLockMinutes = useCallback((minutes: number) => {
    storage.set(AUTH_KEYS.autoLockMinutes, minutes);
    currentState = { ...currentState, autoLockMinutes: minutes };
    emit();
  }, []);

  const recordActivity = useCallback(() => {
    storage.set(AUTH_KEYS.lastActivity, Date.now());
  }, []);

  return useMemo(
    () => ({
      ...state,
      error,
      setupPin,
      unlock,
      unlockBiometric,
      lock,
      changePin,
      setBiometrics,
      setAutoLockMinutes,
      recordActivity,
    }),
    [state, error, setupPin, unlock, unlockBiometric, lock, changePin, setBiometrics, setAutoLockMinutes, recordActivity],
  );
}
