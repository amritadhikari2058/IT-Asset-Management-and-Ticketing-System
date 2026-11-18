import { useCallback, useState } from 'react';
import api from '../api';

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const request = useCallback(async (method, url, data) => {
    setLoading(true);
    setError(null);
    try {
      return await api.request({ method, url, data });
    } catch (e) {
      setError(e?.message || 'Request failed');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const success = useCallback((message) => message, []);

  return { request, loading, error, setError, success };
}

export default useApi;
