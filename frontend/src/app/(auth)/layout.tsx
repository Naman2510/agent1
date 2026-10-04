export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-12">
      <div className="text-center">
        <p className="text-2xl font-semibold tracking-tight">
          Vaani<span className="text-accent">OS</span>
        </p>
        <p className="mt-1 text-sm text-muted">Your voice mentor for engineering — in your language.</p>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
