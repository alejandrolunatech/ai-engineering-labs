# GitHub fixtures

SYNTHETIC. Hand-written for this repository in the shape of GitHub's documented
REST responses (`GET /repos/{owner}/{repo}/pulls/{pull_number}` and
`.../pulls/{pull_number}/files`). They are not recordings of real PRs, and
the people, emails and URLs in them are made up. Extra fields such as
`user`, `avatar_url`, `_links` and `email` are included deliberately so that
tests prove they are dropped.
