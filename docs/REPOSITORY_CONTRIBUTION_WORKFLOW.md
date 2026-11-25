# Repository Contribution Workflow

This guide keeps the `main` branch readable without hiding the detail needed to review and reproduce development.

## Principles

- Keep development history truthful. Do not delete, rewrite, or squash existing public history merely to make the commit count smaller.
- Make each pull request answer one coherent engineering question.
- Keep implementation, tests, and documentation for the same change together where practical.
- Prefer small, reviewable pull requests over one large mixed-purpose change.
- Treat `main` as the integrated project record, not as a scratchpad.

## Branches

Create a short-lived branch from the latest `main` for each independent task. Use a descriptive prefix:

- `feat/<area>-<short-description>`
- `fix/<area>-<short-description>`
- `test/<area>-<short-description>`
- `docs/<short-description>`
- `refactor/<area>-<short-description>`

Avoid committing unrelated work to the same branch. If a task grows into multiple independently reviewable changes, split it before opening the pull request.

## Commit messages

Use a short imperative subject with a conventional type:

- `feat: add persistent run record storage`
- `fix: reject stale telemetry samples`
- `test: cover workspace migration failure`
- `docs: explain local customer console setup`
- `refactor: isolate forecast request validation`

A commit should describe the change, not the act of editing (avoid subjects such as `update`, `try fix`, or `final changes`). Multiple local commits are acceptable when they help development and review.

## Pull request scope and description

Each PR should state:

1. **Purpose:** the user or engineering problem being addressed.
2. **Scope:** the main modules, contracts, pages, or workflows changed.
3. **Behaviour:** what changes, and what deliberately does not change.
4. **Verification:** exact tests or checks run, with results. Never claim a check was run if it was not.
5. **Limitations:** relevant assumptions, compatibility concerns, and unimplemented follow-up work.

Keep a PR focused. Do not combine unrelated features simply to reduce the number of PRs or commits. Link relevant decisions, issues, and dependent PRs.

## Review and merge

- Open a draft PR when the design or implementation is not ready for review.
- Request review from the relevant module owner where practical.
- Resolve material review comments and ensure required CI checks pass before merging.
- Use **Squash and merge** for a focused PR when its intermediate commits are only implementation steps. Use the PR title as the resulting main-branch commit subject, and keep the PR description as the detailed record.
- Preserve separate commits when they represent meaningful, independently useful history or when a merge strategy is needed to retain that structure.
- Do not squash unrelated work into a single PR just to produce one main-branch commit.
- Delete the short-lived branch after merge when it is no longer needed.

## Main-branch commit format

Prefer a concise, searchable subject, for example:

`feat: persist immutable local run records (#123)`

The PR remains the review record: it should contain the purpose, scope, test evidence, discussion, and limitations. A one-commit merge does not replace those details.

## Existing history

This policy applies prospectively. Existing commits on `main`, historical branches, tags, releases, and merged PRs remain unchanged. Do not force-push or rewrite shared history as a cosmetic cleanup. If a genuine repository migration ever requires history rewriting, it must be separately proposed, backed up, coordinated with all contributors, and justified by a concrete technical or security need.

## Reviewer-facing project navigation

Use the README, architecture documents, milestone/closeout records, releases, and focused PRs to explain the project's important engineering progress. Reviewers should not need to inspect every commit to understand the product. Milestones must link to real merged work and must not imply that experimental or unvalidated capabilities are production-ready.
