interface ErrorMessageProps {
  message: string;
}

export default function ErrorMessage({ message }: ErrorMessageProps) {
  return (
    <div className="rounded-md bg-red-50 border border-red-200 p-4">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
