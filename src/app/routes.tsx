import { createBrowserRouter, Navigate, Outlet, useParams } from "react-router";
import { Layout } from "./components/Layout";
import { NotFound } from "./pages/NotFound";
import { RouteErrorBoundary } from "./pages/RouteErrorBoundary";
import { RequireAuth } from "./auth/RequireAuth";
import { DEMO_MODE } from "./demo/config";

// Compile/Dry Run/Deploy and Diff were merged into Publish and Versions
// respectively (PAYREALITY_UX_REVIEW.md); these keep the old URLs from
// 404ing for anyone with a bookmark or an external link.
function RedirectToPublish() {
  const { policyKey } = useParams();
  return <Navigate to={`/governance/${policyKey}/publish`} replace />;
}
function RedirectToVersions() {
  const { policyKey } = useParams();
  return <Navigate to={`/governance/${policyKey}/versions`} replace />;
}

// /authority and /policy-studio were the URL slugs from before the UX
// rename to "Agents" and "Governance" (see the git history on Layout.tsx's
// nav labels). These two splat routes catch every old nested path
// (/authority/:agentId, /policy-studio/:policyKey/publish, etc.) and
// redirect to the same path under the new top-level segment, so no old
// bookmark or external link 404s.
function RedirectAuthoritySplat() {
  const params = useParams();
  const rest = params["*"];
  return <Navigate to={`/agents${rest ? `/${rest}` : ""}`} replace />;
}
function RedirectPolicyStudioSplat() {
  const params = useParams();
  const rest = params["*"];
  return <Navigate to={`/governance${rest ? `/${rest}` : ""}`} replace />;
}

// A single shared gate for every route below except /login and
// /setup-owner: the whole app now requires a real human session, not just
// Organisation Settings/Users. One wrapper here means any route added
// under it in the future is gated automatically -- no risk of a new page
// forgetting its own RequireAuth wrap, which was the failure mode of the
// old per-route pattern. The Operator Key remains a separate, API-level
// bypass (verify_operator_key/require_permission, server side); this
// gate only controls what the browser renders for a human with no
// session, and doesn't touch that at all.
function ProtectedLayout() {
  return (
    <RequireAuth>
      <Outlet />
    </RequireAuth>
  );
}

