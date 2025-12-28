// src/providers/LoadingProvider.jsx
import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import "./LoadingProvider.css";

const LoadingContext = createContext({
  isLoading: false,
  start: () => {},
  stop: () => {},
  installAxiosInterceptors: () => {},
});

export function LoadingProvider({ children }) {
  const [count, setCount] = useState(0);
  const pending = useRef(0);

  const start = useCallback(() => {
    pending.current += 1;
    setCount((c) => c + 1);
  }, []);

  const stop = useCallback(() => {
    pending.current = Math.max(0, pending.current - 1);
    setCount((c) => Math.max(0, c - 1));
  }, []);

  const installAxiosInterceptors = useCallback((axiosInstance) => {
    if (!axiosInstance || axiosInstance.__hasLoadingInterceptor) return;

    const reqId = axiosInstance.interceptors.request.use((config) => {
      start();
      return config;
    });

    const resId = axiosInstance.interceptors.response.use(
      (res) => {
        stop();
        return res;
      },
      (err) => {
        stop();
        return Promise.reject(err);
      }
    );

    axiosInstance.__hasLoadingInterceptor = true;
    axiosInstance.__loadingInterceptors = { reqId, resId };
  }, [start, stop]);

  const value = useMemo(() => ({
    isLoading: count > 0,
    start, stop, installAxiosInterceptors
  }), [count, start, stop, installAxiosInterceptors]);

  return (
    <LoadingContext.Provider value={value}>
      {children}
      {ReactDOM.createPortal(<GlobalSpinner visible={count > 0} />, document.body)}
    </LoadingContext.Provider>
  );
}

export function useLoading() {
  return useContext(LoadingContext);
}

// Full-screen overlay + spinner
function GlobalSpinner({ visible }) {
  return (
    <div className={`nf-loader-overlay ${visible ? "show" : ""}`} aria-hidden={!visible} aria-live="polite">
         <img src="/logo/taurus_logo_full.png" style={{ height: 32, marginRight: 12 }} alt="Taurus Logo" />
      <div className="nf-spinner" role="status" aria-label="Loading" />
      <div className="nf-brand">
        <span className="nf-n">N</span>
        <span className="nf-sheen" />
      </div>
    </div>
  );
}
