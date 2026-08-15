# CLAUDE.md

## Git Operations

Git workflows are defined as project skills. Use the corresponding skill for each task:

- **`/commit`** — commit message format, `Co-Authored-By` line, and conventional commit types. Invoke for every `git commit`.
- **`/release`** — version bump checklist, version bump commit, annotated tag, push, and GitHub Release body template. Invoke when publishing a new release.

### AI Model Configuration

The AI model used in this project is **DeepSeek-V4-Pro**. Configured in skills as:

```
{{AI_MODEL_NAME}} = DeepSeek-V4-Pro
{{AI_MODEL_EMAIL}} = noreply@deepseek.com
```

### Release Configuration

Repository URL for the `/release` skill:

```
{{REPO_URL}} = https://github.com/zjykzj/InferForge
```