// Every real page is code-split by route: the initial bundle only needs
// the shell (Layout) and whichever single page a visitor actually
// requested, instead of eagerly loading Policy Studio, both AI builders,
// and every Live page up front.
export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    errorElement: <RouteErrorBoundary />,
    children: [
      // Phase 10 (RBAC.md): the only two routes reachable without a
      // session. /setup-owner claims the bootstrapped Owner account using
      // the Operator Key, which is how a session comes to exist in the
      // first place on a fresh deployment.
      { path: "login", lazy: () => import("./auth/LoginPage").then((m) => ({ Component: m.LoginPage })) },
      { path: "setup-owner", lazy: () => import("./auth/SetupOwnerPage").then((m) => ({ Component: m.SetupOwnerPage })) },

      {
        Component: ProtectedLayout,
        children: [
          // The public demo's index route is a dedicated front-door
          // (hero + guided-tour entry point), not the real dashboard --
          // production's "/" is completely untouched. "overview" is a
          // second, always-present route to the real PlatformOverview so
          // the demo landing's "Explore Platform" CTA (and production)
          // both have a stable target.
          {
            index: true,
            lazy: () =>
              DEMO_MODE
                ? import("./demo/DemoLanding").then((m) => ({ Component: m.DemoLanding }))
                : import("./pages/PlatformOverview").then((m) => ({ Component: m.PlatformOverview })),
          },
          { path: "overview", lazy: () => import("./pages/PlatformOverview").then((m) => ({ Component: m.PlatformOverview })) },
          // Phase 9 (AGENT_LIFECYCLE.md): the Agent Directory + Detail pages
          // replaced the earlier flat Live Agents list/register-only page.
          { path: "agents", lazy: () => import("./agents/AgentDirectoryPage").then((m) => ({ Component: m.AgentDirectoryPage })) },
          { path: "agents/:agentId", lazy: () => import("./agents/AgentDetailPage").then((m) => ({ Component: m.AgentDetailPage })) },
          { path: "decisions", lazy: () => import("./live/pages/LiveTestIntent").then((m) => ({ Component: m.LiveTestIntent })) },
          { path: "evidence", lazy: () => import("./live/pages/LiveEvidence").then((m) => ({ Component: m.LiveEvidence })) },
          { path: "assurance", lazy: () => import("./live/pages/LiveAssurance").then((m) => ({ Component: m.LiveAssurance })) },

          { path: "organization", lazy: () => import("./organization/OrganizationSettingsPage").then((m) => ({ Component: m.OrganizationSettingsPage })) },
          { path: "organization/users", lazy: () => import("./organization/UsersPage").then((m) => ({ Component: m.UsersPage })) },

          // Policy Studio is the single entry point for all policy work: manual
          // authoring, the AI Authority Builder (multi-document corpus
          // analysis), the single-document AI Policy Builder it superseded as
          // the primary surface (kept mounted for backward compatibility), and
          // the legacy delegation-of-authority review flow, all nested here
          // rather than as separate top-level nav items (see PolicyListPage's
          // own entry-point links).
          { path: "governance", lazy: () => import("./policy-studio/PolicyListPage").then((m) => ({ Component: m.PolicyListPage })) },
          { path: "governance/approvals", lazy: () => import("./policy-studio/ReviewQueuePage").then((m) => ({ Component: m.ReviewQueuePage })) },
          { path: "governance/new", lazy: () => import("./policy-studio/PolicyWorkspacePage").then((m) => ({ Component: m.PolicyWorkspacePage })) },
          { path: "governance/upload", lazy: () => import("./ai-policy-builder/UploadPage").then((m) => ({ Component: m.AIPolicyBuilderUploadPage })) },
          { path: "governance/upload/:uploadId", lazy: () => import("./ai-policy-builder/ReviewPage").then((m) => ({ Component: m.AIPolicyBuilderReviewPage })) },
          { path: "governance/authority-builder", lazy: () => import("./ai-authority-builder/CorpusUploadPage").then((m) => ({ Component: m.AIAuthorityBuilderUploadPage })) },
          { path: "governance/authority-builder/:corpusId", lazy: () => import("./ai-authority-builder/CorpusReviewPage").then((m) => ({ Component: m.AIAuthorityBuilderCorpusReviewPage })) },
          // The legacy Authority/Mandate document-review page (LiveDocuments)
          // and its backing endpoints were retired (PHASE_0.md): the write
          // path it depended on now returns 410. /governance/legacy-review
          // and every old alias below redirect to the modern equivalent.
          { path: "governance/legacy-review", element: <Navigate to="/governance/upload" replace /> },
          { path: "governance/:policyKey", lazy: () => import("./policy-studio/PolicyWorkspacePage").then((m) => ({ Component: m.PolicyWorkspacePage })) },
          // Version History + Diff merged into one page (PAYREALITY_UX_REVIEW.md);
          // Compile + Dry Run + Deploy merged into one Publish page, same reason.
          { path: "governance/:policyKey/versions", lazy: () => import("./policy-studio/VersionsPage").then((m) => ({ Component: m.VersionsPage })) },
          { path: "governance/:policyKey/publish", lazy: () => import("./policy-studio/PublishPage").then((m) => ({ Component: m.PublishPage })) },
          // Runtime Policy Simulator (Authority Intelligence Program, Phase 4,
          // POLICY_SIMULATOR.md): a dry run of Runtime Authority for a
          // hypothetical Intent against this specific policy version.
          { path: "governance/:policyKey/simulate", lazy: () => import("./policy-simulation/SimulationPage").then((m) => ({ Component: m.PolicySimulationPage })) },
          // Old separate URLs redirect rather than 404 for anyone with a bookmark.
          { path: "governance/:policyKey/diff", element: <RedirectToVersions /> },
          { path: "governance/:policyKey/compile", element: <RedirectToPublish /> },
          { path: "governance/:policyKey/dry-run", element: <RedirectToPublish /> },
          { path: "governance/:policyKey/deploy", element: <RedirectToPublish /> },

          // Old /authority and /policy-studio URLs redirect to their renamed
          // equivalents (see the two splat components above).
          { path: "authority", element: <Navigate to="/agents" replace /> },
          { path: "authority/*", element: <RedirectAuthoritySplat /> },
          { path: "policy-studio", element: <Navigate to="/governance" replace /> },
          { path: "policy-studio/review-queue", element: <Navigate to="/governance/approvals" replace /> },
          { path: "policy-studio/*", element: <RedirectPolicyStudioSplat /> },

          // Legacy paths from the pre-consolidation app, kept as redirects so
          // no external link or bookmark 404s. See audit/EXECUTION_REPORT.md.
          { path: "platform-overview", element: <Navigate to="/" replace /> },
          { path: "command-center", element: <Navigate to="/assurance" replace /> },
          { path: "dashboard", element: <Navigate to="/assurance" replace /> },
          { path: "authority-center", element: <Navigate to="/agents" replace /> },
          { path: "ai-agents-registry", element: <Navigate to="/agents" replace /> },
          { path: "ai-agents", element: <Navigate to="/agents" replace /> },
          { path: "decision-intercepts", element: <Navigate to="/decisions" replace /> },
          { path: "evidence-vault", element: <Navigate to="/evidence" replace /> },
          { path: "policy", element: <Navigate to="/governance/upload" replace /> },
          { path: "policy-library", element: <Navigate to="/governance/upload" replace /> },
          { path: "policy-center", element: <Navigate to="/governance/upload" replace /> },
          { path: "ai-policy-builder", element: <Navigate to="/governance/authority-builder" replace /> },
          { path: "governance-simulation", element: <Navigate to="/decisions" replace /> },
          { path: "approvals", element: <Navigate to="/decisions" replace /> },
          { path: "assurance-center", element: <Navigate to="/assurance" replace /> },
          { path: "insurance-readiness", element: <Navigate to="/assurance" replace /> },
          { path: "settings", element: <Navigate to="/organization" replace /> },
          { path: "live", element: <Navigate to="/" replace /> },
          { path: "live/documents", element: <Navigate to="/governance/upload" replace /> },
          { path: "live/agents", element: <Navigate to="/agents" replace /> },
          { path: "live/test-intent", element: <Navigate to="/decisions" replace /> },
          { path: "live/evidence", element: <Navigate to="/evidence" replace /> },

          { path: "*", Component: NotFound },
        ],
      },
    ],
  },
]);
