/**
 * SoundManager — singleton for audio playback and haptic feedback.
 * Uses Web Audio API for low-latency sound, navigator.vibrate for haptics.
 */

import {
  generateAllSounds,
  SOUND_EVENTS,
  type SoundEventType,
  type SoundName,
} from "./sound-generator";
import { storage } from "./storage";

const STORAGE_KEYS = {
  volume: "sound-volume",
  muted: "sound-muted",
  selections: "sound-selections",
  eventMuted: "sound-event-muted",
  vibrationEnabled: "sound-vibration-enabled",
} as const;

export interface SoundPreferences {
  volume: number;
  muted: boolean;
  selections: Record<SoundEventType, SoundName>;
  eventMuted: Record<SoundEventType, boolean>;
  vibrationEnabled: Record<SoundEventType, boolean>;
}

function getDefaultSelections(): Record<SoundEventType, SoundName> {
  const result: Partial<Record<SoundEventType, SoundName>> = {};
  for (const event of SOUND_EVENTS) {
    result[event.type] = event.defaultSound;
  }
  return result as Record<SoundEventType, SoundName>;
}

function getDefaultEventMuted(): Record<SoundEventType, boolean> {
  const result: Partial<Record<SoundEventType, boolean>> = {};
  for (const event of SOUND_EVENTS) {
    result[event.type] = false;
  }
  return result as Record<SoundEventType, boolean>;
}

function getDefaultVibrationEnabled(): Record<SoundEventType, boolean> {
  const result: Partial<Record<SoundEventType, boolean>> = {};
  for (const event of SOUND_EVENTS) {
    result[event.type] = true;
  }
  return result as Record<SoundEventType, boolean>;
}

class SoundManager {
  private ctx: AudioContext | null = null;
  private buffers: Map<SoundName, AudioBuffer> = new Map();
  private gainNode: GainNode | null = null;
  private initialized = false;
  private initializing: Promise<void> | null = null;

  private prefs: SoundPreferences = {
    volume: 80,
    muted: false,
    selections: getDefaultSelections(),
    eventMuted: getDefaultEventMuted(),
    vibrationEnabled: getDefaultVibrationEnabled(),
  };

  constructor() {
    this.loadPreferences();
  }

  private loadPreferences(): void {
    this.prefs.volume = storage.get<number>(STORAGE_KEYS.volume) ?? 80;
    this.prefs.muted = storage.get<boolean>(STORAGE_KEYS.muted) ?? false;
    this.prefs.selections = {
      ...getDefaultSelections(),
      ...(storage.get<Record<SoundEventType, SoundName>>(STORAGE_KEYS.selections) ?? {}),
    };
    this.prefs.eventMuted = {
      ...getDefaultEventMuted(),
      ...(storage.get<Record<SoundEventType, boolean>>(STORAGE_KEYS.eventMuted) ?? {}),
    };
    this.prefs.vibrationEnabled = {
      ...getDefaultVibrationEnabled(),
      ...(storage.get<Record<SoundEventType, boolean>>(STORAGE_KEYS.vibrationEnabled) ?? {}),
    };
  }

  /**
   * Initialize the audio context and preload all sounds.
   * Must be called from a user gesture on iOS.
   */
  async init(): Promise<void> {
    if (this.initialized) return;
    if (this.initializing) return this.initializing;

    this.initializing = this._doInit();
    return this.initializing;
  }

  private async _doInit(): Promise<void> {
    try {
      this.ctx = new AudioContext();

      // iOS unlock — resume on user gesture
      if (this.ctx.state === "suspended") {
        await this.ctx.resume();
      }

      this.gainNode = this.ctx.createGain();
      this.gainNode.gain.value = this.prefs.muted ? 0 : this.prefs.volume / 100;
      this.gainNode.connect(this.ctx.destination);

      // Generate all sound buffers
      this.buffers = await generateAllSounds(this.ctx.sampleRate);
      this.initialized = true;
    } catch (e) {
      console.error("SoundManager init failed:", e);
    }
  }

