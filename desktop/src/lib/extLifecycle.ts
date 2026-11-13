export type AppStartHandler = () => void;
export type BeforeUnloadHandler = (event: BeforeUnloadEvent) => void;
export type VisibilityChangeHandler = (visible: boolean) => void;

type EventHandlers = {
  start: Set<AppStartHandler>;
  beforeunload: Set<BeforeUnloadHandler>;
  visibility: Set<VisibilityChangeHandler>;
};

type LifecycleEventTarget = Pick<EventTarget, "addEventListener">;
type LifecycleDocumentTarget = LifecycleEventTarget & { visibilityState: string };
type AppLifecycleTarget = {
  window: LifecycleEventTarget;
  document: LifecycleDocumentTarget;
};

const handlers: EventHandlers = { start: new Set(), beforeunload: new Set(), visibility: new Set() };
let started = false;
let installed = false;

function subscribe<T extends (...args: any[]) => void>(set: Set<T>, handler: T): () => void {
  set.add(handler);
  return () => set.delete(handler);
}

function notify<T extends (...args: any[]) => void>(set: Set<T>, ...args: Parameters<T>): void {
  for (const handler of [...set]) {
    try { handler(...args); }
    catch (error) { console.error("Application lifecycle subscriber failed", error); }
  }
}

/** App-start replays synchronously to subscribers that arrive after startup. */
export function onAppStart(handler: AppStartHandler): () => void {
  const unsubscribe = subscribe(handlers.start, handler);
  if (started) {
    try { handler(); }
    catch (error) { console.error("Application lifecycle subscriber failed", error); }
  }
  return unsubscribe;
}

export function onBeforeUnload(handler: BeforeUnloadHandler): () => void {
  return subscribe(handlers.beforeunload, handler);
}

export function onVisibilityChange(handler: VisibilityChangeHandler): () => void {
  return subscribe(handlers.visibility, handler);
}

/** Install the three application lifecycle sources once for the process lifetime. */
export function installAppLifecycle(target?: AppLifecycleTarget): void {
  if (installed) return;
  installed = true;
  const windowTarget = target?.window ?? (typeof window === "undefined" ? undefined : window);
  const documentTarget = target?.document ?? (typeof document === "undefined" ? undefined : document);
  windowTarget?.addEventListener("beforeunload", (event) => {
    notify(handlers.beforeunload, event as BeforeUnloadEvent);
  });
  documentTarget?.addEventListener("visibilitychange", () => {
    const visible = documentTarget.visibilityState === "visible";
    notify(handlers.visibility, visible);
  });
  started = true;
  notify(handlers.start);
}

/** Isolated module-state reset for lifecycle unit tests only. */
export function __resetAppLifecycleForTests(): void {
  handlers.start.clear(); handlers.beforeunload.clear(); handlers.visibility.clear();
  started = false;
  installed = false;
}
