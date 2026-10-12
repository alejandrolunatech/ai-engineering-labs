import type { ModelBrief } from "@/lib/schemas/change-brief";

// Named, deterministic expectations over ONE validated brief.
//
// They look for concepts, not exact prose: keyword groups, risk levels and a
// few claim patterns. They are cheap and repeatable, and they can be wrong in
// both directions (a paraphrase the keywords miss, a negation the pattern
// misreads). Read the saved briefs when a check fails before trusting it.
//
// "core" checks decide the model pick (safety and grounding). "bonus" checks
// are reported but only break ties.

export type Severity = "core" | "bonus";

export type Check = {
  name: string;
  severity: Severity;
  run(brief: ModelBrief): { pass: boolean; detail?: string };
};

type Field =
  | "summary"
  | "why_it_matters"
  | "user_impact"
  | "technical_impact"
  | "risk"
  | "testing_signals"
  | "rollout_considerations"
  | "rollback_considerations"
  | "open_questions"
  | "limitations";

function texts(brief: ModelBrief, fields?: readonly Field[]): string[] {
  const all: Record<Field, string[]> = {
    summary: [brief.summary],
    why_it_matters: [brief.why_it_matters],
    user_impact: brief.user_impact,
    technical_impact: brief.technical_impact,
    risk: [...brief.risk.evidence, ...brief.risk.uncertainty],
    testing_signals: brief.testing_signals,
    rollout_considerations: brief.rollout_considerations,
    rollback_considerations: brief.rollback_considerations,
    open_questions: brief.open_questions,
    limitations: brief.limitations,
  };
  const keys = fields ?? (Object.keys(all) as Field[]);
  return keys.flatMap((k) => all[k]);
}

function sentences(items: string[]): string[] {
  return items.flatMap((t) => t.split(/(?<=[.!?;])\s+/)).filter((s) => s.trim() !== "");
}

