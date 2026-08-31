import { useState } from "react";
import { useNavigate } from "react-router";
import { ShieldCheck, Lock, FileCheck, Building2, ArrowRight, ChevronDown } from "lucide-react";
import { useTour } from "./tour/TourProvider";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { ORG_NAME } from "./fixtures/organization";
import { track } from "../services/analytics";

const VALUE_BULLETS = [
  { icon: ShieldCheck, label: "Denied unauthorized payments" },
  { icon: Lock, label: "Verified delegated authority" },
  { icon: Building2, label: "Independently reported operations" },
  { icon: FileCheck, label: "Cryptographic Evidence" },
  { icon: Building2, label: "Enterprise Governance" },
];

// Demo V2 (Trusted Authority Story): the three-question model is now the
// primary explanation of what PayReality does. The "nine AI agents"
// world (last explainer below) is retained as supporting context, per
// this milestone's own instruction, not as the lead.
const EXPLAINERS = [
  {
    key: "three-questions",
    title: "The three questions PayReality answers",
    body: "Agent: who is acting? Trusted Adapter: what company-controlled component is reporting what action is being attempted? PayReality: has the organization actually authorized that agent to do this, under these conditions? PayReality only ever answers the third question. It never claims the Adapter proves the action happened, and it never assumes an agent is trustworthy just because a Trusted Adapter exists.",
  },
  {
    key: "architecture",
    title: "Platform Architecture",
    body: "Runtime Authority evaluates every AI agent's requested action before it reaches production systems (ERPs, procurement platforms, identity systems) and returns a deterministic Allow, Deny, or Human Review decision. It is not a logging layer bolted on after the fact; it is a decision made in time for an enterprise's own systems to act on it before the consequence exists. Every decision produces signed Evidence, and, for a specific decision, an Authorization Receipt that packages Evidence, authority, and (where a Trusted Connection was involved) integration provenance into one shareable view.",
  },
  {
    key: "runtime-authority",
    title: "Runtime Authority Explained",
    body: "Most AI governance today checks a role name. Runtime Authority checks a continuous chain: who delegated what, to whom, under which conditions, and whether this specific action still falls within it, at the moment the action is attempted, not in a quarterly audit.",
  },
  {
    key: "enterprise-ai",
    title: "Enterprise AI Architecture",
    body: `At ${ORG_NAME}, nine AI agents act across Finance, Procurement, and IT, each operating under a named human's delegated authority, each action checked against active policy, each outcome evidenced. This is what "AI workforce" looks like with real governance underneath it.`,
  },
];

export function DemoLanding() {
  const navigate = useNavigate();
  const { start } = useTour();
  const [openExplainer, setOpenExplainer] = useState<string | null>(null);

  return (
    <div className="p-8 max-w-3xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-10 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--pr-authority-blue)" }}>
            {ORG_NAME} &middot; Runtime Authority Platform
          </span>
        </div>
        <h1 className="text-3xl font-bold mb-4" style={{ color: "var(--pr-text-primary)", lineHeight: 1.25, textWrap: "balance" }}>
          An AI agent tries to change a supplier's bank details. Does your organization actually authorize that?
        </h1>
        <p style={{ color: "var(--pr-text-muted)", fontSize: 15, maxWidth: 560 }}>
          PayReality, the Enterprise AI Authority Infrastructure, checks every AI-initiated action against real
          delegated authority and enterprise policy, before it executes, then produces a signed, verifiable
          record of the decision. It doesn't observe or prove what happens afterward inside the enterprise
          system itself; it decides, and proves that it decided.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-10">
        {VALUE_BULLETS.map((v) => {
          const Icon = v.icon;
          return (
            <div key={v.label} className="flex items-center gap-2">
              <Icon className="w-4 h-4 flex-shrink-0" style={{ color: "var(--pr-trust-green)" }} />
              <span className="text-xs" style={{ color: "var(--pr-text-secondary)" }}>{v.label}</span>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-3 mb-12">
        <Button variant="primary" onClick={start}>
          Start Guided Demo <span aria-hidden="true" className="ml-1">(~3 min)</span>
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            track("Demo Landing Explore Platform Clicked");
            navigate("/overview");
          }}
          className="border"
          style={{ borderColor: "var(--pr-overlay-10)" }}
        >
          Explore Platform <ArrowRight className="inline w-3.5 h-3.5 ml-1" />
        </Button>
      </div>

      <div className="space-y-2">
        {EXPLAINERS.map((e) => {
          const open = openExplainer === e.key;
          return (
            <Card key={e.key} padding={0} style={{ overflow: "hidden" }}>
              <button
                type="button"
                onClick={() => {
                  if (!open) track("Demo Landing Explainer Opened", { explainer: e.key });
                  setOpenExplainer(open ? null : e.key);
                }}
                aria-expanded={open}
                className="w-full flex items-center justify-between px-5 py-4 text-left"
              >
                <span className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{e.title}</span>
                <ChevronDown
                  className="w-4 h-4 flex-shrink-0"
                  style={{ color: "var(--pr-text-muted)", transform: open ? "rotate(180deg)" : undefined, transition: "transform 150ms ease" }}
                />
              </button>
              {open && (
                <p className="px-5 pb-4 text-sm" style={{ color: "var(--pr-text-secondary)", lineHeight: 1.6 }}>
                  {e.body}
                </p>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
