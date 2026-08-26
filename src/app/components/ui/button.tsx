import { forwardRef, type ButtonHTMLAttributes, type CSSProperties } from "react";
import { cn } from "./utils";

type ButtonVariant = "primary" | "danger" | "ghost" | "tint-success" | "tint-danger";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Dims to 0.6 opacity while an async action is in flight, matching the auth pages' pending state. */
  pending?: boolean;
}

const VARIANT_STYLE: Record<ButtonVariant, CSSProperties> = {
  primary: { backgroundColor: "var(--pr-authority-blue)", color: "#fff" },
  danger: { backgroundColor: "var(--pr-critical-red)", color: "#fff" },
  ghost: { backgroundColor: "transparent", color: "var(--pr-text-muted)" },
  "tint-success": { backgroundColor: "rgba(34,197,94,0.1)", color: "var(--pr-trust-green)" },
  "tint-danger": { backgroundColor: "rgba(239,68,68,0.1)", color: "var(--pr-critical-red)" },
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  md: "px-4 py-2 rounded-lg text-sm font-medium",
  sm: "px-3 py-1.5 rounded-lg text-xs",
};

/**
 * The button treatment repeated across ~11 files. `disabled` on a
 * primary/danger button falls back to the same "muted, looks inert"
 * bg-hover/text-muted pair every call site already re-implemented by hand
 * (e.g. the Publish button before a policy has compiled).
 *
 * Final Product Polish: React.forwardRef -- this project targets React 18
 * (no automatic ref-as-prop; see sheet.tsx's own fix for the same class of
 * bug), and a caller managing focus (e.g. returning focus to the button
 * that opened a now-closed drawer) needs a real DOM ref to focus.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", pending, className, style, disabled, ...rest },
  ref
) {
  const disabledStyle: CSSProperties =
    disabled && (variant === "primary" || variant === "danger")
      ? { backgroundColor: "var(--pr-bg-hover)", color: "var(--pr-text-muted)" }
      : {};
  return (
    <button
      ref={ref}
      className={cn(variant !== "ghost" && SIZE_CLASS[size], className)}
      disabled={disabled}
      style={{
        ...VARIANT_STYLE[variant],
        ...disabledStyle,
        opacity: pending ? 0.6 : undefined,
        ...style,
      }}
      {...rest}
    />
  );
});
