// Studio-authored (not upstream). The vendored viewport calls `new Error(message, { cause })`, which the ES2022 lib types
// but this project's ES2020 lib does not. This declares only that two-argument form; the lib, target, React and Vite
// are unchanged.
interface ErrorOptions {
  cause?: unknown;
}
interface ErrorConstructor {
  new (message?: string, options?: ErrorOptions): Error;
}
