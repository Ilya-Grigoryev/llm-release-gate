import Link from "next/link";

export default function NotFound() {
  return (
    <section className="py-16 text-center">
      <h1 className="text-2xl font-semibold">Not here</h1>
      <p className="mt-2 text-ink-2">This page does not exist, or the App is not installed on its repository for your account.</p>
      <Link href="/" className="mt-6 inline-block underline underline-offset-4">
        Back to projects
      </Link>
    </section>
  );
}
