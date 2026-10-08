import { AnalyzeForm } from "./analyze-form";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-4 py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">ChangeBrief</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          Paste a public GitHub pull request URL.
        </p>
        <p className="text-sm text-zinc-500">
          Development build: the server fetches the public pull request from the GitHub API,
          sends bounded evidence to one AI model call, and shows the validated brief. The brief
          is AI-generated and may be wrong.
        </p>
      </header>
      <AnalyzeForm />
    </main>
  );
}
