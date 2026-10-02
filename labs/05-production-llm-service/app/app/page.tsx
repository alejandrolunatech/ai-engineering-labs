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
          Development build: this version only validates the URL and shows which GitHub API
          endpoint the server would call. It does not contact GitHub or any AI model yet.
        </p>
      </header>
      <AnalyzeForm />
    </main>
  );
}
