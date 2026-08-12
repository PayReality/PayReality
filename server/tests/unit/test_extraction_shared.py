"""Unit tests for extraction_shared.py's Phase 3 additions
(EXPLAINABILITY_MODEL.md): the four explainability fields on every
entity/relationship/policy item, and conflict_type on Conflicts. Pure,
DB-free -- schema construction and dict-parsing only."""

from app.domain.ai_authority_builder.extraction_shared import (
    build_system_prompt,
    build_tool_schema,
    parse_graph_input,
)


def test_system_prompt_instructs_on_explainability_fields():
    prompt = build_system_prompt()
    assert "clause_reference" in prompt
    assert "extraction_reasoning" in prompt
    assert "detected_assumptions" in prompt
    assert "ambiguity_flags" in prompt
    assert "conflict_type" in prompt


def test_tool_schema_adds_explainability_fields_to_every_entity_item():
    schema = build_tool_schema()
    for item_key in ("policies", "principals", "resources", "operations", "relationships"):
        props = schema["properties"][item_key]["items"]["properties"]
        for field in ("clause_reference", "extraction_reasoning", "detected_assumptions", "ambiguity_flags"):
            assert field in props, f"{item_key} item is missing {field}"


def test_tool_schema_conflict_item_has_conflict_type_enum():
    schema = build_tool_schema()
    conflict_props = schema["properties"]["conflicts"]["items"]["properties"]
    assert conflict_props["conflict_type"]["enum"] == [
        "authority", "threshold", "role", "policy", "delegation", "circular_delegation",
    ]
    assert "conflict_type" in schema["properties"]["conflicts"]["items"]["required"]


def test_tool_schema_never_gains_a_rego_or_deploy_field():
    """The explainability additions must not weaken the existing
    structural guarantee: still no field anywhere suggesting Rego,
    deployment, or activation."""
    import json

    schema_text = json.dumps(build_tool_schema()).lower()
    assert "rego" not in schema_text
    assert "deploy" not in schema_text
    assert "\"activate\"" not in schema_text


def _minimal_item(**overrides):
    base = {"confidence": 0.8, "source_excerpt": "e", "source_location": "l"}
    base.update(overrides)
    return base


def test_parse_graph_input_reads_explainability_fields_when_present():
    graph_input = {
        "policies": [], "resources": [], "operations": [], "relationships": [],
        "gaps": [], "questions": [],
        "principals": [
            _minimal_item(
                name="CFO",
                clause_reference="Clause 4.2",
                extraction_reasoning="Stated explicitly.",
                detected_assumptions=["Assumed 'the CFO' refers to the named officer."],
                ambiguity_flags=["Could also mean the acting CFO."],
            )
        ],
        "conflicts": [
            {"description": "d", "confidence": 0.9, "conflict_type": "threshold"},
        ],
    }
    graph = parse_graph_input(graph_input)
    principal = graph.principals[0]
    assert principal.clause_reference == "Clause 4.2"
    assert principal.extraction_reasoning == "Stated explicitly."
    assert principal.detected_assumptions == ("Assumed 'the CFO' refers to the named officer.",)
    assert principal.ambiguity_flags == ("Could also mean the acting CFO.",)
    assert graph.conflicts[0].conflict_type == "threshold"


def test_parse_graph_input_defaults_explainability_fields_when_absent():
    """Backward compatibility: a raw dict from before this schema change
    (or a provider that hasn't adopted the new prompt) must still parse,
    with these fields at null/empty defaults -- never a KeyError."""
    graph_input = {
        "policies": [], "resources": [], "operations": [], "relationships": [],
        "gaps": [], "questions": [], "conflicts": [],
        "principals": [_minimal_item(name="CFO")],
    }
    graph = parse_graph_input(graph_input)
    principal = graph.principals[0]
    assert principal.clause_reference is None
    assert principal.extraction_reasoning is None
    assert principal.detected_assumptions == ()
    assert principal.ambiguity_flags == ()
