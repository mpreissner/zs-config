import { useEffect, useState } from "react";

export type ToastVariant = "success" | "error" | "info";

interface ToastProps {
  message: string;
  variant?: ToastVariant;
  onDismiss?: () => void;
  duration?: number; // ms, 0 = no auto-dismiss
}

export default function Toast({
  message,
  variant = "info",
  onDismiss,
  duration = 4000,
}: ToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (duration <= 0) return;
    const t = setTimeout(() => {
      setVisible(false);
      onDismiss?.();
    }, duration);
    return () => clearTimeout(t);
  }, [duration, onDismiss]);

  if (!visible) return null;

  const colors = {
    success: "bg-green-50 border-green-300 text-green-800",
    error: "bg-red-50 border-red-300 text-red-800",
    info: "bg-blue-50 border-blue-300 text-blue-800",
  };

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-lg border text-sm shadow-md ${colors[variant]}`}
    >
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button
          onClick={() => { setVisible(false); onDismiss(); }}
          className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  );
}

// ── Toast container for stacking multiple toasts ──────────────────────────────

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastContainerProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm w-full">
      {toasts.map((t) => (
        <Toast
          key={t.id}
          message={t.message}
          variant={t.variant}
          onDismiss={() => onDismiss(t.id)}
        />
      ))}
    </div>
  );
}
