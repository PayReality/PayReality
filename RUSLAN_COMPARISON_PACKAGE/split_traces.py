"""Splits tests/integration/_interop_evidencebound_recovery_v01_output/traces.jsonl
(produced by running test_interop_evidencebound_recovery_v01.py from the server/ directory)
into the four schedule-labeled files under traces/ in this package. A mechanical relabeling
by each record's own "schedule" field -- never alters, reorders, or filters a recorded value.

Usage, from the repository's server/ directory, after running:
    pytest tests/integration/test_interop_evidencebound_recovery_v01.py

    python ../RUSLAN_COMPARISON_PACKAGE/split_traces.py

Resolves its source path relative to the CURRENT WORKING DIRECTORY (assumed to be server/,
per the usage above), not relative to this script's own on-disk location -- so running it
against a different checkout (e.g. an isolated worktree used for verification) correctly reads
that checkout's own freshly-generated trace, not a stale copy sitting next to this script in
whichever checkout it happens to be committed in. This was a real bug in an earlier version of
this script, found by actually running it against a worktree during verification.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.getcwd(), "tests", "integration",
                    "_interop_evidencebound_recovery_v01_output", "traces.jsonl")
OUT_DIR = os.path.join(_HERE, "traces")

GROUPS = {
    "1": "schedule_1_late_commitment_after_revocation.jsonl",
    "2": "schedule_2_unresolved_outcome_after_revocation.jsonl",
    "material": "material_action_binding_enforcement.jsonl",
    "race": "capability_consumption_concurrency.jsonl",
}


def main():
    records = [json.loads(line) for line in open(SRC, encoding="utf-8") if line.strip()]
    buckets = {key: [] for key in GROUPS}
    for record in records:
        buckets[record["schedule"]].append(record)

    for key, filename in GROUPS.items():
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            for record in buckets[key]:
                f.write(json.dumps(record) + "\n")
        print(f"{filename}: {len(buckets[key])} records")


if __name__ == "__main__":
    main()
