---
name: Ewan-kb-git
description: Commit and version knowledge base layers (source, knowledgeBase, graph) to git.
---

# Ewan-kb-git Skill

Version-control your knowledge base in four git-committed layers.

## When to Use

After running `ewankb build`, you want to commit the results to git. This skill handles:

1. Staging the correct files in each layer
2. Writing meaningful commit messages
3. Tracking version metadata

## Layer Commit Strategy

Each layer has its own commit history and commit message convention:

### Layer 1: source/

Raw source material — documents and code snapshots. **Append-only** — never overwrite historical commits.

```bash
# After fetching new docs or updating repos
ewankb-git commit-source "chore: pull docs 2026-04-13"
```

### Layer 2: domains/

Auto-discovered domain definitions (README.md, PROCESSES.md, domains.json). **Overwritable** — re-discovery creates new commits.

```bash
# After discover or knowledgebase
ewankb-git commit-domains "feat: re-discover domains after code update"
```

### Layer 3: knowledgeBase/

AI-refined knowledge files (flat by doc type, domain in frontmatter). **Overwritable** — each build creates a new commit.

```bash
# After extract or enrich
ewankb-git commit-kb "refactor: re-extract 订单管理 domain"
```

### Layer 4: graph/

Graph data and analysis results. **Overwritable** — rebuilds are new commits.

```bash
# After build-graph
ewankb-git commit-graph "feat: add surprising connections for 订单管理"
```

## Combined Workflow

```bash
# Full cycle: build then commit all layers
ewankb build
ewankb-git commit-all
```

This creates four separate commits (one per layer) with auto-generated messages.

## Commit Message Format

```
<type>(<layer>): <description>

<optional body with details>

[skip-ci]
```

Types: `feat`, `refactor`, `fix`, `chore`, `docs`

Layers: `source`, `domains`, `kb`, `graph`, `all`

## Branch Strategy

For a shared knowledge base (team collaboration):

```
main                    # Latest approved knowledge base
├── kb/
│   ├── proposal/       # WIP domain proposals
│   └── review/         # Under review
└── ...
```

Use feature branches for domain-level changes:
```bash
git checkout -b domain/订单管理
# make changes
git push -u origin domain/订单管理
# open PR to main
```

## Push to Remote

```bash
ewankb-git push
```

Pushes all layers to the configured remote.

## Git Hooks

Recommended `.git/hooks/pre-commit`:

```bash
#!/bin/sh
# Reject commits to graph/ if knowledgeBase/ is not committed
KB_HASH=$(git log -1 --format="%H" -- knowledgeBase/)
GRAPH_HASH=$(git log -1 --format="%H" -- graph/)
# Ensure graph is not ahead of kb
```

## Quick Commands

| Command | Description |
|---------|-------------|
| `ewankb-git status` | Show unstaged changes per layer |
| `ewankb-git log --layer kb` | Show kb commit history |
| `ewankb-git diff <layer>` | Show changes since last commit |
| `ewankb-git rollback <layer>` | Revert last commit on layer |
