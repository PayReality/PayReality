import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { aiPolicyBuilderApi } from "./api";
import type { Candidate } from "./types";
import { CandidateCard } from "./components/CandidateCard";
import { AiComingSoonBanner } from "../components/AiComingSoonBanner";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { FileCode2 } from "lucide-react";

export function AIPolicyBuilderReviewPage() {
  const { uploadId } = useParams();
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [aiEnabled, setAiEnabled] = useState(true);

  function load() {
    aiPolicyBuilderApi.listCandidatesForUpload(uploadId!).then(setCandidates);
  }

  useEffect(load, [uploadId]);
  useEffect(() => {
    aiPolicyBuilderApi.getStatus().then((s) => setAiEnabled(s.ai_enabled));
  }, []);

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to="/governance/upload" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to uploads
      </Link>
      <PageHeader
        title={`Candidate Runtime Policies (${candidates?.length ?? 0})`}
        description="AI-proposed, not yet real authority. Review, edit, and promote each candidate individually."
      />

      {!aiEnabled && <AiComingSoonBanner />}

      {candidates?.length === 0 && (
        <EmptyState
          icon={FileCode2}
          title="No candidates found"
          description="This can be a valid outcome: a scanned, non-text PDF, or a document with nothing matching a known action."
        />
      )}

      {candidates?.map((c) => (
        <CandidateCard key={c.candidate_id} candidate={c} onChanged={load} />
      ))}
    </div>
  );
}
