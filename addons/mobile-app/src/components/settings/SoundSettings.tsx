"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { getSoundManager } from "@/lib/sounds";
import { SOUND_EVENTS, type SoundEventType, type SoundName } from "@/lib/sound-generator";
import { SettingsSection, SettingsRow, Toggle } from "./SettingsSection";
import { useHaptic } from "@/hooks/useHaptic";

export const SoundSettings = memo(function SoundSettings() {
  const haptic = useHaptic();
  const [prefs, setPrefs] = useState(() => getSoundManager().getPreferences());
  const [playingEvent, setPlayingEvent] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const testAbortRef = useRef(false);
  const volumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshPrefs = useCallback(() => {
    setPrefs(getSoundManager().getPreferences());
  }, []);

  // Ensure SoundManager is initialized
  useEffect(() => {
    getSoundManager().init();
  }, []);

  const handleVolumeChange = useCallback((value: number) => {
    getSoundManager().setVolume(value);
    refreshPrefs();

    // Debounced preview tone
    if (volumeTimerRef.current) clearTimeout(volumeTimerRef.current);
    volumeTimerRef.current = setTimeout(() => {
      getSoundManager().playSound("click-confirm");
    }, 300);
  }, [refreshPrefs]);

  const handleMasterMute = useCallback((muted: boolean) => {
    if (muted) getSoundManager().mute();
    else getSoundManager().unmute();
    haptic("tick");
    refreshPrefs();
  }, [haptic, refreshPrefs]);

  const handleSelectionChange = useCallback((eventType: SoundEventType, soundName: SoundName) => {
    getSoundManager().setSelection(eventType, soundName);
    haptic("tick");
    refreshPrefs();
  }, [haptic, refreshPrefs]);

  const handlePreview = useCallback(async (eventType: SoundEventType) => {
    const soundName = prefs.selections[eventType];
    setPlayingEvent(eventType);
    await getSoundManager().previewSound(eventType, soundName);
    setTimeout(() => setPlayingEvent(null), 1500);
  }, [prefs.selections]);

  const handleEventMute = useCallback((eventType: SoundEventType, muted: boolean) => {
    getSoundManager().setEventMuted(eventType, muted);
    haptic("tick");
    refreshPrefs();
  }, [haptic, refreshPrefs]);

  const handleVibrationToggle = useCallback((eventType: SoundEventType, enabled: boolean) => {
    getSoundManager().setVibrationEnabled(eventType, enabled);
    haptic("tick");
    refreshPrefs();
  }, [haptic, refreshPrefs]);

  const handleTestAll = useCallback(async () => {
    if (testingAll) return;
    setTestingAll(true);
    testAbortRef.current = false;

    for (const event of SOUND_EVENTS) {
      if (testAbortRef.current) break;
      setPlayingEvent(event.type);
      await getSoundManager().play(event.type);
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }

    setPlayingEvent(null);
    setTestingAll(false);
  }, [testingAll]);

  const handleReset = useCallback(() => {
    getSoundManager().resetToDefaults();
    haptic("medium");
    refreshPrefs();
  }, [haptic, refreshPrefs]);

  return (
    <SettingsSection title="Sounds & Haptics">
      {/* Master volume */}
      <div className="flex flex-col gap-2 px-4 py-3 border-b" style={{ borderColor: "rgba(42,46,57,0.3)" }}>
        <div className="flex items-center justify-between">
          <span className="text-sm" style={{ color: "#d1d4dc" }}>Volume</span>
          <span className="font-mono text-sm tabular-nums" style={{ color: "#2962ff" }}>
            {prefs.volume}%
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={prefs.volume}
          onChange={(e) => handleVolumeChange(Number(e.target.value))}
          className="w-full accent-[#2962ff]"
          style={{ height: "4px" }}
          aria-label={`Volume: ${prefs.volume}%`}
        />
      </div>

      {/* Master mute */}
      <SettingsRow label="Master Mute">
        <Toggle
          checked={prefs.muted}
          onChange={() => handleMasterMute(!prefs.muted)}
          label="Master mute"
        />
      </SettingsRow>

      {/* Per-event controls */}
      {SOUND_EVENTS.map((event, idx) => {
        const isPlaying = playingEvent === event.type;
        const isLast = idx === SOUND_EVENTS.length - 1;

        return (
          <div
            key={event.type}
            className={`px-4 py-3 ${isLast ? "" : "border-b"} ${isPlaying ? "bg-[rgba(41,98,255,0.05)]" : ""}`}
            style={{ borderColor: "rgba(42,46,57,0.3)", transition: "background-color 200ms" }}
          >
            {/* Event name + description */}
            <div className="mb-2">
              <span className="text-sm font-medium" style={{ color: "#d1d4dc" }}>
                {event.label}
              </span>
              <p className="text-[10px] mt-0.5" style={{ color: "#787b86" }}>
                {event.description}
              </p>
            </div>

            {/* Sound selector + preview */}
            <div className="flex items-center gap-2 mb-2">
              <select
                value={prefs.selections[event.type]}
                onChange={(e) => handleSelectionChange(event.type, e.target.value as SoundName)}
                disabled={prefs.muted}
                className="flex-1 rounded-lg border bg-transparent px-2.5 py-2 text-xs font-mono disabled:opacity-40"
                style={{ borderColor: "rgba(42,46,57,0.6)", color: "#d1d4dc" }}
                aria-label={`Sound for ${event.label}`}
              >
                {event.options.map((opt) => (
                  <option key={opt.name} value={opt.name} style={{ backgroundColor: "#1e222d" }}>
                    {opt.label}
                  </option>
                ))}
              </select>

              <button
                onClick={() => handlePreview(event.type)}
                disabled={prefs.muted || prefs.eventMuted[event.type] || prefs.selections[event.type] === "silent"}
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border transition-default active:scale-90 disabled:opacity-30"
                style={{ borderColor: "rgba(42,46,57,0.6)" }}
                aria-label={`Preview ${event.label} sound`}
              >
                {isPlaying ? (
                  <div className="h-3.5 w-3.5 rounded-full" style={{ backgroundColor: "#2962ff", animation: "pulseSubtle 0.8s ease-in-out infinite" }} />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#787b86" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                    <path d="M19.07 4.93a10 10 0 010 14.14" />
                    <path d="M15.54 8.46a5 5 0 010 7.07" />
                  </svg>
                )}
              </button>
            </div>

            {/* Toggles row */}
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-1.5 text-[10px]" style={{ color: "#787b86" }}>
                <input
                  type="checkbox"
                  checked={!prefs.eventMuted[event.type]}
                  onChange={(e) => handleEventMute(event.type, !e.target.checked)}
                  disabled={prefs.muted}
                  className="accent-[#2962ff] h-3.5 w-3.5"
                />
                Sound
              </label>
              <label className="flex items-center gap-1.5 text-[10px]" style={{ color: "#787b86" }}>
                <input
                  type="checkbox"
                  checked={prefs.vibrationEnabled[event.type]}
                  onChange={(e) => handleVibrationToggle(event.type, e.target.checked)}
                  className="accent-[#2962ff] h-3.5 w-3.5"
                />
                Vibration
              </label>
            </div>
          </div>
        );
      })}

      {/* Test All + Reset */}
      <div className="flex gap-3 px-4 py-3">
        <button
          onClick={handleTestAll}
          disabled={testingAll || prefs.muted}
          className="flex-1 rounded-lg border py-2.5 text-xs font-medium transition-default active:scale-95 disabled:opacity-40"
          style={{ borderColor: "rgba(41,98,255,0.3)", color: "#2962ff" }}
        >
          {testingAll ? `Playing: ${SOUND_EVENTS.find((e) => e.type === playingEvent)?.label ?? "..."}` : "Test All Sounds"}
        </button>
        <button
          onClick={handleReset}
          className="rounded-lg border px-4 py-2.5 text-xs font-medium transition-default active:scale-95"
          style={{ borderColor: "rgba(42,46,57,0.6)", color: "#787b86" }}
        >
          Reset
        </button>
      </div>
    </SettingsSection>
  );
});
