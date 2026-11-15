import { Dialog as Radix } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "../../lib/cn";

// A copied-in shadcn-style dialog over Radix: modal, focus trapped, Escape cancels, and the
// focus goes back to what opened it. Drawn with our tokens (the mockup's sign dialog).

export const Dialog = Radix.Root;

/**
 * The overlay and the panel. `container` is where it is mounted: the trace view passes its own
 * root, so the screen's stylesheet (its buttons) reaches the dialog.
 */
export function DialogContent({
  container,
  className,
  children,
  ...props
}: ComponentProps<typeof Radix.Content> & { container?: HTMLElement | null }) {
  return (
    <Radix.Portal container={container ?? undefined}>
      <Radix.Overlay className="fixed inset-0 z-40 bg-[var(--scrim)]" />
      <Radix.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(480px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-sheet border border-rule bg-sheet p-6 text-ink shadow-[var(--lift)]",
          className,
        )}
        {...props}
      >
        {children}
      </Radix.Content>
    </Radix.Portal>
  );
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof Radix.Title>) {
  return <Radix.Title className={cn("text-21 leading-tight font-bold", className)} {...props} />;
}

export function DialogDescription({
  className,
  ...props
}: ComponentProps<typeof Radix.Description>) {
  return <Radix.Description className={cn("mt-2", className)} {...props} />;
}
