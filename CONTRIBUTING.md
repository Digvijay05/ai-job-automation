# Contributing to AI Job Automation

Thank you for your interest in contributing to the AI Job Automation project! We welcome contributions from the community to help improve this tool.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Branching Strategy

We follow a strict Git flow:
- **`main`**: Production-ready code. Protected branch.
- **`develop`**: Integration branch for new features.
- **`feature/feature-name`**: For new features.
- **`fix/bug-name`**: For bug fixes.
- **`hotfix/issue-name`**: For critical production fixes.

## Commit Standards

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only changes
- `style:` Changes that do not affect the meaning of the code (white-space, formatting, etc)
- `refactor:` A code change that neither fixes a bug nor adds a feature
- `perf:` A code change that improves performance
- `test:` Adding missing tests or correcting existing tests
- `chore:` Changes to the build process or auxiliary tools and libraries such as documentation generation

**Example:** `feat: add scraper module support for LinkedIn`

## Pull Request Guidelines

1.  Ensure your code adheres to the project's coding standards.
2.  Update documentation for any new features.
3.  Ensure all tests pass.
4.  Provide a clear description of the changes in the PR.
5.  Link related issues.

## Code Review Process

All PRs require review from at least one maintainer. We look for:
- Correctness
- Readability
- Security
- Performance
- Test coverage

## Development Setup

1.  Clone the repository.
2.  Copy `.env.example` to `.env` and configure secrets.
3.  Run `docker-compose up -d --build`.
4.  Access n8n at `http://localhost:5678`.

Thank you for contributing!
