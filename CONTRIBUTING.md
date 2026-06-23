# Contributing

This repo uses a **feature branch → pull request → merge** workflow. Do not push directly to `main`.

## Workflow

1. **Sync `main`**
   ```bash
   git checkout main
   git pull origin main
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feat/short-description
   ```
   Use prefixes like `feat/`, `fix/`, `chore/`, or `docs/`.

3. **Make changes and commit**
   ```bash
   git add .
   git commit -m "Describe the change"
   ```

4. **Push and open a PR**
   ```bash
   git push -u origin HEAD
   gh pr create --fill
   ```

5. **Wait for CI** — the `test` job must pass before merge.

6. **Merge** — use **Squash and merge** on GitHub (or `gh pr merge --squash`).

7. **Clean up**
   ```bash
   git checkout main
   git pull origin main
   git branch -d feat/short-description
   ```

## Branch protection

`main` requires a pull request and a passing CI check. Force-pushes and branch deletion are disabled.

## Local checks

```bash
python -m pytest tests/ -v
python eval/run_eval.py
```
