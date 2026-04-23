import { useState } from "react";
import { formatDate } from "../utils/time";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { startRegistration } from "@simplewebauthn/browser";
import { useAuth } from "../context/AuthContext";
import {
  listCredentials,
  beginRegistration,
  completeRegistration,
  deleteCredential,
  renameCredential,
  type WebAuthnCredential,
} from "../api/webauthn";

export default function ProfilePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [addError, setAddError] = useState<string | null>(null);
  const [addSuccess, setAddSuccess] = useState(false);
  const [labelInput, setLabelInput] = useState("");
  const [adding, setAdding] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const { data: creds = [], isLoading } = useQuery<WebAuthnCredential[]>({
    queryKey: ["webauthn-credentials"],
    queryFn: listCredentials,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCredential,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webauthn-credentials"] }),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => renameCredential(id, label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["webauthn-credentials"] });
      setRenamingId(null);
    },
  });

  async function handleAddKey() {
    if (!labelInput.trim() && !window.confirm("Add key without a label?")) return;
    setAdding(true);
    setAddError(null);
    setAddSuccess(false);
    try {
      const options = await beginRegistration(labelInput.trim());
      const credential = await startRegistration(options as Parameters<typeof startRegistration>[0]);
      await completeRegistration(labelInput.trim(), credential);
      qc.invalidateQueries({ queryKey: ["webauthn-credentials"] });
      setLabelInput("");
      setAddSuccess(true);
      setTimeout(() => setAddSuccess(false), 3000);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "NotAllowedError") {
        setAddError("Registration cancelled.");
      } else {
        setAddError(err instanceof Error ? err.message : "Registration failed.");
      }
    } finally {
      setAdding(false);
    }
  }


  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8">
      {/* Account info */}
      <section>
        <h1 className="text-xl font-semibold text-gray-800 mb-4">Profile</h1>
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-2">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-zs-500 flex items-center justify-center text-white font-bold text-lg">
              {user?.username?.[0]?.toUpperCase() ?? "?"}
            </div>
            <div>
              <p className="font-medium text-gray-800">{user?.username}</p>
              <p className="text-xs text-gray-500 capitalize">{user?.role}</p>
            </div>
          </div>
          <div className="pt-2">
            <Link
              to="/change-password"
              className="text-sm text-zs-500 hover:underline"
            >
              Change password
            </Link>
          </div>
        </div>
      </section>

      {/* Security Keys */}
      <section>
        <h2 className="text-base font-semibold text-gray-700 mb-3">Security Keys</h2>
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {isLoading ? (
            <p className="p-4 text-sm text-gray-500">Loading...</p>
          ) : creds.length === 0 ? (
            <p className="p-4 text-sm text-gray-500">No security keys registered.</p>
          ) : (
            creds.map((cred) => (
              <div key={cred.credential_id} className="p-4 flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0">
                  {renamingId === cred.credential_id ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        className="border border-gray-300 rounded px-2 py-1 text-sm flex-1"
                        autoFocus
                      />
                      <button
                        onClick={() => renameMutation.mutate({ id: cred.credential_id, label: renameValue })}
                        className="text-xs bg-zs-500 text-white px-2 py-1 rounded"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setRenamingId(null)}
                        className="text-xs text-gray-500 px-2 py-1"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {cred.label || <span className="italic text-gray-400">Unnamed key</span>}
                    </p>
                  )}
                  <p className="text-xs text-gray-400">
                    Added {formatDate(cred.created_at)} · Last used {formatDate(cred.last_used_at)}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  {renamingId !== cred.credential_id && (
                    <button
                      onClick={() => {
                        setRenamingId(cred.credential_id);
                        setRenameValue(cred.label ?? "");
                      }}
                      className="text-xs text-gray-500 hover:text-gray-700"
                    >
                      Rename
                    </button>
                  )}
                  <button
                    onClick={() => {
                      if (window.confirm("Remove this security key?")) {
                        deleteMutation.mutate(cred.credential_id);
                      }
                    }}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))
          )}

          {/* Add key form */}
          <div className="p-4 space-y-2">
            <p className="text-xs font-medium text-gray-600">Add a security key</p>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Key label (optional)"
                value={labelInput}
                onChange={(e) => setLabelInput(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm flex-1 focus:outline-none focus:ring-2 focus:ring-zs-500"
              />
              <button
                onClick={handleAddKey}
                disabled={adding}
                className="bg-zs-500 hover:bg-zs-600 disabled:opacity-60 text-white text-sm px-3 py-1.5 rounded transition-colors"
              >
                {adding ? "Touch key…" : "Add Key"}
              </button>
            </div>
            {addError && <p className="text-xs text-red-600">{addError}</p>}
            {addSuccess && <p className="text-xs text-green-600">Security key registered successfully.</p>}
          </div>
        </div>
      </section>
    </div>
  );
}
