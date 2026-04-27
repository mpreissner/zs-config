import { useParams } from "react-router-dom";

export default function ZiaPage() {
  const { tenant } = useParams<{ tenant: string }>();

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-2">
        ZIA — {tenant}
      </h1>
      <p className="text-gray-500">Coming soon.</p>
    </div>
  );
}
