/**
 * Programmatic sound synthesis via Web Audio API.
 * 35 unique sounds across 9 event types — no external audio files.
 */

export type SoundEventType =
  | "buy_open"
  | "sell_open"
  | "trade_profit"
  | "big_win"
  | "trade_loss"
  | "big_loss"
  | "system_error"
  | "signal_recovery"
  | "position_aligned";

export type SoundName =
  // buy_open
  | "power-up" | "swift-swoosh" | "coin-drop" | "click-confirm"
  // sell_open
  | "descend" | "blade-swoosh" | "lock-in" | "tap"
  // trade_profit
  | "cash-in" | "level-up" | "coins-clink" | "success-bell"
  // big_win
  | "jackpot" | "fireworks" | "victory-fanfare" | "money-rain"
  // trade_loss
  | "flatline" | "shatter" | "drain" | "buzzer" | "heavy-drop"
  // big_loss
  | "alarm" | "explosion" | "siren" | "market-crash"
  // system_error
  | "klaxon" | "glitch" | "warning-tone" | "red-alert"
  // signal_recovery
  | "rescue" | "reboot" | "sonar-ping"
  // position_aligned
  | "heartbeat" | "soft-chime" | "silent";

export interface SoundEventConfig {
  type: SoundEventType;
  label: string;
  description: string;
  vibration: number[];
  defaultSound: SoundName;
  options: { name: SoundName; label: string }[];
}

export const SOUND_EVENTS: SoundEventConfig[] = [
  {
    type: "buy_open",
    label: "Buy Open",
    description: "Buy/Long position opened",
    vibration: [100],
    defaultSound: "power-up",
    options: [
      { name: "power-up", label: "Power Up" },
      { name: "swift-swoosh", label: "Swift Swoosh" },
      { name: "coin-drop", label: "Coin Drop" },
      { name: "click-confirm", label: "Click Confirm" },
    ],
  },
  {
    type: "sell_open",
    label: "Sell Open",
    description: "Sell/Short position opened",
    vibration: [100, 50, 100],
    defaultSound: "descend",
    options: [
      { name: "descend", label: "Descend" },
      { name: "blade-swoosh", label: "Blade Swoosh" },
      { name: "lock-in", label: "Lock In" },
      { name: "tap", label: "Tap" },
    ],
  },
  {
    type: "trade_profit",
    label: "Trade Profit",
    description: "Trade closed with profit",
    vibration: [80, 40, 80],
    defaultSound: "cash-in",
    options: [
      { name: "cash-in", label: "Cash In" },
      { name: "level-up", label: "Level Up" },
      { name: "coins-clink", label: "Coins Clink" },
      { name: "success-bell", label: "Success Bell" },
    ],
  },
  {
    type: "big_win",
    label: "Big Win",
    description: "Trade closed with big profit (>5%)",
    vibration: [100, 50, 100, 50, 100, 50, 200],
    defaultSound: "jackpot",
    options: [
      { name: "jackpot", label: "Jackpot" },
      { name: "fireworks", label: "Fireworks" },
      { name: "victory-fanfare", label: "Victory Fanfare" },
      { name: "money-rain", label: "Money Rain" },
    ],
  },
  {
    type: "trade_loss",
    label: "Trade Loss",
    description: "Trade closed at a loss",
    vibration: [400],
    defaultSound: "flatline",
    options: [
      { name: "flatline", label: "Flatline" },
      { name: "shatter", label: "Shatter" },
      { name: "drain", label: "Drain" },
      { name: "buzzer", label: "Buzzer" },
      { name: "heavy-drop", label: "Heavy Drop" },
    ],
  },
  {
    type: "big_loss",
    label: "Big Loss",
    description: "Trade closed with major loss (>5%)",
    vibration: [300, 100, 300, 100, 300],
    defaultSound: "alarm",
    options: [
      { name: "alarm", label: "Alarm" },
      { name: "explosion", label: "Explosion" },
      { name: "siren", label: "Siren" },
      { name: "market-crash", label: "Market Crash" },
    ],
  },
  {
    type: "system_error",
    label: "System Error",
    description: "Bot down, VPN issue, or webhook failure",
    vibration: [200, 100, 200, 100, 200],
    defaultSound: "klaxon",
    options: [
      { name: "klaxon", label: "Klaxon" },
      { name: "glitch", label: "Glitch" },
      { name: "warning-tone", label: "Warning Tone" },
      { name: "red-alert", label: "Red Alert" },
    ],
  },
  {
    type: "signal_recovery",
    label: "Signal Recovery",
    description: "State reconciler corrected a mismatch",
    vibration: [50, 30, 50, 30, 100],
    defaultSound: "rescue",
    options: [
      { name: "rescue", label: "Rescue" },
      { name: "reboot", label: "Reboot" },
      { name: "sonar-ping", label: "Sonar Ping" },
    ],
  },
  {
    type: "position_aligned",
    label: "Position Aligned",
    description: "Hourly check confirmed position matches strategy",
    vibration: [30],
    defaultSound: "silent",
    options: [
      { name: "heartbeat", label: "Heartbeat" },
      { name: "soft-chime", label: "Soft Chime" },
      { name: "silent", label: "Silent" },
    ],
  },
];

