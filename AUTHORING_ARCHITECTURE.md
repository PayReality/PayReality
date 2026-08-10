# Authoring Architecture

Design only. No code has changed as a result of this document. This is the overarching design; `POLICY_LANGUAGE_SPEC.md`, `POLICY_COMPILER_V2.md`, and `POLICY_STUDIO.md` go deep on the DSL, the compiler, and the editor respectively. Read this one first.

## A naming collision this design resolves before going further

The directive's canonical model is called **Runtime Policy**, and its own example is a single rule: one action, one set of conditions, one name ("Vendor Payment"). That is the same granularity as today's `Authority` row, not today's `Policy` row. Today's `Policy` table means something different: a whole compiled, versioned, activatable bundle containing many Mandates (one per approved Authority) plus the Rego that evaluates all of them together, exactly one of which can be `active` at a time.

Calling the new per-rule object "Runtime Policy" while an existing table named `Policy` already means "a compiled bundle version" would make every future conversation ambiguous: "policy" would mean two different granularities depending on who's talking. This document resolves it explicitly rather than let it surface later as a confused data model:

- **Runtime Policy** = the new canonical, authoring-method-agnostic representation of *one authored rule* (one action, one set of conditions, one name). This is the direct successor to today's `Authority`: every authoring mode (wizard, manual, AI) produces one or more Runtime Policies, exactly the way every authoring path today eventually produces one or more Authority rows.
- **Policy Bundle** (today's `Policy` table, recommended renamed at the database/API level when this is actually built, not before) = the compiled, versioned, activatable unit containing every Runtime Policy compiled together into one Rego module, exactly what `Policy` already means today. Nothing about its lifecycle (`draft` → `compiled` → `active` → `retired`, exactly one active at a time, `bundle_hash` determinism) changes.

This mapping means the migration is smaller than it sounds: **`Authority` becomes `Runtime Policy`, expanded to carry a real condition language instead of a mostly-inert `conditions` JSONB array** (see the compiler finding below for why "mostly inert" is the accurate description of today's state, not an exaggeration). `Mandate` stays exactly what it is: the compiled, per-Runtime-Policy row inside an active bundle. `Policy` stays exactly what it is: the bundle. Nothing at the runtime-evaluation layer (OPA, the Decision Engine, Evidence signing) needs to know authoring modes exist at all, they only ever see compiled Mandates and a Rego bundle, exactly as `domain/decision/engine.py` does today.

## The three authoring modes, and how each produces a Runtime Policy

### Mode 1: Guided Wizard (unchanged behavior)

This described the document-upload → AI-extraction → human-review flow this section was originally written against (`LiveDocuments.tsx`, `document_service.py`, `review_service.py`). **Update:** `LiveDocuments.tsx` and the write endpoints it depended on were later fully retired (`SPECIFICATION/17_LEGACY_COMPONENTS.md`); its route now redirects to `/governance/upload`. The AI Authority Builder and AI Policy Builder (Modes 2/3 below) are the live successors to what this mode originally described, not an unchanged parallel path.

What changes underneath, invisibly to this mode's users: an approved `Authority` row is the same thing as a Runtime Policy now, just produced by a different authoring path than modes 2 and 3. Today's `Authority` → `Mandate` compilation step becomes "compile a Runtime Policy," the same operation modes 2 and 3 trigger. This mode doesn't get a new UI, a new review step, or new fields it didn't already have; it gets a renamed underlying model and a shared compiler, both invisible to its users.

### Mode 2: Manual Policy Authoring (Policy Studio, new)

A new page where a technical-enough user (a policy administrator, not necessarily an engineer) directly authors a Runtime Policy in a small, purpose-built language, described fully in `POLICY_LANGUAGE_SPEC.md`. Never exposes Rego. Full editor design in `POLICY_STUDIO.md`.

### Mode 3: AI Policy Builder (new, broader documents)

Upload a PDF, DOCX, delegation matrix, or authority framework document (a broader document-type set than mode 1's single-DoA-letter assumption, and potentially multi-principal/multi-rule documents rather than one document per Principal). AI extraction proposes one or more Runtime Policies (not Authority rows directly, the canonical model from the start). A human reviews and approves before anything compiles or deploys, same principle as mode 1, applied to the new canonical model and a wider document intake.

Whether mode 3 is a genuinely separate code path from mode 1, or mode 1 becomes "mode 3, scoped to single-DoA-letter PDFs, with its existing UI kept unchanged" is an open implementation question, not an architecture question: both produce Runtime Policies via AI extraction plus human review. This document treats them as two entry points to the same underlying extraction-and-review mechanism, generalized to a broader document/output shape; `POLICY_COMPILER_V2.md` and the refactor sequencing don't need to resolve this before the model itself is agreed on.

## The canonical Runtime Policy model, conceptually

```
RuntimePolicy
  id
  name                    "Vendor Payment"
  domain_adapter          "financial" (see DOMAIN_ABSTRACTION.md; this field
                           is what a future Insurance/Identity/etc. adapter
                           would set instead)
  principal_id            who this delegates authority to act for
  action                  must be a recognized scope for the active adapter
                           (KNOWN_SCOPES today; adapter-owned per
                           DOMAIN_REFACTOR_PLAN.md item 2)
  conditions               a structured condition tree (see
                           POLICY_LANGUAGE_SPEC.md), not a string, not Rego
  authoring_mode           "wizard" | "manual" | "ai_builder"
  status                   "draft" | "pending_review" | "approved" |
                           "rejected" | "compiled" | "active" | "retired"
  source_document_id       nullable; set for wizard/ai_builder, null for
                           manual authoring
  author                   identity of whoever authored/edited this
                           revision (see Versioning below)
  version metadata         see Versioning section
```

This is deliberately close to today's `Authority` row plus a real `conditions` structure instead of a mostly-inert JSONB array. It is not a from-scratch redesign.

## Compiler separation

```
Authoring (any of the 3 modes)
        ↓
   Runtime Policy   (persisted, versioned, reviewable, the same object
                      regardless of which mode produced it)
        ↓
     Compiler         (one compiler; see POLICY_COMPILER_V2.md for why
                      this is a materially bigger compiler than today's,
                      not just a reorganization)
        ↓
      Rego            (generated per active adapter's rule shape)
        ↓
      OPA             (unchanged; still just evaluates whatever Rego and
                      data it's given, exactly as today)
```

The compiler never knows or cares which authoring mode produced a given Runtime Policy. It only ever sees the canonical model. This is the same separation principle as `DOMAIN_ABSTRACTION.md`'s engine/adapter boundary, applied one layer up: just as the Decision Engine doesn't know about Financial vs. a future Insurance adapter, the Compiler doesn't know about Wizard vs. Manual vs. AI Builder.

## Validation pipeline, and where each check actually happens

| Check | When | What it catches |
|---|---|---|
| Schema validation | On save (draft), before anything else | Malformed YAML/DSL, missing required fields, wrong types. Purely structural; doesn't need to know what `amount` means. |
| Semantic validation | On save, after schema validation passes | References to fields or actions the active domain adapter doesn't recognize (e.g. a typo'd action name, a condition field the adapter has no concept of). Requires the adapter's vocabulary; see `DOMAIN_ABSTRACTION.md`. |
| Dry-run evaluation | On demand ("Test Policy"), and again automatically before Compile | Runs a sample Intent against the draft Runtime Policy's compiled-but-not-activated Rego, without touching the live active bundle. Full design in `POLICY_COMPILER_V2.md`, this is the part of this system that doesn't exist at all today and needs real design, not just reorganization. |
| Conflict detection | Before Compile | Whether this Runtime Policy contradicts or overlaps ambiguously with another already-approved one for the same principal/action. `POLICY_COMPILER_V2.md` is explicit about the bounded, practical scope of what's actually detectable here versus what would require a general theorem prover. |
| Version comparison | Before Deploy | A structural diff against the currently-active version, for human review before activation, not an automated gate, a display aid for a human approver to see exactly what's changing. |

## Versioning

Every Runtime Policy revision, and every compiled bundle, carries:

- **Version number**: monotonically increasing per Runtime Policy (not per bundle; a single Runtime Policy edited three times has versions 1, 2, 3, independent of how many bundle activations happened in between).
- **Author**: the identity that created or edited this revision. Until real human authentication exists (see `VERSION_3_ROADMAP.md`'s Enterprise Pilot phase), this is the same free-text-identity limitation `resolved_by`/`reviewer_id` already have; this design doesn't pretend to solve that here, it inherits the same honest gap.
- **Timestamp**.
- **Change summary**: free text, required on save if this is an edit to an existing Runtime Policy (not required on first creation).
- **Previous version pointer**: so a rollback (see below) and a version-comparison diff both have something concrete to point at.
- **Rollback capability**: reactivating a previous Runtime Policy version, and recompiling the bundle from that reactivated set, exactly the same *mechanism* as today's Policy Bundle rollback (`POST /v1/policies/{id}/activate` on a retired version, see `ARCHITECTURE.md`), extended to work at the per-Runtime-Policy granularity as well as the whole-bundle granularity.

## How this connects to the domain-abstraction work

This entire design assumes `DOMAIN_REFACTOR_PLAN.md`'s item 2 (adapter-owned action vocabulary) and item 3 (adapter-aware compiler) either exist already or land alongside this work, since:

- Semantic validation needs to ask "the active adapter" what actions and condition-fields are valid, exactly the vocabulary question item 2 already addresses.
- The compiler generating Rego from arbitrary Runtime Policy conditions is exactly the generalization item 3 already calls for, just with a fuller job description than that plan originally scoped (see `POLICY_COMPILER_V2.md`).

These two efforts should be sequenced together, not as two unrelated initiatives that happen to both touch the compiler.

## Risk and migration summary

- **Biggest risk**: today's `conditions` field is not, in fact, mostly enforced. See `POLICY_COMPILER_V2.md`'s compiler-capability finding: only one specific pattern (`requires_dual_approval_above_N`) is ever read by the Rego template; everything else is stored and never evaluated. Building a real condition language that's actually compiled into enforceable Rego is new compiler capability, not a reorganization of existing capability. Budget for this accordingly; it is the single largest piece of net-new engineering in this whole initiative.
- **Second risk**: dry-run evaluation against a draft, uncompiled, unactivated policy doesn't exist today in any form (OPA today only ever holds the one active bundle's data). This needs a genuinely new evaluation path, detailed in `POLICY_COMPILER_V2.md`.
- **Lower risk, still real**: renaming/reframing `Authority` as `Runtime Policy` at the data-model level, while keeping mode 1's UX completely unchanged, is mechanical but touches a table with a foreign-key relationship to `Mandate`, `Constraint`, and the extraction pipeline; treat it as its own isolated migration step, not bundled with the new compiler capability.
- **Sequencing recommendation**: build the condition language and the generalized compiler (mode 2's core dependency) before building mode 3's broader document intake, since mode 3 only becomes valuable once there's a real target model to extract into; building broader document parsing before the model it feeds is stable would be built twice.
