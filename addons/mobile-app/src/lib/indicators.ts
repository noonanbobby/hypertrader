import type { CandleData, SupertrendPoint, SupertrendSignal, SqueezePoint, MacdRsiPoint } from "@/types";
import { SUPERTREND_CONFIG, SQUEEZE_CONFIG, MACD_RSI_CONFIG } from "./constants";

/* ─────────────────────────────────────────────
   Helpers
   ───────────────────────────────────────────── */

function trueRange(candles: CandleData[], i: number): number {
  if (i === 0) return candles[i].high - candles[i].low;
  const prev = candles[i - 1];
  return Math.max(
    candles[i].high - candles[i].low,
    Math.abs(candles[i].high - prev.close),
    Math.abs(candles[i].low - prev.close),
  );
}

function sma(values: number[], period: number): number[] {
  const result: number[] = new Array(values.length).fill(NaN);
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    result[i] = sum / period;
  }
  return result;
}

function ema(values: number[], period: number): number[] {
  const result: number[] = new Array(values.length).fill(NaN);
  const k = 2 / (period + 1);
  let first = true;
  for (let i = 0; i < values.length; i++) {
    if (isNaN(values[i])) continue;
    if (first) {
      result[i] = values[i];
      first = false;
    } else {
      result[i] = values[i] * k + result[i - 1] * (1 - k);
    }
  }
  return result;
}

function rma(values: number[], period: number): number[] {
  const result: number[] = new Array(values.length).fill(NaN);
  let sum = 0;
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    if (isNaN(values[i])) continue;
    if (count < period) {
      sum += values[i];
      count++;
      if (count === period) {
        result[i] = sum / period;
      }
    } else {
      result[i] = (result[i - 1] * (period - 1) + values[i]) / period;
    }
  }
  return result;
}

function stdDev(values: number[], period: number): number[] {
  const result: number[] = new Array(values.length).fill(NaN);
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const mean = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) variance += (values[j] - mean) ** 2;
    result[i] = Math.sqrt(variance / period);
  }
  return result;
}

function linreg(values: number[], period: number): number[] {
  const result: number[] = new Array(values.length).fill(NaN);
  for (let i = period - 1; i < values.length; i++) {
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (let j = 0; j < period; j++) {
      const x = j;
      const y = values[i - period + 1 + j];
      sumX += x;
      sumY += y;
      sumXY += x * y;
      sumX2 += x * x;
    }
    const slope = (period * sumXY - sumX * sumY) / (period * sumX2 - sumX * sumX);
    const intercept = (sumY - slope * sumX) / period;
    result[i] = intercept + slope * (period - 1);
  }
  return result;
}

/* ─────────────────────────────────────────────
   Supertrend
   ATR Period: 10, Multiplier: 1.3, Source: close
   ───────────────────────────────────────────── */

export function calcSupertrend(
  candles: CandleData[],
  config = SUPERTREND_CONFIG,
): { points: SupertrendPoint[]; signals: SupertrendSignal[] } {
  const { atrPeriod, multiplier } = config;
  const n = candles.length;
  if (n < atrPeriod + 1) return { points: [], signals: [] };

  // ATR via RMA
  const trValues = candles.map((_, i) => trueRange(candles, i));
  const atr = rma(trValues, atrPeriod);

  // Supertrend calculation
  const upperBand: number[] = new Array(n).fill(NaN);
  const lowerBand: number[] = new Array(n).fill(NaN);
  const direction: number[] = new Array(n).fill(1); // 1 = bullish, -1 = bearish
  const supertrendValues: number[] = new Array(n).fill(NaN);

  for (let i = 0; i < n; i++) {
    if (isNaN(atr[i])) continue;

    const hl2 = (candles[i].high + candles[i].low) / 2;
    const basicUpper = hl2 + multiplier * atr[i];
    const basicLower = hl2 - multiplier * atr[i];

    // Final upper band
    if (i > 0 && !isNaN(upperBand[i - 1])) {
      upperBand[i] = basicUpper < upperBand[i - 1] || candles[i - 1].close > upperBand[i - 1]
        ? basicUpper
        : upperBand[i - 1];
    } else {
      upperBand[i] = basicUpper;
    }

    // Final lower band
    if (i > 0 && !isNaN(lowerBand[i - 1])) {
      lowerBand[i] = basicLower > lowerBand[i - 1] || candles[i - 1].close < lowerBand[i - 1]
        ? basicLower
        : lowerBand[i - 1];
    } else {
      lowerBand[i] = basicLower;
    }

    // Direction
    if (i > 0) {
      const prevDir = direction[i - 1];
      if (prevDir === -1 && candles[i].close > upperBand[i]) {
        direction[i] = 1;
      } else if (prevDir === 1 && candles[i].close < lowerBand[i]) {
        direction[i] = -1;
      } else {
        direction[i] = prevDir;
      }
    }

    supertrendValues[i] = direction[i] === 1 ? lowerBand[i] : upperBand[i];
  }

  // Build points and signals
  const points: SupertrendPoint[] = [];
  const signals: SupertrendSignal[] = [];

  for (let i = 0; i < n; i++) {
    if (isNaN(supertrendValues[i])) continue;

    points.push({
      time: candles[i].time,
      value: supertrendValues[i],
      direction: direction[i] === 1 ? "bullish" : "bearish",
    });

    // Direction change = signal
    if (i > 0 && direction[i] !== direction[i - 1] && !isNaN(supertrendValues[i - 1])) {
      if (direction[i] === 1) {
        signals.push({
          time: candles[i].time,
          type: "buy",
          price: candles[i].low,
          label: "Buy",
        });
      } else {
        signals.push({
          time: candles[i].time,
          type: "sell",
          price: candles[i].high,
          label: "Sell",
        });
      }
    }
  }

  return { points, signals };
}

