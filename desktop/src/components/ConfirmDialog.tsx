import { useEffect, useId, useRef } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

// A confirmation prompt built on the browser's own <dialog>, so the page behind it is inert (no focus,
// no clicks), Escape is a real "cancel" event, and the prompt sits above everything else.
//
// What this component adds on top of the browser:
//  - a name and a description for assistive technology (role="alertdialog", labelled by the title,
//    described by the body and the details);
//  - initial focus on Cancel, the safe answer;
//  - Escape and Cancel only ever dismiss; they never confirm. While a request is in flight Escape does
//    nothing, because dismissing the prompt would not unsend it;
//  - focus returns to the control that opened it (or to a named fallback if that control is gone).
//
// It does not decide what confirming does. The caller owns that, and owns closing the prompt when the
// thing it asked about is no longer true.
export function ConfirmDialog({
  title, body, details = [], danger, busy, onCancel, onConfirm, returnFocusTo,
}: {
  title: string;
  body: string;
  /** Extra lines naming what exactly will be affected, such as the printer and the file. */
  details?: string[];
  danger: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  /** Where focus goes when the prompt closes. Called at that moment, so it can check the control still exists. */
  returnFocusTo: () => HTMLElement | null;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descId = useId();
  // The latest values, read from handlers that must not be re-created on every render.
  const live = useRef({ busy, onCancel, returnFocusTo });
  live.current = { busy, onCancel, returnFocusTo };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    // `hasAttribute` rather than `.open`: the attribute is the standard, observable state.
    if (!dialog.hasAttribute("open")) dialog.showModal();
    cancelRef.current?.focus();
    return () => {
      if (dialog.hasAttribute("open")) dialog.close();
      live.current.returnFocusTo()?.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={descId}
      className="fixed left-1/2 top-1/2 m-0 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-background p-5 text-foreground shadow-xl backdrop:bg-black/50"
      onCancel={(e) => {
        // Escape. Never let the browser close it by itself: the caller decides, and a request in
        // flight keeps the prompt on screen.
        e.preventDefault();
        if (!live.current.busy) live.current.onCancel();
      }}
    >
      <p id={titleId} className={`text-sm font-semibold ${danger ? "text-risk" : ""}`}>{title}</p>
      <div id={descId}>
        <p className="mt-2 text-xs text-muted-foreground">{body}</p>
        {details.map((line) => (
          <p key={line} className="mt-1 text-xs font-medium text-foreground">{line}</p>
        ))}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button ref={cancelRef} type="button" size="sm" variant="secondary" disabled={busy} onClick={onCancel}>Cancel</Button>
        <Button type="button" size="sm" variant={danger ? "danger" : "primary"} disabled={busy} onClick={onConfirm}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} {danger ? "Yes, do it" : "Confirm"}
        </Button>
      </div>
    </dialog>
  );
}
