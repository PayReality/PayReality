import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ChevronDown, ExternalLink, Search } from "lucide-react";
import { Card } from "../components/ui/card";
import { Sheet, SheetContent, SheetTitle } from "../components/ui/sheet";
import { useHelp, type HelpTab } from "./HelpContext";
import {
  CONTACT_ACTIONS,
  DEVELOPER_RESOURCES,
  GETTING_STARTED_STEPS,
  LEARN_ARTICLES,
  TROUBLESHOOTING_GUIDES,
} from "./content";
import { categoryLabel, searchHelp, type SearchResult } from "./search";

const TABS: Array<{ id: HelpTab; label: string }> = [
  { id: "getting_started", label: "Getting Started" },
  { id: "learn", label: "Learn" },
  { id: "search", label: "Search" },
  { id: "troubleshooting", label: "Troubleshooting" },
  { id: "developer", label: "Developer" },
  { id: "contact", label: "Contact" },
];

const cardStyle: React.CSSProperties = {
  backgroundColor: "var(--pr-bg-card)",
  border: "1px solid var(--pr-overlay-05)",
  borderRadius: 10,
};

function openExternal(href: string) {
  window.open(href, "_blank", "noopener,noreferrer");
}

function GettingStartedTab({ onNavigate }: { onNavigate: (path: string) => void }) {
  const { doneSteps, markStepDone, toggleStep } = useHelp();
  const doneCount = GETTING_STARTED_STEPS.filter((s) => doneSteps.has(s.id)).length;

  return (
    <div>
      <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
        {doneCount} of {GETTING_STARTED_STEPS.length} complete
      </p>
      <div className="h-1 rounded-full mb-4 overflow-hidden" style={{ backgroundColor: "var(--pr-overlay-06)" }}>
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${(doneCount / GETTING_STARTED_STEPS.length) * 100}%`,
            backgroundColor: "var(--pr-trust-green)",
          }}
        />
      </div>
      <div className="space-y-2">
        {GETTING_STARTED_STEPS.map((step) => {
          const done = doneSteps.has(step.id);
          return (
            <Card key={step.id} radius={10} padding={12} className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={done}
                onChange={() => toggleStep(step.id)}
                className="mt-0.5 flex-shrink-0"
                aria-label={`Mark "${step.label}" as done`}
              />
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => {
                    markStepDone(step.id);
                    onNavigate(step.path);
                  }}
                  className="text-sm font-medium text-left"
                  style={{
                    color: done ? "var(--pr-text-muted)" : "var(--pr-authority-blue)",
                    textDecoration: done ? "line-through" : "none",
                  }}
                >
                  {step.label}
                </button>
                <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{step.description}</p>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function LearnTab() {
  const { focusedArticleId, clearFocusedArticle } = useHelp();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!focusedArticleId) return;
    setExpandedId(focusedArticleId);
    const el = refs.current[focusedArticleId];
    el?.scrollIntoView({ block: "start", behavior: "smooth" });
    clearFocusedArticle();
  }, [focusedArticleId, clearFocusedArticle]);

  return (
    <div className="space-y-2">
      {LEARN_ARTICLES.map((article) => {
        const expanded = expandedId === article.id;
        return (
          <div
            key={article.id}
            ref={(el) => { refs.current[article.id] = el; }}
            style={cardStyle}
          >
            <button
              type="button"
              onClick={() => setExpandedId(expanded ? null : article.id)}
              className="w-full flex items-center justify-between p-3 text-left"
              aria-expanded={expanded}
            >
              <span>
                <span className="block text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{article.term}</span>
                <span className="block text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{article.summary}</span>
              </span>
              <ChevronDown
                className="w-4 h-4 flex-shrink-0 ml-2 transition-transform"
                style={{ color: "var(--pr-text-disabled)", transform: expanded ? "rotate(180deg)" : "none" }}
              />
            </button>
            {expanded && (
              <p className="px-3 pb-3 text-xs" style={{ color: "var(--pr-text-secondary)", lineHeight: 1.6 }}>
                {article.body}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SearchTab({ onResult }: { onResult: (result: SearchResult) => void }) {
  const [query, setQuery] = useState("");
  const results = searchHelp(query);

  return (
    <div>
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg mb-4"
        style={{ backgroundColor: "var(--pr-input-bg)", border: "1px solid var(--pr-overlay-08)" }}
      >
        <Search className="w-4 h-4 flex-shrink-0" style={{ color: "var(--pr-text-disabled)" }} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search help articles (e.g. agent, policy, evidence)"
          className="w-full text-sm bg-transparent outline-none"
          style={{ color: "var(--pr-text-primary)" }}
          autoFocus
        />
      </div>

      {query.trim() && results.length === 0 && (
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No help articles matched "{query}".</p>
      )}

      <div className="space-y-2">
        {results.map((result) => (
          <button
            key={`${result.category}-${result.id}`}
            type="button"
            onClick={() => onResult(result)}
            className="w-full text-left p-3 rounded-lg"
            style={cardStyle}
          >
            <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: "var(--pr-authority-blue)" }}>
              {categoryLabel(result.category)}
            </span>
            <span className="block text-sm font-medium mt-0.5" style={{ color: "var(--pr-text-primary)" }}>{result.title}</span>
            <span className="block text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{result.snippet}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TroubleshootingTab({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="space-y-2">
      {TROUBLESHOOTING_GUIDES.map((guide) => {
        const expanded = expandedId === guide.id;
        return (
          <Card key={guide.id} radius={10}>
            <button
              type="button"
              onClick={() => setExpandedId(expanded ? null : guide.id)}
              className="w-full flex items-center justify-between p-3 text-left"
              aria-expanded={expanded}
            >
              <span>
                <span className="block text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{guide.issue}</span>
                <span className="block text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{guide.explanation}</span>
              </span>
              <ChevronDown
                className="w-4 h-4 flex-shrink-0 ml-2 transition-transform"
                style={{ color: "var(--pr-text-disabled)", transform: expanded ? "rotate(180deg)" : "none" }}
              />
            </button>
            {expanded && (
              <div className="px-3 pb-3">
                <ol className="list-decimal list-inside space-y-1 mb-2">
                  {guide.steps.map((step, i) => (
                    <li key={i} className="text-xs" style={{ color: "var(--pr-text-secondary)", lineHeight: 1.5 }}>{step}</li>
                  ))}
                </ol>
                {guide.path && (
                  <button
                    type="button"
                    onClick={() => onNavigate(guide.path!)}
                    className="text-xs font-medium"
                    style={{ color: "var(--pr-authority-blue)" }}
                  >
                    Go to the relevant page →
                  </button>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function DeveloperTab() {
  return (
    <div className="space-y-2">
      {DEVELOPER_RESOURCES.map((resource) => (
        <button
          key={resource.id}
          type="button"
          onClick={() => openExternal(resource.href)}
          className="w-full text-left p-3 rounded-lg flex items-start justify-between gap-2"
          style={cardStyle}
        >
          <span>
            <span className="block text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{resource.label}</span>
            <span className="block text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{resource.description}</span>
          </span>
          <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-text-disabled)" }} />
        </button>
      ))}
    </div>
  );
}

function ContactTab({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <div className="space-y-2">
      {CONTACT_ACTIONS.map((action) => (
        <button
          key={action.id}
          type="button"
          onClick={() => (action.href.startsWith("/") ? onNavigate(action.href) : openExternal(action.href))}
          className="w-full text-left p-3 rounded-lg flex items-start justify-between gap-2"
          style={cardStyle}
        >
          <span>
            <span className="block text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{action.label}</span>
            <span className="block text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{action.description}</span>
          </span>
          {!action.href.startsWith("/") && (
            <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-text-disabled)" }} />
          )}
        </button>
      ))}
    </div>
  );
}

export function HelpPanel() {
  const { isOpen, closeHelp, activeTab, setActiveTab, openLearnArticle, lastFocusedRef } = useHelp();
  const navigate = useNavigate();

  function goTo(path: string) {
    closeHelp();
    navigate(path);
  }

  function handleSearchResult(result: SearchResult) {
    if (result.path) {
      goTo(result.path);
    } else if (result.articleId) {
      openLearnArticle(result.articleId);
    } else if (result.href) {
      if (result.href.startsWith("/")) goTo(result.href);
      else openExternal(result.href);
    }
  }

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && closeHelp()}>
      <SheetContent
        side="right"
        className="w-[420px] max-w-[92vw] flex flex-col p-0 gap-0 border-l"
        style={{ backgroundColor: "var(--pr-bg-secondary)", borderColor: "var(--pr-overlay-05)" }}
        onCloseAutoFocus={(e) => {
          // Live-QA fix: this Sheet is opened from outside its own tree
          // (HelpButton, a HelpIcon, a search result), never through a
          // Radix Trigger inside it, so Radix's built-in trigger-focus
          // restore has nothing to focus and silently drops focus to
          // <body> on close. Restore it to whatever really opened the
          // panel instead.
          e.preventDefault();
          lastFocusedRef.current?.focus();
        }}
      >
        <SheetTitle className="sr-only">Help Center</SheetTitle>

        <div className="px-5 py-4 border-b" style={{ borderColor: "var(--pr-overlay-05)" }}>
          <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Help Center</h2>
          <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>
            Guidance for using PayReality, without leaving this page.
          </p>
        </div>

        <div className="flex flex-wrap gap-1 px-3 pt-3 border-b" style={{ borderColor: "var(--pr-overlay-05)" }}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className="text-xs px-2.5 py-1.5 rounded-t-lg"
              style={{
                color: activeTab === tab.id ? "var(--pr-text-primary)" : "var(--pr-text-muted)",
                borderBottom: activeTab === tab.id ? "2px solid var(--pr-authority-blue)" : "2px solid transparent",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {activeTab === "getting_started" && <GettingStartedTab onNavigate={goTo} />}
          {activeTab === "learn" && <LearnTab />}
          {activeTab === "search" && <SearchTab onResult={handleSearchResult} />}
          {activeTab === "troubleshooting" && <TroubleshootingTab onNavigate={goTo} />}
          {activeTab === "developer" && <DeveloperTab />}
          {activeTab === "contact" && <ContactTab onNavigate={goTo} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}