/* ─────────────────────────────────────────────
   Squeeze Momentum
   BB Length 20, MultFactor 2, KC Length 20, MultFactor 1.5
   ───────────────────────────────────────────── */

export function calcSqueezeMomentum(
  candles: CandleData[],
  config = SQUEEZE_CONFIG,
): SqueezePoint[] {
  const { bbLength, bbMultFactor, kcLength, kcMultFactor } = config;
  const n = candles.length;
  const closes = candles.map((c) => c.close);
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);

  // Bollinger Bands
  const bbBasis = sma(closes, bbLength);
  const bbDev = stdDev(closes, bbLength);

  // Keltner Channel (using SMA + ATR-based range)
  const kcBasis = sma(closes, kcLength);
  const trValues = candles.map((_, i) => trueRange(candles, i));
  const kcRange = sma(trValues, kcLength);

  // Momentum value = linear regression of (close - midline of highest/lowest + SMA)
  const highestHigh: number[] = new Array(n).fill(NaN);
  const lowestLow: number[] = new Array(n).fill(NaN);
  for (let i = kcLength - 1; i < n; i++) {
    let hh = -Infinity, ll = Infinity;
    for (let j = i - kcLength + 1; j <= i; j++) {
      if (highs[j] > hh) hh = highs[j];
      if (lows[j] < ll) ll = lows[j];
    }
    highestHigh[i] = hh;
    lowestLow[i] = ll;
  }

  const momentum: number[] = new Array(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    if (isNaN(highestHigh[i]) || isNaN(lowestLow[i]) || isNaN(kcBasis[i])) continue;
    const midline = (highestHigh[i] + lowestLow[i]) / 2;
    momentum[i] = closes[i] - (midline + kcBasis[i]) / 2;
  }

  const val = linreg(momentum, kcLength);

  const result: SqueezePoint[] = [];
  for (let i = 0; i < n; i++) {
    if (isNaN(val[i])) continue;

    // Squeeze detection: BB inside KC
    const bbUpper = bbBasis[i] + bbMultFactor * bbDev[i];
    const bbLower = bbBasis[i] - bbMultFactor * bbDev[i];
    const kcUpper = kcBasis[i] + kcMultFactor * kcRange[i];
    const kcLower = kcBasis[i] - kcMultFactor * kcRange[i];
    const squeezeOn = bbLower > kcLower && bbUpper < kcUpper;

    // 4-color scheme
    let color: SqueezePoint["color"];
    const prev = i > 0 && !isNaN(val[i - 1]) ? val[i - 1] : val[i];
    if (val[i] > 0) {
      color = val[i] > prev ? "brightGreen" : "darkGreen";
    } else {
      color = val[i] < prev ? "brightRed" : "darkRed";
    }

    result.push({
      time: candles[i].time,
      value: val[i],
      color,
      squeezeOn,
    });
  }

  return result;
}

/* ─────────────────────────────────────────────
   MACD + RSI Combined
   MACD: close 12 26 9 | RSI: 14
   ───────────────────────────────────────────── */

export function calcMacdRsi(
  candles: CandleData[],
  config = MACD_RSI_CONFIG,
): MacdRsiPoint[] {
  const { fastLength, slowLength, signalLength, rsiLength } = config;
  const closes = candles.map((c) => c.close);
  const n = closes.length;

  // MACD
  const fastEma = ema(closes, fastLength);
  const slowEma = ema(closes, slowLength);
  const macdLine: number[] = new Array(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    if (!isNaN(fastEma[i]) && !isNaN(slowEma[i])) {
      macdLine[i] = fastEma[i] - slowEma[i];
    }
  }
  const signal = ema(macdLine, signalLength);
  const histogram: number[] = new Array(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    if (!isNaN(macdLine[i]) && !isNaN(signal[i])) {
      histogram[i] = macdLine[i] - signal[i];
    }
  }

  // RSI
  const gains: number[] = new Array(n).fill(NaN);
  const losses: number[] = new Array(n).fill(NaN);
  for (let i = 1; i < n; i++) {
    const change = closes[i] - closes[i - 1];
    gains[i] = change > 0 ? change : 0;
    losses[i] = change < 0 ? -change : 0;
  }
  const avgGain = rma(gains, rsiLength);
  const avgLoss = rma(losses, rsiLength);
  const rsiValues: number[] = new Array(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    if (isNaN(avgGain[i]) || isNaN(avgLoss[i])) continue;
    if (avgLoss[i] === 0) {
      rsiValues[i] = 100;
    } else {
      rsiValues[i] = 100 - 100 / (1 + avgGain[i] / avgLoss[i]);
    }
  }

  // Build result
  const result: MacdRsiPoint[] = [];
  for (let i = 0; i < n; i++) {
    if (isNaN(rsiValues[i]) || isNaN(signal[i]) || isNaN(histogram[i])) continue;

    const prev = i > 0 && !isNaN(histogram[i - 1]) ? histogram[i - 1] : histogram[i];
    let histogramColor: MacdRsiPoint["histogramColor"];
    if (histogram[i] > 0) {
      histogramColor = histogram[i] > prev ? "brightGreen" : "paleGreen";
    } else {
      histogramColor = histogram[i] < prev ? "brightRed" : "paleRed";
    }

    result.push({
      time: candles[i].time,
      rsi: rsiValues[i],
      macdSignal: signal[i],
      histogram: histogram[i],
      histogramColor,
    });
  }

  return result;
}
