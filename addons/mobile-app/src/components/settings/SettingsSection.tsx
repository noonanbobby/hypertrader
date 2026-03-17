"use client";

interface SettingsSectionProps {
  title: string;
  children: React.ReactNode;
}

export function SettingsSection({ title, children }: SettingsSectionProps) {
  return (
    <div>
      <h2
        className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider"
        style={{ color: "#787b86" }}
      >
        {title}
      </h2>
      <div
        className="overflow-hidden rounded-xl border"
        style={{ backgroundColor: "#1e222d", borderColor: "rgba(42,46,57,0.6)" }}
      >
        {children}
      </div>
    </div>
  );
}

interface SettingsRowProps {
  label: string;
  children?: React.ReactNode;
  value?: string;
  valueColor?: string;
  last?: boolean;
  onTap?: () => void;
}

export function SettingsRow({
  label,
  children,
  value,
  valueColor,
  last = false,
  onTap,
}: SettingsRowProps) {
  const Component = onTap ? "button" : "div";
  return (
    <Component
      onClick={onTap}
      className={`flex min-h-[48px] w-full items-center justify-between px-4 py-3 text-left ${
        last ? "" : "border-b"
      } ${onTap ? "active:bg-[rgba(42,46,57,0.3)] transition-default" : ""}`}
      style={{ borderColor: "rgba(42,46,57,0.3)" }}
    >
      <span className="text-sm" style={{ color: "#d1d4dc" }}>
        {label}
      </span>
      {children ?? (
        <span
          className="font-mono text-sm tabular-nums"
          style={{ color: valueColor ?? "#787b86" }}
        >
          {value}
        </span>
      )}
    </Component>
  );
}

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label: string;
}

export function Toggle({ checked, onChange, disabled = false, label }: ToggleProps) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative h-[30px] w-[50px] flex-shrink-0 rounded-full transition-all duration-200 active:scale-95 disabled:opacity-40"
      style={{
        backgroundColor: checked ? "#2962ff" : "rgba(120,123,134,0.3)",
      }}
    >
      <span
        className="absolute top-[3px] left-[3px] h-[24px] w-[24px] rounded-full bg-white shadow-sm transition-transform duration-200"
        style={{
          transform: checked ? "translateX(20px)" : "translateX(0)",
        }}
      />
    </button>
  );
}

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
  last?: boolean;
}

export function SliderRow({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
  last = false,
}: SliderRowProps) {
  return (
    <div
      className={`flex flex-col gap-2 px-4 py-3 ${last ? "" : "border-b"}`}
      style={{ borderColor: "rgba(42,46,57,0.3)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm" style={{ color: "#d1d4dc" }}>
          {label}
        </span>
        <span className="font-mono text-sm tabular-nums" style={{ color: "#2962ff" }}>
          {value}{unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[#2962ff]"
        style={{ height: "4px" }}
        aria-label={`${label}: ${value}${unit}`}
      />
    </div>
  );
}
