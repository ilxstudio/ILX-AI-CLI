# Governance

This document describes how the ILX AI CLI project is governed, how decisions are made,
and how contributors can grow their role in the project.

## Project Roles

### Maintainer

The ILX Studio team holds maintainer status. Maintainers have write access to the repository,
approve and merge pull requests, cut releases, and make final decisions on direction and
policy. All maintainer actions are subject to this document and the Code of Conduct.

### Contributor

Anyone who has had a pull request accepted into the repository. Contributors are listed in
the commit history and may be acknowledged in release notes. There is no formal process to
become a Contributor — submit a PR that gets merged.

### Community Member

Anyone who participates in the project: opens issues, comments on PRs, answers questions in
Discussions, or uses and promotes ILX AI CLI. All community members are expected to follow
the Code of Conduct.

## Decision Making

### Feature Approval

New features must be approved by at least one maintainer before work begins on a significant
implementation. Open a GitHub issue describing the feature and its motivation. Maintainers
will triage it within two weeks. Work on small bug fixes and documentation improvements can
proceed without pre-approval.

### Merging Pull Requests

A pull request requires:

- At least one approving review from a maintainer
- All CI checks passing (tests, lint, architecture fitness, coverage threshold)
- No unresolved review comments

Maintainers may merge their own PRs after CI passes if the change is a small fix and no
review is pending after 48 hours.

### Breaking Changes

Breaking changes require a major version bump and a deprecation window of at least three
releases. The deprecated behavior must emit a runtime warning during the deprecation window.
Breaking changes must be documented in `docs/CHANGELOG.md` under a `### Breaking` heading.

## Current Maintainers

| Name | Contact |
|------|---------|
| ILX Studio | arivera@riveraeng.com |

## Becoming a Maintainer

Maintainer status is granted by the existing maintainers to contributors who demonstrate:

- Sustained, high-quality contributions over multiple releases
- Good judgment on design and code quality decisions
- Familiarity with the architecture fitness rules and coding standards
- Trustworthiness and a constructive presence in the community

There is no fixed timeline. If you believe you meet the bar, reach out at arivera@riveraeng.com.

## Security Issues

Do not open public GitHub issues for security vulnerabilities. Report them privately to
**arivera@riveraeng.com**. Maintainers will acknowledge receipt within 72 hours and work
with the reporter on a coordinated disclosure timeline.

## Code of Conduct Enforcement

Enforcement of the Code of Conduct is at maintainer discretion following the four-step
enforcement ladder described in `CODE_OF_CONDUCT.md`. Reports go to arivera@riveraeng.com.
All reports are treated confidentially.
