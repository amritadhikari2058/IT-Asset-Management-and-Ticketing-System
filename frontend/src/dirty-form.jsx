import { useCallback, useEffect, useState, createContext, useContext } from 'react';

const DirtyCtx = createContext({ isDirty: false, markDirty: () => {}, markClean: () => {}, setDirty: () => {} });

export function DirtyProvider({ children }) {
  const [isDirty, setIsDirty] = useState(false);
  const markDirty = useCallback(() => setIsDirty(true), []);
  const markClean = useCallback(() => setIsDirty(false), []);
  const setDirty = useCallback((v) => setIsDirty(!!v), []);
  return (
    <DirtyCtx.Provider value={{ isDirty, markDirty, markClean, setDirty }}>
      {children}
    </DirtyCtx.Provider>
  );
}

export function useDirty() { // eslint-disable-line react/only-export-components
  const ctx = useContext(DirtyCtx);
  if (!ctx) throw new Error('useDirty must be used within a DirtyProvider');
  return ctx;
}

/** Hook for tracking field-level dirtiness against initial values.
 *  Returns { isDirty, setField, markClean, reset, values }. */
export function useDirtyForm(initialValues) { // eslint-disable-line react/only-export-components
  const [values, setValues] = useState(initialValues);
  const initialKeys = Object.keys(initialValues);
  const { markDirty, markClean } = useDirty();

  const isDirtyValue = useMemo(() => {
    const cur = values;
    const keys = new Set([...Object.keys(cur), ...initialKeys]);
    return [...keys].some((k) => cur[k] !== initialValues[k]);
  }, [values]); // eslint-disable-line react-hooks/exhaustive-deps

  const setField = useCallback((k, v) => {
    setValues((prev) => ({ ...prev, [k]: v }));
    if (v !== initialValues[k]) markDirty();
    else {
      if (!isDirtyValue) markClean();
    }
  }, [isDirtyValue, markDirty, markClean, initialValues]);

  const reset = useCallback(() => {
    setValues(initialValues);
    markClean();
  }, [markClean, initialValues]);

  return { values, setField, isDirty: isDirtyValue, reset };
}

/** Registers a beforeunload warning when dirty. Place once per page/shell. */
export function DirtyBlocker() {
  const { isDirty } = useDirty();
  useEffect(() => {
    const onBeforeUnload = (e) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Leave anyway?';
      }
    };
    const onHashChange = () => {
      if (isDirty) {
        // Cannot programmatically block hash navigation via beforeunload.
        // Warn via toast instead if the UI layer handles it.
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    window.addEventListener('hashchange', onHashChange);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      window.removeEventListener('hashchange', onHashChange);
    };
  }, [isDirty]);
  return null;
}
