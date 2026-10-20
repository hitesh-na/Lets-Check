# Publish Let's Check from Windows

The verified source is ready to commit.
These steps use Git and PowerShell from the project folder containing
`README.md`, `app`, and `docker-compose.yml`. No GitHub CLI installation is needed.

## 1. Check the local repository

```powershell
git status
git remote -v
```

If Git reports **not a git repository**, initialize this project folder:

```powershell
git init -b main
```

If it is already a repository, keep its existing history and branch. If a
remote already exists, check its URL before using it; the new-remote step
below applies only when there is no `origin` configured.

## 2. Stage and review the project

```powershell
git add .gitignore .gitattributes README.md requirements.txt docker-compose.yml app tests scripts docs
git diff --cached --stat
git status --short
```

The staged files should be this project's source, tests, configuration, and
documentation. Keep personal working notes outside the project folder. The
provided ignore rules exclude the virtual environment, environment files,
caches, logs, and local demo JSON reports.

If Git requests your name/email when committing, set the identity you want
associated with this repository, using your own name and a GitHub-verified or
GitHub-provided private email address:

```powershell
git config user.name "YOUR NAME"
git config user.email "YOUR EMAIL"
```

These two settings apply to this repository. Then create the commit:

```powershell
git commit -m "Build Let's Check distributed website checker"
```

If you already committed some project files, this records the remaining changes.
If there is nothing new to commit, keep the existing commit.

## 3. Create an empty GitHub repository

On GitHub, create a repository named **lets-check** under the account you want
to use. Choose Public or Private as appropriate for your project. Leave the
README, license, and gitignore initialization options unchecked, because this
source already contains its own README and ignore rules.

If you already created the intended repository, use it. Copy its HTTPS URL
from the repository's setup page. A repository that already contains commits
may need history reconciliation before the first push; this guide does not
use force-push commands.

## 4. Connect and push

For a repository with no existing `origin`, run:

```powershell
$repoUrl = Read-Host "Paste the GitHub repository HTTPS URL"
git remote add origin $repoUrl
git remote -v
```

If `origin` already points to the intended repository, use that remote. Push
the current branch, preserving its name:

```powershell
$branch = git branch --show-current
git push -u origin $branch
```

Complete GitHub authentication through your Git installation's normal flow
if prompted. If a command fails, retain the output and resolve that error
before rerunning later commands.

## 5. Verify the published repository

Refresh the repository page and confirm the source, tests, docs, and rendered
README are present. The README should show its architecture diagram and link
to the actual Windows demo record. Retain the local JSON report as additional
evidence. Retain the repository URL and successful push output for your records.

Official instructions:

- [Add locally hosted code to GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
- [Diagrams in GitHub Markdown](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)
