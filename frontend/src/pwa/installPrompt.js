// src/pwa/installPrompt.js
// Chrome / Edge / Android fire "beforeinstallprompt" once, possibly before any component is
// mounted: keep it here so the "Install app" button can use it later.
import { useEffect, useState } from "react";

let deferredPrompt = null;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // we show our own button instead of the browser's mini bar
    deferredPrompt = e;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });
}

const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;

// iPhone / iPad Safari has no install prompt: "Share > Add to Home Screen" instead
const isIos = () =>
  /iphone|ipad|ipod/i.test(window.navigator.userAgent) ||
  (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1); // iPadOS

/** { canInstall, iosInstructions, install() } */
export function useInstallApp() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const fn = () => setTick((t) => t + 1);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);

  const installed = isStandalone();
  return {
    canInstall: !installed && !!deferredPrompt,
    iosInstructions: !installed && !deferredPrompt && isIos(),
    install: async () => {
      if (!deferredPrompt) return false;
      const prompt = deferredPrompt;
      deferredPrompt = null; // can only be used once
      notify();
      prompt.prompt();
      const { outcome } = await prompt.userChoice;
      return outcome === "accepted";
    },
  };
}