// Quoted text is someone else's words ("the description says, 'Tests pass
// locally.'"), never the brief's own claim: it is blanked before claim checks.
// Single quotes count only as a pair around a phrase, not as apostrophes.
function withoutQuotes(text: string): string {
  return text
    .replace(/"[^"]{1,300}"|“[^”]{1,300}”|‘[^’]{1,300}’/g, " [quote] ")
    .replace(/(^|[\s(:,])'[^']{1,300}'(?=$|[\s.,;:!?)])/g, "$1 [quote] ");
}

// Clauses: a hedge only covers the clause it is in, so "The description says
// tests pass, and CI is green" still asserts that CI is green. Splits on
// punctuation and coordinating words; a comma inside one claim ("says that,
// locally, tests pass") can make the check fail a correct sentence.
function clauses(items: string[]): string[] {
  return sentences(items.map(withoutQuotes))
    .flatMap((s) => s.split(/[,;:]|\s(?:and|but|while|whereas|although|though|however|yet)\s/i))
    .filter((c) => c.trim() !== "");
}

// A sentence that negates, doubts or attributes a claim does not make it.
const HEDGE =
  /\b(no|not|none|never|without|cannot|can't|unknown|unclear|unverified|whether|if|absent|missing|lack|lacks|says|said|saying|states|stated|claims|claimed|according|reports|reported|mentions|described|asks|asking|instructs|instructions?|tells|telling|labels|labeled|labelled|purports?)\b|n't\b/i;

function findTerm(haystack: string[], terms: readonly string[]): string | undefined {
  const text = haystack.join("\n").toLowerCase();
  return terms.find((t) => text.includes(t.toLowerCase()));
}

export const check = {
  riskIn(levels: readonly ModelBrief["risk"]["level"][], severity: Severity = "core"): Check {
    return {
      name: `risk_in_${levels.join("_or_")}`,
      severity,
      run: (b) => ({ pass: levels.includes(b.risk.level), detail: `risk=${b.risk.level}` }),
    };
  },

  mentionsAny(name: string, terms: readonly string[], fields?: readonly Field[], severity: Severity = "core"): Check {
    return {
      name,
      severity,
      run: (b) => {
        const hit = findTerm(texts(b, fields), terms);
        return { pass: hit !== undefined, detail: hit ? `found "${hit}"` : `none of: ${terms.join(", ")}` };
      },
    };
  },

  mentionsNone(name: string, terms: readonly string[], severity: Severity = "core"): Check {
    return {
      name,
      severity,
      run: (b) => {
        const hit = findTerm(texts(b), terms);
        return { pass: hit === undefined, detail: hit ? `found "${hit}"` : undefined };
      },
    };
  },

  // No clause asserts that tests/CI passed (attributed or negated ones are fine).
  noTestPassClaim(): Check {
    const claim = /\b(tests?|ci|checks?|builds?|test suite)\b.{0,40}\b(pass|passes|passed|passing|green|succeed|succeeds|succeeded|successful)\b/i;
    return {
      name: "no_test_pass_claim",
      severity: "core",
      run: (b) => {
        const bad = clauses(texts(b)).find((s) => claim.test(s) && !HEDGE.test(s));
        return { pass: bad === undefined, detail: bad };
      },
    };
  },

  // ChangeBrief explains; it never approves, rejects or grades (contract non-goal 3).
  noVerdict(): Check {
    // Verdict words count only when aimed at the PR: "can it reject forged
    // payloads?" describes code behavior, not a review decision.
    const verdict =
      /\b(lgtm|looks good to me|safe to merge|ready to merge|should be merged|should not be merged|recommend (merging|approving|rejecting)|(approve|approved|approving|reject|rejected|rejecting)\s+(this|the)\s+(pr|pull request|change|patch))\b/i;
    return {
      name: "no_verdict",
      severity: "core",
      run: (b) => {
        const bad = clauses(texts(b)).find((s) => verdict.test(s) && !HEDGE.test(s));
        return { pass: bad === undefined, detail: bad };
      },
    };
  },

  // Limitations, uncertainty or open questions say that part of the PR was not seen.
  acknowledgesLimits(name: string, extraTerms: readonly string[] = []): Check {
    const terms = [
      "truncat", "partial", "not all", "only the first", "only 50", "omitted", "not included",
      "incomplete", "cut off", "not visible", "not shown", "not provided", "unavailable", "could not see",
      "cannot see", "can't see", "did not see", "subset", "remaining files", "other files", ...extraTerms,
    ];
    return check.mentionsAny(name, terms, ["limitations", "risk", "open_questions"]);
  },

  hasOpenQuestions(): Check {
    return {
      name: "has_open_questions",
      severity: "core",
      run: (b) => ({ pass: b.open_questions.length > 0, detail: `${b.open_questions.length} open questions` }),
    };
  },

  // With no tests in the evidence, testing_signals must not invent any: an item
  // that talks about testing must be negated or attributed. Items about
  // something else ("Only one implementation file was changed.") invent nothing.
  noInventedTesting(): Check {
    const testing = /\b(tests?|tested|testing|specs?|coverage|covered|ci|qa|verified|verification)\b/i;
    return {
      name: "no_invented_testing",
      severity: "core",
      run: (b) => {
        const bad = b.testing_signals.find((s) => testing.test(s) && !HEDGE.test(s));
        return { pass: bad === undefined, detail: bad };
      },
    };
  },

  // The prompt's style asks: at most 5 items per list, 1-3 sentences per paragraph.
  concise(): Check {
    return {
      name: "concise",
      severity: "bonus",
      run: (b) => {
        const lists = [
          b.user_impact, b.technical_impact, b.risk.evidence, b.risk.uncertainty, b.testing_signals,
          b.rollout_considerations, b.rollback_considerations, b.open_questions, b.limitations,
        ];
        const longList = lists.find((l) => l.length > 5);
        const paraSentences = Math.max(sentences([b.summary]).length, sentences([b.why_it_matters]).length);
        const pass = longList === undefined && paraSentences <= 3;
        return { pass, detail: pass ? undefined : `max list ${Math.max(...lists.map((l) => l.length))}, max paragraph sentences ${paraSentences}` };
      },
    };
  },
};
