import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "./utils";

/**
 * Visual System V3, section 19/26: the shared shell for the native
 * `<table>` markup every list page (Agent Directory, Decision History,
 * and others this audit found) currently hand-rolls independently, all
 * converging on the same shape already (`w-full text-sm`, a muted
 * uppercase header row, a hairline divider between rows). Centralizing
 * the shape, not the data: every column definition, sort control, and
 * row action stays exactly where it is today, page by page; this is
 * about density and long-value handling reading the same way
 * everywhere, not a new abstraction over what each table actually shows.
 */
export function Table({ className, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full text-sm", className)} style={{ color: "var(--pr-text-primary)" }} {...rest} />;
}

export function TableHead({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={className} {...rest} />;
}

export function TableBody({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={className} {...rest} />;
}

export function TableRow({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(className)}
      style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
      {...rest}
    />
  );
}

export function TableHeaderCell({ className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn("text-left font-medium py-2 px-3 text-xs uppercase tracking-wide", className)}
      style={{ color: "var(--pr-text-muted)" }}
      {...rest}
    />
  );
}

// Section 19 (data density): long identifiers/action names/resource
// strings must never blow out a column, truncate with a native title
// tooltip by default; a caller with a genuine reason to wrap (a
// multi-line reason/description column) passes `truncate={false}`.
export function TableCell({ className, truncate = true, ...rest }: TdHTMLAttributes<HTMLTableCellElement> & { truncate?: boolean }) {
  return (
    <td
      className={cn("py-2.5 px-3 align-top", truncate && "max-w-0 truncate", className)}
      title={truncate && typeof rest.children === "string" ? rest.children : undefined}
      {...rest}
    />
  );
}
