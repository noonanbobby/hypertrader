"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const pathname = usePathname();
  const [displayChildren, setDisplayChildren] = useState(children);
  const [transitioning, setTransitioning] = useState(false);
  const prevPathname = useRef(pathname);

  useEffect(() => {
    if (pathname !== prevPathname.current) {
      setTransitioning(true);
      const timer = setTimeout(() => {
        setDisplayChildren(children);
        setTransitioning(false);
        prevPathname.current = pathname;
      }, 100);
      return () => clearTimeout(timer);
    } else {
      setDisplayChildren(children);
    }
  }, [pathname, children]);

  return (
    <div
      className="transition-all duration-200 ease-out"
      style={{
        opacity: transitioning ? 0.6 : 1,
        transform: transitioning ? "translateY(4px)" : "translateY(0)",
      }}
    >
      {displayChildren}
    </div>
  );
}
