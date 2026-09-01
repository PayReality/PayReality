"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "./utils";

// Product Experience V3.2, section 4: collapsed navigation shows icons
// only, so every one needs a real, accessible name on both hover AND
// keyboard focus -- a native `title` attribute alone does not reliably
// show on keyboard focus across browsers, which is why this exists
// rather than reusing `title`. Radix's own Trigger already forwards
// focus/blur to open/close the tooltip, so no extra keyboard handling
// is written here.
function TooltipProvider({
  delayDuration = 200,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider data-slot="tooltip-provider" delayDuration={delayDuration} {...props} />;
}

function Tooltip({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return (
    <TooltipProvider>
      <TooltipPrimitive.Root data-slot="tooltip" {...props} />
    </TooltipProvider>
  );
}

function TooltipTrigger({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

// React 18.3.1 (no automatic ref-as-prop support until React 19):
// forwardRef, the same fix Sheet's own SheetOverlay/SheetContent
// already needed for Radix's Presence/SlotClone machinery.
const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 8, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      data-slot="tooltip-content"
      sideOffset={sideOffset}
      className={cn(
        "z-50 overflow-hidden rounded-md px-2.5 py-1.5 text-xs font-medium shadow-md",
        "data-[state=delayed-open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=delayed-open]:zoom-in-95",
        className
      )}
      style={{
        backgroundColor: "var(--pr-bg-secondary)",
        color: "var(--pr-text-primary)",
        border: "1px solid var(--pr-overlay-10)",
        transitionDuration: "var(--pr-motion-fast)",
      }}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
