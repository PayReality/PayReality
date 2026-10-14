// Shown only when VITE_PROTOTYPE_MODE=true is baked in at build time
// (the isolated Decision Intelligence prototype deployment). Never set
// for the real demo or dashboard builds.
export function PrototypeBanner() {
  return (
    <div
      className="flex items-center justify-center gap-3 flex-wrap px-4 py-2 text-center"
      style={{ backgroundColor: "var(--pr-warning-amber, #92400e)", color: "#fff", fontSize: 13 }}
    >
      <span>
        <strong className="font-semibold">Prototype: Decision Intelligence.</strong>{" "}
        Patterns and priority questions are manually entered by a reviewer; there is no automated
        AI discovery. All data in this environment is fictional and created for review only.
      </span>
    </div>
  );
}
