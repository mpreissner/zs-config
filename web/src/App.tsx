import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import TenantsPage from "./pages/TenantsPage";
import AuditPage from "./pages/AuditPage";
import ZiaPage from "./pages/ZiaPage";
import ZpaPage from "./pages/ZpaPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/tenants" replace />} />
        <Route path="/tenants" element={<TenantsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/zia/:tenant" element={<ZiaPage />} />
        <Route path="/zpa/:tenant" element={<ZpaPage />} />
      </Routes>
    </Layout>
  );
}
