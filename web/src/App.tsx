import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import { PrivateRoute } from "./components/PrivateRoute";
import TenantsPage from "./pages/TenantsPage";
import AuditPage from "./pages/AuditPage";
import ZiaPage from "./pages/ZiaPage";
import ZpaPage from "./pages/ZpaPage";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/change-password" element={<ChangePasswordPage />} />
      <Route
        path="/*"
        element={
          <PrivateRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<Navigate to="/tenants" replace />} />
                <Route path="/tenants" element={<TenantsPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/zia/:tenant" element={<ZiaPage />} />
                <Route path="/zpa/:tenant" element={<ZpaPage />} />
              </Routes>
            </Layout>
          </PrivateRoute>
        }
      />
    </Routes>
  );
}
