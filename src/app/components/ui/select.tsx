import { forwardRef, type CSSProperties, type SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "./utils";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  containerClassName?: string;
  containerStyle?: CSSProperties;
}

/**
 * Final Product Polish: the one genuinely repeated native-select styling
 * problem across the app (filter bars on Decisions/Agents/Governance, the
 * Test Runtime Authority drawer) -- every `<select>` already carried the
 * same colors/border/radius as the inputs around it, but kept the
 * browser's own default dropdown arrow, which reads as template chrome
 * next to the rest of the redesigned surface. This wraps the real,
 * native `<select>` (full keyboard/screen-reader semantics, nothing
 * reimplemented) and only replaces the arrow -- `appearance: none` plus
 * a lucide ChevronDown positioned over it. Deliberately unopinionated
 * about color/border/width beyond that: every caller keeps its own
 * existing className/style exactly as before, so migrating a call site
 * changes nothing but the arrow. Not a generic listbox component: no
 * options-rendering, no search, no multi-select -- if that's ever
 * genuinely needed, it belongs in a different primitive, not scope
 * creep on this one.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, style, containerClassName, containerStyle, ...rest },
  ref
) {
  return (
    <div className={cn("relative inline-block", containerClassName)} style={containerStyle}>
      <select
        ref={ref}
        className={cn(className)}
        style={{
          ...style,
          // Deliberately spread after `style`, not before: several call
          // sites set `padding` as a shorthand (e.g. "6px 10px"), and a
          // shorthand applied after a longhand resets it -- paddingRight
          // reserving room for the chevron below needs to win regardless
          // of how the caller expressed its own padding.
          appearance: "none",
          WebkitAppearance: "none",
          paddingRight: 30,
        }}
        {...rest}
      />
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 -translate-y-1/2"
        style={{ right: 9, width: 14, height: 14, color: "var(--pr-text-muted)" }}
      />
    </div>
  );
});
