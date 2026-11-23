/**
 * Vitest setup file for the jsdom environment.
 *
 * The `jsdom` test environment already provides `window`, `document`,
 * `navigator`, and `location`. Creating a second JSDOM instance here would
 * make Testing Library query a different document than the one React renders
 * into, so this file intentionally leaves the environment globals untouched.
 */

/** Make React.lazy resolve synchronously in tests so code-split routes render
 *  without awaiting dynamic imports. */
import React from 'react';
const originalLazy = React.lazy;
React.lazy = (factory) => {
  let Resolved = null;
  let resolving = false;
  const lazyComp = (props) => {
    const [mod, setMod] = React.useState(null);
    React.useEffect(() => {
      if (!resolving) {
        resolving = true;
        factory().then((m) => {
          Resolved = m.default ?? m;
          setMod(Resolved);
        });
      }
    }, []);
    if (!mod) return null;
    return React.createElement(mod, props);
  };
  return lazyComp;
};
