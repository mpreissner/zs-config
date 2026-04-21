import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { changePassword } from "../api/auth";

export default function ChangePasswordPage() {
  const { login: setToken } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (next !== confirm) { setError("Passwords do not match"); return; }
    setError(null);
    setLoading(true);
    try {
      const res = await changePassword(current, next);
      setToken(res.access_token);
      navigate("/tenants");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setLoading(false);
    }
  }

  const fields: Array<{ label: string; value: string; setter: (v: string) => void }> = [
    { label: "Current password", value: current, setter: setCurrent },
    { label: "New password", value: next, setter: setNext },
    { label: "Confirm new password", value: confirm, setter: setConfirm },
  ];

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-lg px-8 py-6 w-full max-w-sm">
        <h2 className="text-gray-800 font-semibold text-lg mb-1">Change password</h2>
        <p className="text-gray-500 text-xs mb-4">You must set a new password before continuing.</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          {fields.map(({ label, value, setter }) => (
            <div key={label}>
              <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
              <input
                type="password"
                value={value}
                onChange={(e) => setter(e.target.value)}
                required
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              />
            </div>
          ))}
          {error && <p className="text-red-600 text-xs">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-zs-500 hover:bg-zs-600 disabled:opacity-60 text-white font-medium py-2 rounded-md text-sm transition-colors"
          >
            {loading ? "Saving..." : "Set new password"}
          </button>
        </form>
      </div>
    </div>
  );
}