/* ── Helpers ── */

function createNoiseBuffer(ctx: OfflineAudioContext, duration: number): AudioBuffer {
  const length = Math.ceil(ctx.sampleRate * duration);
  const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i++) {
    data[i] = Math.random() * 2 - 1;
  }
  return buffer;
}

function scheduleOsc(
  ctx: OfflineAudioContext,
  dest: AudioNode,
  type: OscillatorType,
  freq: number,
  startTime: number,
  endTime: number,
  gainEnv: { t: number; v: number }[],
  detune = 0,
): void {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  if (detune) osc.detune.value = detune;
  gain.gain.setValueAtTime(0, startTime);
  for (const { t, v } of gainEnv) {
    gain.gain.linearRampToValueAtTime(v, startTime + t);
  }
  osc.connect(gain);
  gain.connect(dest);
  osc.start(startTime);
  osc.stop(endTime);
}

function scheduleSweep(
  ctx: OfflineAudioContext,
  dest: AudioNode,
  type: OscillatorType,
  freqStart: number,
  freqEnd: number,
  startTime: number,
  duration: number,
  peakGain: number,
): void {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freqStart, startTime);
  osc.frequency.exponentialRampToValueAtTime(Math.max(freqEnd, 20), startTime + duration);
  gain.gain.setValueAtTime(0, startTime);
  gain.gain.linearRampToValueAtTime(peakGain, startTime + 0.02);
  gain.gain.linearRampToValueAtTime(0, startTime + duration);
  osc.connect(gain);
  gain.connect(dest);
  osc.start(startTime);
  osc.stop(startTime + duration + 0.05);
}

function scheduleNoise(
  ctx: OfflineAudioContext,
  dest: AudioNode,
  startTime: number,
  duration: number,
  peakGain: number,
  filterFreq?: number,
  filterType?: BiquadFilterType,
): void {
  const noiseBuffer = createNoiseBuffer(ctx, duration);
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0, startTime);
  gain.gain.linearRampToValueAtTime(peakGain, startTime + 0.005);
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

  if (filterFreq && filterType) {
    const filter = ctx.createBiquadFilter();
    filter.type = filterType;
    filter.frequency.value = filterFreq;
    filter.Q.value = 1;
    src.connect(filter);
    filter.connect(gain);
  } else {
    src.connect(gain);
  }
  gain.connect(dest);
  src.start(startTime);
  src.stop(startTime + duration + 0.05);
}

function scheduleTone(
  ctx: OfflineAudioContext,
  dest: AudioNode,
  freq: number,
  startTime: number,
  duration: number,
  peakGain: number,
  type: OscillatorType = "sine",
  attack = 0.01,
  release = 0.05,
): void {
  scheduleOsc(ctx, dest, type, freq, startTime, startTime + duration + release, [
    { t: attack, v: peakGain },
    { t: duration, v: peakGain * 0.8 },
    { t: duration + release, v: 0 },
  ]);
}

/* ── Sound Generators ── */

type GeneratorFn = (ctx: OfflineAudioContext) => void;

