import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-16">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">Not here</h1>
      <p className="mt-3 max-w-[60ch] text-ink-2">
        This page does not exist, or the App is not installed on its repository for your account.
      </p>
      <p className="mt-6 flex gap-6">
        <Link href="/projects" className="underline underline-offset-4">
          Your projects
        </Link>
        <Link href="/" className="underline underline-offset-4">
          Docs
        </Link>
      </p>
    </main>
  );
}
