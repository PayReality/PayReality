import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TourStep } from "./steps";

interface Props {
  step: TourStep;
  stepIndex: number;
  total: number;
  onNext: () => void;
  onPrev: () => void;
  onStop: () => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Highlights an existing element in place (a ring + spotlight dim, via a giant box-shadow -- no clip-path needed) and floats a small tooltip beside it. Never blocks clicks on the target itself. */
export function TourOverlay({ step, stepIndex, total, onNext, onPrev, onStop }: Props) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // A fixed height guess (the bug a real-browser walkthrough caught: step
  // 4's body text alone is taller than any guess low enough to fit under
  // a target near the bottom of a tall page, pushing Next/Back off
  // screen). Measure the dialog's own real height instead, per step,
  // since body copy length varies step to step.
  const [dialogHeight, setDialogHeight] = useState(220);
  useLayoutEffect(() => {
    if (dialogRef.current) setDialogHeight(dialogRef.current.offsetHeight);
  });

  useEffect(() => {
    setRect(null);
    let cancelled = false;
    let attempts = 0;
    function measure() {
      if (cancelled) return;
      const el = document.querySelector(step.selector);
      if (el) {
        // Scroll positioning: a target below the fold (routine on a long
        // Decision Detail or Receipt page) would otherwise leave the
        // highlight ring drawn around something the visitor can't see,
        // with the tooltip clamped to whatever's on-screen instead.
        el.scrollIntoView?.({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
        setRect(el.getBoundingClientRect());
      } else if (attempts < 20) {
        attempts += 1;
        window.setTimeout(measure, 100);
      }
    }
    measure();
    function onReflow() {
      const el = document.querySelector(step.selector);
      if (el) setRect(el.getBoundingClientRect());
    }
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      cancelled = true;
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
  }, [step]);

  // Accessibility (section 31): a screen-reader or keyboard user needs
  // focus to actually land somewhere when a new step appears, not just a
  // visual highlight, otherwise the dialog's content is discoverable
  // only by accident. The dialog itself is focusable (tabIndex=-1, never
  // in the natural tab order) purely as a focus target.
  useEffect(() => {
    // preventScroll is true because the dialog is position:fixed
    // (already viewport-relative, never part of document flow), so the
    // browser's default focus-triggered scroll-into-view has nothing
    // useful to do here and only fights the target element's own
    // scrollIntoView call above, which is the one that actually needs
    // to move the page.
    dialogRef.current?.focus({ preventScroll: true });
  }, [step]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onStop();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onStop]);

  const isNarrow = typeof window !== "undefined" && window.innerWidth < 420;
  const tooltipWidth = isNarrow ? Math.min(320, window.innerWidth - 32) : 320;
  const roomBelow = rect ? window.innerHeight - rect.bottom - 12 : 0;
  const roomAbove = rect ? rect.top - 12 : 0;
  // Prefer below the target (reads as "here's more detail on what you
  // just saw"); flip above only when below genuinely can't fit the
  // dialog's real height but above can, never picking a side that clips.
  const placeAbove = rect ? roomBelow < dialogHeight && roomAbove > roomBelow : false;
  const tooltipStyle = rect
    ? isNarrow
      ? // Mobile (section 20/29): a rect-relative position risks the
        // tooltip overlapping the very content it's explaining on a
        // short viewport. Anchor to the bottom of the screen instead,
        // clear of the highlighted target, the same predictable place
        // every step.
        { bottom: 16, left: 16, right: 16, width: "auto" as const }
      : placeAbove
        ? {
            top: Math.max(16, rect.top - dialogHeight - 12),
            left: Math.min(Math.max(rect.left, 16), window.innerWidth - tooltipWidth - 16),
          }
        : {
            top: Math.min(rect.bottom + 12, Math.max(16, window.innerHeight - dialogHeight - 16)),
            left: Math.min(Math.max(rect.left, 16), window.innerWidth - tooltipWidth - 16),
          }
    : { bottom: 24, left: "50%", transform: "translateX(-50%)" };

  return (
    <>
      {rect && (
        <div
          aria-hidden="true"
          style={{
            position: "fixed",
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            border: "2px solid var(--pr-authority-blue)",
            borderRadius: 8,
            pointerEvents: "none",
            zIndex: 90,
            boxShadow: "0 0 0 4000px rgba(7,17,31,0.55)",
            transition: prefersReducedMotion() ? "none" : "top 200ms ease, left 200ms ease",
          }}
        />
      )}
      <div
        ref={dialogRef}
        role="dialog"
        aria-label={`Guided demo, step ${stepIndex + 1} of ${total}: ${step.title}`}
        tabIndex={-1}
        style={{
          position: "fixed",
          width: tooltipWidth,
          ...tooltipStyle,
          zIndex: 91,
          backgroundColor: "var(--pr-bg-card)",
          border: "1px solid var(--pr-overlay-10)",
          borderRadius: 12,
          padding: 16,
          boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          outline: "none",
          // A hard floor under the top/bottom placement math above: even
          // if a future step's body copy is longer than any position
          // guess accounts for, the dialog scrolls internally rather
          // than ever pushing its own Next/Back controls off-screen.
          maxHeight: "calc(100vh - 32px)",
          overflowY: "auto",
        }}
      >
        <div className="flex items-center gap-1.5 mb-2" aria-hidden="true">
          {Array.from({ length: total }, (_, i) => (
            <span
              key={i}
              style={{
                width: i === stepIndex ? 14 : 5,
                height: 5,
                borderRadius: 3,
                backgroundColor: i === stepIndex ? "var(--pr-authority-blue)" : "var(--pr-overlay-10)",
                transition: prefersReducedMotion() ? "none" : "width 150ms ease",
              }}
            />
          ))}
        </div>
        <p className="text-xs font-mono uppercase tracking-widest mb-1.5" style={{ color: "var(--pr-authority-blue)" }}>
          Step {stepIndex + 1} of {total}
        </p>
        <p className="text-sm font-semibold mb-1.5" style={{ color: "var(--pr-text-primary)" }}>{step.title}</p>
        <p className="text-sm mb-4" style={{ color: "var(--pr-text-secondary)", lineHeight: 1.5 }}>{step.body}</p>
        <div className="flex items-center justify-between">
          <button type="button" onClick={onStop} className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
            Skip tour
          </button>
          <div className="flex gap-2">
            {stepIndex > 0 && (
              <button
                type="button"
                onClick={onPrev}
                className="px-3 py-1.5 rounded-lg text-xs"
                style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
              >
                Back
              </button>
            )}
            <button
              type="button"
              onClick={onNext}
              className="px-3 py-1.5 rounded-lg text-xs font-medium"
              style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
            >
              {stepIndex === total - 1 ? "Finish" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
