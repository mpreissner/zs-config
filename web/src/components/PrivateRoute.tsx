import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ReactNode } from "react";

export function PrivateRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, mfaEnrollRequired } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (mfaEnrollRequired) return <Navigate to="/mfa-enroll" replace />;
  return <>{children}</>;
}
