import type { LivePrincipal, PrincipalAuthorityContext } from "../../live/types";
import { ORG_NAME } from "./organization";

export const PRINCIPAL_OKONKWO = "principal-okonkwo";
export const PRINCIPAL_RUIZ = "principal-ruiz";
export const PRINCIPAL_WEBB = "principal-webb";
export const PRINCIPAL_CHANDRASEKARAN = "principal-chandrasekaran";

export const demoPrincipals: LivePrincipal[] = [
  { id: PRINCIPAL_OKONKWO, name: "David Okonkwo", role: "Head of Treasury", created_at: "2025-02-10T09:00:00Z" },
  { id: PRINCIPAL_RUIZ, name: "Elena Ruiz", role: "VP, Procurement", created_at: "2025-02-10T09:00:00Z" },
  { id: PRINCIPAL_WEBB, name: "Marcus Webb", role: "Chief Information Security Officer", created_at: "2025-02-10T09:00:00Z" },
  { id: PRINCIPAL_CHANDRASEKARAN, name: "Priya Chandrasekaran", role: "Chief Financial Officer", created_at: "2025-02-10T09:00:00Z" },
];

const DELEGATION_FROM_CFO = {
  id: "delegation-cfo-to-treasury",
  from_principal_id: PRINCIPAL_CHANDRASEKARAN,
  resource_id: "resource-ap-ledger",
  operation: "vendor_payment",
};

export const demoAuthorityContextByPrincipal: Record<string, PrincipalAuthorityContext> = {
  [PRINCIPAL_OKONKWO]: {
    organization: ORG_NAME,
    business_unit: "Corporate Services",
    department: "Finance",
    team: "Treasury",
    role: "Head of Treasury",
    delegations: [DELEGATION_FROM_CFO],
  },
  [PRINCIPAL_RUIZ]: {
    organization: ORG_NAME,
    business_unit: "Corporate Services",
    department: "Procurement",
    team: "Vendor Management",
    role: "VP, Procurement",
    delegations: [],
  },
  [PRINCIPAL_WEBB]: {
    organization: ORG_NAME,
    business_unit: "Corporate Services",
    department: "Security & Compliance",
    team: null,
    role: "Chief Information Security Officer",
    delegations: [],
  },
  [PRINCIPAL_CHANDRASEKARAN]: {
    organization: ORG_NAME,
    business_unit: "Corporate Services",
    department: "Finance",
    team: null,
    role: "Chief Financial Officer",
    delegations: [],
  },
};
