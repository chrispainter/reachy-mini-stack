# AGENTS.md — reachy-mini-stack

Python stack for the Reachy Mini robot (see README.md). Tests live in `showrunner/tests` and `voice/tests`. This repo is **public**: never commit secrets, keys, home-network details or personal data.

## Backlog workflow

Board: [BTPC Backlog](https://github.com/users/chrispainter/projects/2). The board Status is the source of truth; the `status: *` labels mirror it. Start with the pinned issue "Backlog workflow for agents (read first)".

- Work only on issues in **Ready** (`status: ready`). Never pick up `blocked: Chris decision`.
- Assign yourself and move the card to **In Progress**.
- Follow the issue's acceptance criteria.
- One branch and one PR per issue, named `issue-<N>-short-name`.
- Run `(cd showrunner && python3 -m pytest tests/ -m "not live") && python3 -m pytest voice/tests` and make sure it passes before you open the PR. Never run `live` tests or touch the physical robot without Chris's approval.
- Put `Closes #N` in the PR description and move the card to **In Review**.
- Found new work? File an issue in **Idea** (`status: idea`).
- No merging to main, prod deploys, billing changes or outside contact without Chris's approval.
- No secrets in code, issues or PRs. Never use Chris's personal name or email; use gobehindtheproduct.com aliases.
