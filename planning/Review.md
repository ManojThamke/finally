# Review

Reviewed all tracked and untracked changes against `HEAD` (`e2e8675`). Findings are ordered by severity.

## Findings

### [P1] The same review command is registered twice

`.claude/settings.json` registers a `Stop` hook that runs `codex exec ...`, and the newly enabled `independent-reviewer@mt-tools` plugin declares the identical `Stop` hook in `independent-reviewer/hooks/hooks.json`. With both project hooks and the enabled plugin loaded, each Claude stop launches two independent Codex reviews that write `planning/Review.md` concurrently. This can duplicate review cost and produce a truncated or last-writer-wins report. Keep the hook in one place (or otherwise ensure only one invocation).

### [P2] Removing the GitHub workflows disables repository review and @claude automation

The deletions of `.github/workflows/claude-code-review.yml` and `.github/workflows/claude.yml` remove the PR review workflow and the issue/PR `@claude` workflow. Repositories relying on these workflows will no longer receive automated PR reviews or respond to `@claude` mentions. If this was intended as a migration to the local plugin, the new Stop hook does not provide equivalent GitHub automation; retain or replace the workflows if that automation is still expected.

## Other checks

- The README's `uv sync --extra dev` matches the optional `dev` extra in `backend/pyproject.toml`.
- `backend/market_data_demo.py` exists, so the documented demo path is present.
- The additional blank lines at the end of `planning/PLAN.md` are harmless.
