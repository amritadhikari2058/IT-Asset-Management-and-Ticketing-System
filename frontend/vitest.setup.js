/**
 * Vitest setup file for the jsdom environment.
 *
 * The `jsdom` test environment already provides `window`, `document`,
 * `navigator`, and `location`. Creating a second JSDOM instance here would
 * make Testing Library query a different document than the one React renders
 * into, so this file intentionally leaves the environment globals untouched.
 */
