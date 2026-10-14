"""Decision Intelligence (module prefix `DI`): a deliberately PARALLEL,
isolated product module alongside the existing Runtime Authority domain
(Principal/Agent/Intent/RuntimePolicy/Decision Engine/Evidence) in this
same codebase, never merged into it.

Runtime Authority enforces a live AI action against an already-authored
rule. Decision Intelligence is the upstream discipline of discovering,
from real recurring cases, the smallest set of questions an organisation
actually needs to answer before a rule can be authored at all. The two
concepts only sound alike in English ("policy", "decision") -- this
module shares no table with Runtime Authority, and reuses only
Organization/User (multi-tenancy, authorship) and the RBAC permission
system from the rest of this codebase, by design."""
