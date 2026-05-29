# Git Workflow — Connecting Local Project to GitHub

This guide covers how to connect an existing local project folder to a GitHub repository and push your work to a feature branch.

---

## Prerequisites

- Git installed on your machine
- A GitHub repository already created
- Your feature branch already created on GitHub

---

## Step 1 — Initialize Git Locally

Inside your project folder:

```bash
git init
git remote add origin https://github.com/<your-username>/<your-repo>.git
```

---

## Step 2 — Fetch Branches from GitHub

```bash
git fetch origin
```

This downloads all remote branches without changing any local files.

---

## Step 3 — Connect to Your Feature Branch

```bash
git symbolic-ref HEAD "refs/heads/<your-branch-name>"
git update-ref "refs/heads/<your-branch-name>" "refs/remotes/origin/<your-branch-name>"
git branch --set-upstream-to="origin/<your-branch-name>" "<your-branch-name>"
git reset HEAD
```

> Use this approach when your local folder already has files and you want to connect to a remote branch without overwriting anything.

---

## Step 4 — Check What Has Changed

```bash
git status
```

- `M` = modified (file exists in both local and remote, but differs)
- `??` = untracked (new file that only exists locally — your additions)
- `D` = deleted locally (file exists on remote but not in your local folder — **do not stage these if they belong to other team members**)

---

## Step 5 — Stage Only Your Files

Stage specific files instead of `git add .` to avoid accidentally including other people's deletions or sensitive files:

```bash
git add path/to/your/file.py
git add path/to/your/folder/
```

To stage all modified + new files at once (only safe if you reviewed `git status` first):

```bash
git add -u        # stages modified + deleted (not untracked)
git add .         # stages everything including untracked
```

**Never stage `.env` files or files containing real passwords/tokens.**

---

## Step 6 — Review What Is Staged

```bash
git diff --cached --stat
```

Confirm:
- No `.env` file
- No deletion of other team members' files
- Only your intended changes

---

## Step 7 — Commit

```bash
git commit -m "your commit message here"
```

Good commit message format:

```
feat(scope): short description of what was added

- bullet point detail
- another detail
```

---

## Step 8 — Push to Your Branch

```bash
git push origin "<your-branch-name>"
```

---

## Step 9 — Delete a File from GitHub

```bash
git rm filename.md
git commit -m "remove filename.md"
git push origin "<your-branch-name>"
```

---

## Step 10 — Open a Pull Request

Go to your repository on GitHub. You will see a banner:

> "Compare & pull request" for your branch

Click it, write a description, and set the base branch to `main`.

---

## Common Rules

| Rule | Why |
|------|-----|
| Never push directly to `main` | Protects shared history |
| Never commit `.env` | Contains real secrets |
| Always review `git diff --cached` before committing | Catch accidental files |
| Use `git add <specific-file>` not `git add .` blindly | Avoid staging team members' deletions |
| Keep PRs focused on one feature | Easier to review and revert |

---

## Useful Commands Reference

| Command | What it does |
|---------|-------------|
| `git status` | Show all changes in working tree |
| `git diff --cached --stat` | Show what is staged for commit |
| `git log --oneline` | Show recent commits |
| `git fetch origin` | Download remote branches (no file changes) |
| `git branch -a` | List all local and remote branches |
| `git rm <file>` | Remove file from disk and git tracking |
| `git restore --staged <file>` | Unstage a file without deleting it |