const generators: Record<SoundName, { duration: number; fn: GeneratorFn }> = {
  // ─── BUY OPEN ───
  "power-up": {
    duration: 0.5,
    fn(ctx) {
      scheduleSweep(ctx, ctx.destination, "sine", 200, 1200, 0, 0.4, 0.5);
      scheduleSweep(ctx, ctx.destination, "triangle", 400, 2400, 0.05, 0.35, 0.2);
      scheduleTone(ctx, ctx.destination, 1200, 0.35, 0.12, 0.3, "sine", 0.01, 0.08);
    },
  },
  "swift-swoosh": {
    duration: 0.35,
    fn(ctx) {
      scheduleSweep(ctx, ctx.destination, "sawtooth", 300, 2000, 0, 0.2, 0.15);
      scheduleNoise(ctx, ctx.destination, 0, 0.25, 0.12, 4000, "highpass");
    },
  },
  "coin-drop": {
    duration: 0.6,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 2200, 0, 0.08, 0.4, "sine", 0.002, 0.15);
      scheduleTone(ctx, ctx.destination, 1800, 0.03, 0.06, 0.25, "sine", 0.002, 0.12);
      scheduleTone(ctx, ctx.destination, 3300, 0.08, 0.15, 0.2, "triangle", 0.002, 0.3);
    },
  },
  "click-confirm": {
    duration: 0.5,
    fn(ctx) {
      scheduleNoise(ctx, ctx.destination, 0, 0.03, 0.3, 3000, "highpass");
      scheduleTone(ctx, ctx.destination, 1400, 0.05, 0.15, 0.3, "sine", 0.01, 0.25);
      scheduleTone(ctx, ctx.destination, 2100, 0.08, 0.12, 0.15, "sine", 0.01, 0.2);
    },
  },

  // ─── SELL OPEN ───
  "descend": {
    duration: 0.5,
    fn(ctx) {
      scheduleSweep(ctx, ctx.destination, "sine", 1200, 200, 0, 0.4, 0.5);
      scheduleSweep(ctx, ctx.destination, "triangle", 2400, 400, 0.05, 0.35, 0.2);
      scheduleTone(ctx, ctx.destination, 200, 0.35, 0.12, 0.3, "sine", 0.01, 0.08);
    },
  },
  "blade-swoosh": {
    duration: 0.3,
    fn(ctx) {
      scheduleSweep(ctx, ctx.destination, "sawtooth", 2000, 200, 0, 0.2, 0.15);
      scheduleNoise(ctx, ctx.destination, 0, 0.2, 0.15, 5000, "highpass");
    },
  },
  "lock-in": {
    duration: 0.4,
    fn(ctx) {
      scheduleNoise(ctx, ctx.destination, 0, 0.04, 0.35, 2000, "lowpass");
      scheduleTone(ctx, ctx.destination, 600, 0.02, 0.06, 0.4, "square", 0.002, 0.05);
      scheduleTone(ctx, ctx.destination, 400, 0.08, 0.08, 0.3, "square", 0.002, 0.15);
    },
  },
  "tap": {
    duration: 0.3,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 3000, 0, 0.02, 0.35, "sine", 0.001, 0.08);
      scheduleTone(ctx, ctx.destination, 5000, 0, 0.015, 0.15, "sine", 0.001, 0.06);
      scheduleNoise(ctx, ctx.destination, 0, 0.02, 0.1, 6000, "highpass");
    },
  },

  // ─── TRADE PROFIT ───
  "cash-in": {
    duration: 0.8,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 1800, 0, 0.04, 0.3, "triangle", 0.002, 0.04);
      scheduleTone(ctx, ctx.destination, 2200, 0.06, 0.04, 0.25, "triangle", 0.002, 0.04);
      scheduleTone(ctx, ctx.destination, 2800, 0.12, 0.06, 0.35, "sine", 0.005, 0.1);
      scheduleNoise(ctx, ctx.destination, 0.1, 0.15, 0.08, 4000, "highpass");
      scheduleTone(ctx, ctx.destination, 3500, 0.2, 0.15, 0.2, "sine", 0.01, 0.35);
    },
  },
  "level-up": {
    duration: 0.7,
    fn(ctx) {
      const notes = [523, 659, 784, 1047]; // C5 E5 G5 C6
      notes.forEach((freq, i) => {
        scheduleTone(ctx, ctx.destination, freq, i * 0.1, 0.12, 0.35, "sine", 0.005, 0.1);
        scheduleTone(ctx, ctx.destination, freq * 2, i * 0.1 + 0.02, 0.08, 0.1, "triangle", 0.005, 0.08);
      });
    },
  },
  "coins-clink": {
    duration: 0.8,
    fn(ctx) {
      for (let i = 0; i < 6; i++) {
        const freq = 2500 + Math.sin(i * 1.7) * 1200;
        scheduleTone(ctx, ctx.destination, freq, i * 0.08, 0.03, 0.2 + i * 0.02, "sine", 0.001, 0.1);
        scheduleTone(ctx, ctx.destination, freq * 1.5, i * 0.08 + 0.01, 0.02, 0.08, "triangle", 0.001, 0.06);
      }
    },
  },
  "success-bell": {
    duration: 0.9,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 1200, 0, 0.5, 0.4, "sine", 0.005, 0.35);
      scheduleTone(ctx, ctx.destination, 2400, 0, 0.3, 0.15, "sine", 0.005, 0.2);
      scheduleTone(ctx, ctx.destination, 3600, 0, 0.2, 0.08, "sine", 0.005, 0.15);
      scheduleTone(ctx, ctx.destination, 1800, 0.01, 0.25, 0.1, "triangle", 0.005, 0.2);
    },
  },

  // ─── BIG WIN ───
  "jackpot": {
    duration: 2.0,
    fn(ctx) {
      const notes = [523, 659, 784, 1047]; // C5 E5 G5 C6
      // Initial rising arpeggio
      notes.forEach((freq, i) => {
        scheduleTone(ctx, ctx.destination, freq, i * 0.08, 0.15, 0.35, "sine", 0.005, 0.1);
      });
      // Cascade of coin sounds
      for (let i = 0; i < 12; i++) {
        const t = 0.4 + i * 0.1;
        const freq = 2000 + Math.sin(i * 2.3) * 1500;
        scheduleTone(ctx, ctx.destination, freq, t, 0.03, 0.15 + (i % 3) * 0.05, "triangle", 0.001, 0.08);
      }
      // Triumphant final chord
      scheduleTone(ctx, ctx.destination, 1047, 1.5, 0.4, 0.3, "sine", 0.01, 0.2);
      scheduleTone(ctx, ctx.destination, 1319, 1.5, 0.4, 0.25, "sine", 0.01, 0.2);
      scheduleTone(ctx, ctx.destination, 1568, 1.5, 0.4, 0.2, "sine", 0.01, 0.2);
    },
  },
  "fireworks": {
    duration: 1.8,
    fn(ctx) {
      // Launch whoosh
      scheduleSweep(ctx, ctx.destination, "sawtooth", 100, 3000, 0, 0.3, 0.1);
      // Burst
      scheduleNoise(ctx, ctx.destination, 0.3, 0.15, 0.25, 3000, "highpass");
      // Sparkle tones
      for (let i = 0; i < 10; i++) {
        const t = 0.35 + i * 0.12;
        const freq = 2000 + Math.random() * 3000;
        scheduleTone(ctx, ctx.destination, freq, t, 0.04, 0.12, "sine", 0.002, 0.1);
      }
      // Second burst
      scheduleNoise(ctx, ctx.destination, 0.8, 0.12, 0.2, 4000, "highpass");
      for (let i = 0; i < 8; i++) {
        const t = 0.85 + i * 0.1;
        const freq = 2500 + Math.random() * 2500;
        scheduleTone(ctx, ctx.destination, freq, t, 0.03, 0.1, "triangle", 0.002, 0.08);
      }
    },
  },
  "victory-fanfare": {
    duration: 1.5,
    fn(ctx) {
      // Brass-like tones using square + triangle layers
      const fanfare: [number, number, number][] = [
        [523, 0, 0.2], [659, 0.15, 0.15], [784, 0.3, 0.15],
        [1047, 0.45, 0.35], [784, 0.85, 0.15], [1047, 1.0, 0.4],
      ];
      for (const [freq, t, dur] of fanfare) {
        scheduleTone(ctx, ctx.destination, freq, t, dur, 0.3, "square", 0.01, 0.05);
        scheduleTone(ctx, ctx.destination, freq, t + 0.005, dur, 0.15, "triangle", 0.01, 0.05);
      }
    },
  },
  "money-rain": {
    duration: 2.0,
    fn(ctx) {
      for (let i = 0; i < 20; i++) {
        const t = i * 0.08;
        const freq = 1800 + Math.sin(i * 1.1) * 1000 + i * 50;
        const gain = 0.12 + (i / 20) * 0.08;
        scheduleTone(ctx, ctx.destination, freq, t, 0.025, gain, "sine", 0.001, 0.06);
        if (i % 3 === 0) {
          scheduleTone(ctx, ctx.destination, freq * 1.5, t + 0.01, 0.02, gain * 0.4, "triangle", 0.001, 0.04);
        }
      }
      // Grand final shimmer
      scheduleTone(ctx, ctx.destination, 3000, 1.6, 0.3, 0.15, "sine", 0.02, 0.2);
    },
  },

  // ─── TRADE LOSS ───
  "flatline": {
    duration: 1.2,
    fn(ctx) {
      // Steady heartbeat beeps
      scheduleTone(ctx, ctx.destination, 1000, 0, 0.08, 0.35, "sine", 0.005, 0.02);
      scheduleTone(ctx, ctx.destination, 1000, 0.25, 0.08, 0.35, "sine", 0.005, 0.02);
      // Flatline — continuous tone
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 1000;
      gain.gain.setValueAtTime(0, 0.5);
      gain.gain.linearRampToValueAtTime(0.4, 0.55);
      gain.gain.setValueAtTime(0.4, 1.0);
      gain.gain.linearRampToValueAtTime(0, 1.15);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(0.5);
      osc.stop(1.2);
    },
  },
  "shatter": {
    duration: 0.8,
    fn(ctx) {
      // Impact
      scheduleTone(ctx, ctx.destination, 150, 0, 0.06, 0.45, "square", 0.001, 0.04);
      // Glass shards — high frequency noise bursts
      scheduleNoise(ctx, ctx.destination, 0.01, 0.15, 0.4, 6000, "highpass");
      scheduleNoise(ctx, ctx.destination, 0.05, 0.2, 0.25, 3000, "highpass");
      // Falling shards
      for (let i = 0; i < 6; i++) {
        const t = 0.1 + i * 0.08;
        scheduleTone(ctx, ctx.destination, 4000 - i * 400, t, 0.02, 0.1, "sine", 0.001, 0.06);
      }
      scheduleNoise(ctx, ctx.destination, 0.15, 0.5, 0.08, 2000, "highpass");
    },
  },
  "drain": {
    duration: 1.5,
    fn(ctx) {
      scheduleSweep(ctx, ctx.destination, "sine", 800, 80, 0, 1.3, 0.35);
      scheduleSweep(ctx, ctx.destination, "sawtooth", 600, 60, 0.1, 1.2, 0.1);
      // Swirling effect
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(400, 0);
      osc.frequency.exponentialRampToValueAtTime(50, 1.4);
      lfo.frequency.value = 6;
      lfoGain.gain.value = 80;
      lfo.connect(lfoGain);
      lfoGain.connect(osc.frequency);
      gain.gain.setValueAtTime(0.15, 0);
      gain.gain.linearRampToValueAtTime(0, 1.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(0.05);
      lfo.start(0.05);
      osc.stop(1.45);
      lfo.stop(1.45);
    },
  },
  "buzzer": {
    duration: 0.6,
    fn(ctx) {
      // Harsh wrong-answer buzzer
      scheduleTone(ctx, ctx.destination, 150, 0, 0.45, 0.4, "sawtooth", 0.005, 0.1);
      scheduleTone(ctx, ctx.destination, 153, 0, 0.45, 0.3, "sawtooth", 0.005, 0.1);
      scheduleTone(ctx, ctx.destination, 100, 0, 0.45, 0.2, "square", 0.005, 0.1);
    },
  },
  "heavy-drop": {
    duration: 1.8,
    fn(ctx) {
      // Deep bass drop
      scheduleSweep(ctx, ctx.destination, "sine", 600, 30, 0, 0.8, 0.5);
      scheduleSweep(ctx, ctx.destination, "triangle", 400, 25, 0.05, 0.75, 0.25);
      // Sub-bass rumble tail
      scheduleTone(ctx, ctx.destination, 35, 0.5, 1.0, 0.2, "sine", 0.1, 0.4);
      scheduleNoise(ctx, ctx.destination, 0.3, 0.6, 0.05, 200, "lowpass");
    },
  },

  // ─── BIG LOSS ───
  "alarm": {
    duration: 1.2,
    fn(ctx) {
      // Two piercing alarm cycles
      for (let i = 0; i < 4; i++) {
        const t = i * 0.28;
        const freq = i % 2 === 0 ? 800 : 1200;
        scheduleTone(ctx, ctx.destination, freq, t, 0.22, 0.45, "square", 0.005, 0.02);
        scheduleTone(ctx, ctx.destination, freq * 1.01, t, 0.22, 0.2, "sawtooth", 0.005, 0.02);
      }
    },
  },
  "explosion": {
    duration: 1.5,
    fn(ctx) {
      // Initial boom
      scheduleTone(ctx, ctx.destination, 60, 0, 0.3, 0.5, "sine", 0.002, 0.2);
      scheduleTone(ctx, ctx.destination, 40, 0, 0.4, 0.35, "square", 0.002, 0.25);
      scheduleNoise(ctx, ctx.destination, 0, 0.5, 0.35, 800, "lowpass");
      // Debris settling
      scheduleNoise(ctx, ctx.destination, 0.3, 0.8, 0.15, 2000, "lowpass");
      for (let i = 0; i < 5; i++) {
        const t = 0.5 + i * 0.15;
        scheduleNoise(ctx, ctx.destination, t, 0.06, 0.06, 3000 + i * 500, "highpass");
      }
    },
  },
  "siren": {
    duration: 1.5,
    fn(ctx) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      // Siren sweep
      osc.frequency.setValueAtTime(600, 0);
      osc.frequency.linearRampToValueAtTime(1400, 0.35);
      osc.frequency.linearRampToValueAtTime(600, 0.7);
      osc.frequency.linearRampToValueAtTime(1400, 1.05);
      osc.frequency.linearRampToValueAtTime(600, 1.4);
      gain.gain.setValueAtTime(0, 0);
      gain.gain.linearRampToValueAtTime(0.35, 0.05);
      gain.gain.setValueAtTime(0.35, 1.3);
      gain.gain.linearRampToValueAtTime(0, 1.45);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(0);
      osc.stop(1.5);
    },
  },
  "market-crash": {
    duration: 2.0,
    fn(ctx) {
      // Multiple descending tones collapsing
      const starts = [800, 1200, 600, 1000, 500];
      starts.forEach((freq, i) => {
        scheduleSweep(ctx, ctx.destination, "sawtooth", freq, 30 + i * 10, i * 0.15, 1.5 - i * 0.1, 0.12);
      });
      // Rumble
      scheduleTone(ctx, ctx.destination, 40, 0.8, 1.0, 0.2, "sine", 0.2, 0.3);
      scheduleNoise(ctx, ctx.destination, 0.6, 1.0, 0.1, 300, "lowpass");
    },
  },

  // ─── SYSTEM ERROR ───
  "klaxon": {
    duration: 1.5,
    fn(ctx) {
      for (let i = 0; i < 3; i++) {
        const t = i * 0.45;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        const filter = ctx.createBiquadFilter();
        osc.type = "sawtooth";
        osc.frequency.value = 200;
        filter.type = "lowpass";
        filter.frequency.setValueAtTime(400, t);
        filter.frequency.linearRampToValueAtTime(2000, t + 0.15);
        filter.frequency.linearRampToValueAtTime(400, t + 0.35);
        filter.Q.value = 5;
        gain.gain.setValueAtTime(0, t);
        gain.gain.linearRampToValueAtTime(0.4, t + 0.03);
        gain.gain.setValueAtTime(0.4, t + 0.3);
        gain.gain.linearRampToValueAtTime(0, t + 0.4);
        osc.connect(filter);
        filter.connect(gain);
        gain.connect(ctx.destination);
        osc.start(t);
        osc.stop(t + 0.42);
      }
    },
  },
  "glitch": {
    duration: 0.8,
    fn(ctx) {
      // Digital corruption
      for (let i = 0; i < 8; i++) {
        const t = i * 0.08;
        const freq = 200 + Math.random() * 2000;
        const dur = 0.02 + Math.random() * 0.04;
        scheduleTone(ctx, ctx.destination, freq, t, dur, 0.2 + Math.random() * 0.15, "square", 0.001, 0.01);
      }
      scheduleNoise(ctx, ctx.destination, 0.1, 0.1, 0.15, 1000, "lowpass");
      scheduleNoise(ctx, ctx.destination, 0.35, 0.08, 0.2, 5000, "highpass");
      // Bit-crushed tone
      scheduleTone(ctx, ctx.destination, 440, 0.5, 0.15, 0.25, "square", 0.002, 0.05);
    },
  },
  "warning-tone": {
    duration: 0.8,
    fn(ctx) {
      // Two-tone professional warning
      scheduleTone(ctx, ctx.destination, 880, 0, 0.2, 0.35, "sine", 0.01, 0.05);
      scheduleTone(ctx, ctx.destination, 660, 0.25, 0.25, 0.35, "sine", 0.01, 0.15);
      scheduleTone(ctx, ctx.destination, 1760, 0, 0.15, 0.08, "sine", 0.01, 0.05);
      scheduleTone(ctx, ctx.destination, 1320, 0.25, 0.2, 0.08, "sine", 0.01, 0.1);
    },
  },
  "red-alert": {
    duration: 1.2,
    fn(ctx) {
      // Star Trek style pulsing alert
      for (let i = 0; i < 3; i++) {
        const t = i * 0.38;
        scheduleTone(ctx, ctx.destination, 880, t, 0.15, 0.35, "sine", 0.01, 0.08);
        scheduleTone(ctx, ctx.destination, 880, t, 0.15, 0.15, "square", 0.01, 0.08);
        scheduleTone(ctx, ctx.destination, 440, t + 0.005, 0.15, 0.1, "sine", 0.01, 0.08);
      }
    },
  },

  // ─── SIGNAL RECOVERY ───
  "rescue": {
    duration: 1.0,
    fn(ctx) {
      // Ascending recovery tones
      const freqs = [300, 500, 800, 1200];
      freqs.forEach((freq, i) => {
        scheduleTone(ctx, ctx.destination, freq, i * 0.15, 0.15, 0.25 + i * 0.05, "sine", 0.01, 0.1);
      });
      // Final sustain
      scheduleTone(ctx, ctx.destination, 1200, 0.6, 0.3, 0.2, "triangle", 0.02, 0.15);
    },
  },
  "reboot": {
    duration: 1.0,
    fn(ctx) {
      // Digital startup sequence
      for (let i = 0; i < 5; i++) {
        const t = i * 0.12;
        const freq = 200 + i * 200;
        scheduleTone(ctx, ctx.destination, freq, t, 0.06, 0.2, "square", 0.002, 0.03);
      }
      // System online chime
      scheduleTone(ctx, ctx.destination, 1500, 0.65, 0.2, 0.3, "sine", 0.01, 0.15);
      scheduleTone(ctx, ctx.destination, 2000, 0.7, 0.2, 0.2, "sine", 0.01, 0.15);
    },
  },
  "sonar-ping": {
    duration: 0.8,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 1200, 0, 0.05, 0.4, "sine", 0.002, 0.6);
      scheduleTone(ctx, ctx.destination, 2400, 0, 0.03, 0.1, "sine", 0.002, 0.3);
    },
  },

  // ─── POSITION ALIGNED ───
  "heartbeat": {
    duration: 0.5,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 60, 0, 0.08, 0.15, "sine", 0.005, 0.06);
      scheduleTone(ctx, ctx.destination, 50, 0.12, 0.06, 0.1, "sine", 0.005, 0.08);
    },
  },
  "soft-chime": {
    duration: 0.8,
    fn(ctx) {
      scheduleTone(ctx, ctx.destination, 2000, 0, 0.08, 0.1, "sine", 0.01, 0.5);
      scheduleTone(ctx, ctx.destination, 3000, 0.02, 0.05, 0.04, "sine", 0.01, 0.3);
    },
  },
  "silent": {
    duration: 0.01,
    fn() {
      // Intentionally empty — no sound
    },
  },
};

/**
 * Generate an AudioBuffer for a given sound name.
 */
export async function generateSound(
  name: SoundName,
  sampleRate = 44100,
): Promise<AudioBuffer> {
  const config = generators[name];
  const duration = config.duration + 0.1; // padding
  const ctx = new OfflineAudioContext(1, Math.ceil(sampleRate * duration), sampleRate);
  config.fn(ctx);
  return ctx.startRendering();
}

/**
 * Generate all 35 sound buffers.
 */
export async function generateAllSounds(
  sampleRate = 44100,
): Promise<Map<SoundName, AudioBuffer>> {
  const buffers = new Map<SoundName, AudioBuffer>();
  const names = Object.keys(generators) as SoundName[];
  const results = await Promise.all(
    names.map((name) => generateSound(name, sampleRate)),
  );
  names.forEach((name, i) => buffers.set(name, results[i]));
  return buffers;
}
