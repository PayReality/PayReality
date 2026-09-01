import { useTour } from "../demo/tour/TourProvider";

// Elegant, not a warning: this is a feature of the deployment, not an
// error state, so it uses the brand accent, not amber/critical tokens.
export function DemoBanner() {
  const { start } = useTour();
  return (
    <div
      className="flex items-center justify-center gap-3 flex-wrap px-4 py-2 text-center"
      style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff", fontSize: 13 }}
    >
      <span>
        <strong className="font-semibold">Interactive Product Demonstration</strong>
        {" -- "}
        This environment contains fictional organisations, users, transactions and policies created solely for demonstration purposes.
      </span>
      <button
        type="button"
        onClick={start}
        className="px-2.5 py-1 rounded-md text-xs font-medium flex-shrink-0"
        // Product Experience V3.2, Part E: a translucent WHITE overlay on
        // top of the already-light authority-blue banner measured
        // 2.88:1 with white text, below WCAG AA -- lightening this
        // further only made the underlying 3.73:1 problem worse. A
        // translucent BLACK overlay darkens the composited background
        // instead, reaching ~5.2:1, while keeping the same "distinct
        // pill on the banner" visual affordance.
        style={{ backgroundColor: "rgba(0,0,0,0.18)", color: "#fff" }}
      >
        Start Guided Demo
      </button>
    </div>
  );
}
