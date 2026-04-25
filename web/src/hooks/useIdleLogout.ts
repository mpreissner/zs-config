import { useEffect, useRef, useCallback, useState } from "react";

const IDLE_MS = 15 * 60 * 1000;
const WARN_BEFORE_MS = 2 * 60 * 1000;
const WARN_SECONDS = Math.round(WARN_BEFORE_MS / 1000);
const ACTIVITY_THROTTLE_MS = 5_000;

export function useIdleLogout(active: boolean, logout: () => void) {
  const [showWarning, setShowWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(WARN_SECONDS);

  const warnTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const logoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdown = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastActivity = useRef(0);

  const clearAll = useCallback(() => {
    if (warnTimer.current)   { clearTimeout(warnTimer.current);    warnTimer.current   = null; }
    if (logoutTimer.current) { clearTimeout(logoutTimer.current);  logoutTimer.current = null; }
    if (countdown.current)   { clearInterval(countdown.current);   countdown.current   = null; }
  }, []);

  const arm = useCallback(() => {
    clearAll();
    setShowWarning(false);

    warnTimer.current = setTimeout(() => {
      setShowWarning(true);
      setSecondsLeft(WARN_SECONDS);
      countdown.current = setInterval(() => {
        setSecondsLeft((s) => Math.max(0, s - 1));
      }, 1000);
    }, IDLE_MS - WARN_BEFORE_MS);

    logoutTimer.current = setTimeout(logout, IDLE_MS);
  }, [clearAll, logout]);

  const onActivity = useCallback(() => {
    const now = Date.now();
    if (now - lastActivity.current < ACTIVITY_THROTTLE_MS) return;
    lastActivity.current = now;
    arm();
  }, [arm]);

  // Called from the "Stay logged in" button — bypasses throttle.
  const extend = useCallback(() => {
    lastActivity.current = 0;
    arm();
  }, [arm]);

  useEffect(() => {
    if (!active) {
      clearAll();
      setShowWarning(false);
      return;
    }
    lastActivity.current = 0;
    arm();

    const events = ["mousemove", "keydown", "mousedown", "touchstart", "scroll", "click"] as const;
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      clearAll();
    };
  }, [active, arm, onActivity, clearAll]);

  return { showWarning, secondsLeft, extend };
}
