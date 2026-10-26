import { AnalyzeForm } from "./analyze-form";

const SOURCE_URL = "https://github.com/alejandrolunatech/ai-engineering-labs/tree/main/labs/05-production-llm-service";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-4 py-16">
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">ChangeBrief</h1>
        <p className="text-zinc-700 dark:text-zinc-300">
          Paste a public GitHub pull request. Get a plain-language brief of what it changes, why it
          matters, how risky it looks, and what is still unknown.
        </p>
      </header>
      <AnalyzeForm />
      <footer className="mt-auto flex flex-col gap-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          How it works: the server reads the pull request from the GitHub API, cuts it to a fixed
          size, and makes one call to an AI model. The answer is checked against a schema before it
          is shown. The brief is AI-generated and may be wrong; check it against the pull request.
        </p>
        <p>
          Public repositories only. ChangeBrief keeps no copy of the pull request or the brief. Its
          own logs hold counts and timings; the rate limiter keeps a hashed form of your IP address
          for up to a day.
        </p>
        <p>
          <a href={SOURCE_URL} className="underline underline-offset-2">
            Source code and design notes
          </a>
        </p>
      </footer>
    </main>
  );
}
