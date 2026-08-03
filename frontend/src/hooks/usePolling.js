import { useState, useEffect, useRef } from 'react';

export function usePolling(fetchFunc, intervalMs, enabled = true) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  
  const fetchRef = useRef(fetchFunc);
  fetchRef.current = fetchFunc;

  useEffect(() => {
    let mounted = true;
    let timeoutId = null;

    const executePoll = async () => {
      try {
        const result = await fetchRef.current();
        if (mounted) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err);
        }
      } finally {
        if (mounted) {
          setLoading(false);
          if (enabled) {
            timeoutId = setTimeout(executePoll, intervalMs);
          }
        }
      }
    };

    if (enabled) {
      setLoading(true);
      executePoll();
    } else {
      setLoading(false);
    }

    return () => {
      mounted = false;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [intervalMs, enabled]);

  return { data, error, loading, setData };
}
