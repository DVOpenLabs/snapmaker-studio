// When does a route change start a new page at the top? Pure, so the rule is testable without a router.

/** A different path is a different page and starts at the top. The same path (a query, state or hash
 *  change, or re-selecting the page you are on) keeps its place, and a hash link scrolls to its anchor. */
export function shouldResetScroll(prevPath: string | null, nextPath: string, hash: string): boolean {
  if (prevPath === null) return false;       // first render: nothing to reset
  if (hash) return false;                    // an in-page anchor decides the position itself
  return prevPath !== nextPath;
}
