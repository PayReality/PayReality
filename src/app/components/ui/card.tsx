import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { cn } from "./utils";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padding?: number;
  borderColor?: string;
  radius?: number;
}

/** The card shell repeated near-verbatim across the app (bg-card + hairline border). */
export function Card({
  children,
  className,
  style,
  padding = 20,
  borderColor = "var(--pr-overlay-05)",
  radius = 12,
  ...rest
}: CardProps) {
  const mergedStyle: CSSProperties = {
    backgroundColor: "var(--pr-bg-card)",
    border: `1px solid ${borderColor}`,
    borderRadius: radius,
    padding,
    // Visual Experience V2: a restrained depth cue (theme.css's
    // --pr-shadow-card) so a card reads as a raised surface against the
    // page background, not a second flat rectangle sharing its border
    // color. `boxShadow` in `style` (a caller passing its own, or "none")
    // still wins via the spread below -- this is a default, not a floor.
    boxShadow: "var(--pr-shadow-card)",
    ...style,
  };
  return (
    <div className={cn(className)} style={mergedStyle} {...rest}>
      {children}
    </div>
  );
}
