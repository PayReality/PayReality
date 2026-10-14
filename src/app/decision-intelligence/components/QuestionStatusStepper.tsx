import { formatStatus } from "../../live/format";
import { QUESTION_STATUS_ORDER, type QuestionStatus } from "../types";

const STEP_LABEL: Record<QuestionStatus, string> = {
  proposed: "Proposed",
  in_analysis: "In analysis",
  awaiting_answer: "Awaiting answer",
  answer_submitted: "Answer submitted",
  approved: "Answer approved",
  logic_drafted: "Logic drafted",
  logic_validated: "Logic validated",
  replay_completed: "Replay completed",
  ready_for_review: "Ready for review",
  approved_for_operational_use: "Approved for operational use",
};

/**
 * The Priority Question's 10-value lifecycle (DIQuestion.status, a fixed
 * product vocabulary -- di_question_service.py's own module docstring)
 * rendered as a real stepper, not raw status text: a reviewer needs to
 * see both where a question IS and how far it has to go before it can
 * govern a real Decision Rule.
 */
export function QuestionStatusStepper({ status }: { status: QuestionStatus }) {
  const currentIndex = QUESTION_STATUS_ORDER.indexOf(status);
  return (
    <div className="flex flex-wrap items-center gap-1" role="list" aria-label="Question lifecycle status">
      {QUESTION_STATUS_ORDER.map((step, i) => {
        const done = i < currentIndex;
        const active = i === currentIndex;
        const color = active ? "var(--pr-authority-blue)" : done ? "var(--pr-trust-green)" : "var(--pr-overlay-10)";
        return (
          <div key={step} role="listitem" className="flex items-center gap-1">
            <span
              aria-current={active ? "step" : undefined}
              title={STEP_LABEL[step]}
              style={{
                display: "inline-block",
                width: active ? 10 : 7,
                height: active ? 10 : 7,
                borderRadius: 999,
                backgroundColor: color,
              }}
            />
            {i < QUESTION_STATUS_ORDER.length - 1 && (
              <span style={{ width: 10, height: 1, backgroundColor: done ? "var(--pr-trust-green)" : "var(--pr-overlay-10)" }} />
            )}
          </div>
        );
      })}
      <span className="ml-2 text-xs font-medium" style={{ color: "var(--pr-text-primary)" }}>
        {formatStatus(status)}
      </span>
    </div>
  );
}

export { STEP_LABEL as QUESTION_STATUS_LABEL };
