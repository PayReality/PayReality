import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

export type HelpTab = "getting_started" | "learn" | "search" | "troubleshooting" | "developer" | "contact";

const STORAGE_KEY = "payreality_getting_started_done";

function loadDoneSteps(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

interface HelpContextValue {
  isOpen: boolean;
  activeTab: HelpTab;
  // Set when a contextual HelpIcon or search result opens the Learn tab
  // pointed at one specific article, so that article can be expanded/
  // scrolled to automatically. Cleared once the panel has consumed it.
  focusedArticleId: string | null;
  openHelp: (tab?: HelpTab) => void;
  closeHelp: () => void;
  setActiveTab: (tab: HelpTab) => void;
  openLearnArticle: (articleId: string) => void;
  clearFocusedArticle: () => void;
  doneSteps: Set<string>;
  markStepDone: (stepId: string) => void;
  toggleStep: (stepId: string) => void;
  // Live-QA fix: the element that had focus right before the panel opened
  // (a HelpButton, a HelpIcon's "Learn more", a search result), so the
  // panel can hand focus back to it on close. Needed because HelpPanel's
  // Sheet is opened from outside its own tree via this context rather
  // than a Radix Trigger inside it, so Radix's own trigger-focus-restore
  // (@radix-ui/react-dialog's context.triggerRef) never fires and focus
  // was silently dropping to <body> instead, the same failure mode the
  // mobile nav drawer in Layout.tsx already had to work around explicitly.
  lastFocusedRef: RefObject<HTMLElement | null>;
}

const HelpContext = createContext<HelpContextValue | null>(null);

export function HelpProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTabState] = useState<HelpTab>("getting_started");
  const [focusedArticleId, setFocusedArticleId] = useState<string | null>(null);
  const [doneSteps, setDoneSteps] = useState<Set<string>>(() => loadDoneSteps());
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(doneSteps)));
  }, [doneSteps]);

  function rememberFocus() {
    lastFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }

  function openHelp(tab?: HelpTab) {
    rememberFocus();
    if (tab) setActiveTabState(tab);
    setIsOpen(true);
  }

  function closeHelp() {
    setIsOpen(false);
  }

  function setActiveTab(tab: HelpTab) {
    setActiveTabState(tab);
  }

  function openLearnArticle(articleId: string) {
    rememberFocus();
    setFocusedArticleId(articleId);
    setActiveTabState("learn");
    setIsOpen(true);
  }

  function clearFocusedArticle() {
    setFocusedArticleId(null);
  }

  function markStepDone(stepId: string) {
    setDoneSteps((prev) => {
      if (prev.has(stepId)) return prev;
      const next = new Set(prev);
      next.add(stepId);
      return next;
    });
  }

  function toggleStep(stepId: string) {
    setDoneSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  }

  return (
    <HelpContext.Provider
      value={{
        isOpen,
        activeTab,
        focusedArticleId,
        openHelp,
        closeHelp,
        setActiveTab,
        openLearnArticle,
        clearFocusedArticle,
        doneSteps,
        markStepDone,
        toggleStep,
        lastFocusedRef,
      }}
    >
      {children}
    </HelpContext.Provider>
  );
}

export function useHelp(): HelpContextValue {
  const context = useContext(HelpContext);
  if (!context) throw new Error("useHelp must be used within HelpProvider");
  return context;
}