  /**
   * Ensure audio context is running (call on user gesture).
   */
  async unlock(): Promise<void> {
    if (!this.ctx) {
      await this.init();
      return;
    }
    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }
  }

  getPreferences(): SoundPreferences {
    return { ...this.prefs };
  }

  /**
   * Play a sound for a given event type.
   */
  async play(eventType: SoundEventType): Promise<void> {
    // Vibrate
    const eventConfig = SOUND_EVENTS.find((e) => e.type === eventType);
    if (eventConfig && this.prefs.vibrationEnabled[eventType]) {
      if (typeof navigator !== "undefined" && "vibrate" in navigator) {
        navigator.vibrate(eventConfig.vibration);
      }
    }

    // Sound
    if (this.prefs.muted || this.prefs.eventMuted[eventType]) return;

    const soundName = this.prefs.selections[eventType];
    if (soundName === "silent") return;

    await this.playSound(soundName);
  }

  /**
   * Play a specific sound by name (for preview).
   */
  async playSound(soundName: SoundName): Promise<void> {
    if (soundName === "silent") return;
    if (!this.initialized) await this.init();
    if (!this.ctx || !this.gainNode) return;

    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }

    const buffer = this.buffers.get(soundName);
    if (!buffer) return;

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gainNode);
    source.start(0);
  }

  /**
   * Preview a specific sound for a given event type.
   */
  async previewSound(eventType: SoundEventType, soundName: SoundName): Promise<void> {
    // Vibrate for preview too
    const eventConfig = SOUND_EVENTS.find((e) => e.type === eventType);
    if (eventConfig && this.prefs.vibrationEnabled[eventType]) {
      if (typeof navigator !== "undefined" && "vibrate" in navigator) {
        navigator.vibrate(eventConfig.vibration);
      }
    }

    await this.playSound(soundName);
  }

  setVolume(volume: number): void {
    this.prefs.volume = Math.max(0, Math.min(100, volume));
    storage.set(STORAGE_KEYS.volume, this.prefs.volume);
    if (this.gainNode && !this.prefs.muted) {
      this.gainNode.gain.setValueAtTime(
        this.prefs.volume / 100,
        this.ctx?.currentTime ?? 0,
      );
    }
  }

  mute(): void {
    this.prefs.muted = true;
    storage.set(STORAGE_KEYS.muted, true);
    if (this.gainNode) {
      this.gainNode.gain.setValueAtTime(0, this.ctx?.currentTime ?? 0);
    }
  }

  unmute(): void {
    this.prefs.muted = false;
    storage.set(STORAGE_KEYS.muted, false);
    if (this.gainNode) {
      this.gainNode.gain.setValueAtTime(
        this.prefs.volume / 100,
        this.ctx?.currentTime ?? 0,
      );
    }
  }

  setSelection(eventType: SoundEventType, soundName: SoundName): void {
    this.prefs.selections[eventType] = soundName;
    storage.set(STORAGE_KEYS.selections, this.prefs.selections);
  }

  setEventMuted(eventType: SoundEventType, muted: boolean): void {
    this.prefs.eventMuted[eventType] = muted;
    storage.set(STORAGE_KEYS.eventMuted, this.prefs.eventMuted);
  }

  setVibrationEnabled(eventType: SoundEventType, enabled: boolean): void {
    this.prefs.vibrationEnabled[eventType] = enabled;
    storage.set(STORAGE_KEYS.vibrationEnabled, this.prefs.vibrationEnabled);
  }

  resetToDefaults(): void {
    this.prefs = {
      volume: 80,
      muted: false,
      selections: getDefaultSelections(),
      eventMuted: getDefaultEventMuted(),
      vibrationEnabled: getDefaultVibrationEnabled(),
    };
    storage.set(STORAGE_KEYS.volume, 80);
    storage.set(STORAGE_KEYS.muted, false);
    storage.set(STORAGE_KEYS.selections, this.prefs.selections);
    storage.set(STORAGE_KEYS.eventMuted, this.prefs.eventMuted);
    storage.set(STORAGE_KEYS.vibrationEnabled, this.prefs.vibrationEnabled);

    if (this.gainNode) {
      this.gainNode.gain.setValueAtTime(0.8, this.ctx?.currentTime ?? 0);
    }
  }
}

// Singleton
let instance: SoundManager | null = null;

export function getSoundManager(): SoundManager {
  if (!instance) {
    instance = new SoundManager();
  }
  return instance;
}
