"use client";

interface LogoProps {
  size?: number;
  className?: string;
  glow?: boolean;
}

const basePath = process.env.__NEXT_ROUTER_BASEPATH || "/mobile";

export function Logo({ size = 80, className = "", glow = false }: LogoProps) {
  return (
    <div className={`relative ${className}`}>
      {glow && (
        <div
          className="absolute -inset-6 rounded-full opacity-20 blur-xl"
          style={{ backgroundColor: "#2962ff" }}
          aria-hidden="true"
        />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${basePath}/icons/icon-512.png`}
        alt="HyperTrader"
        width={size}
        height={size}
        className="relative rounded-[22%]"
        draggable={false}
      />
    </div>
  );
}
