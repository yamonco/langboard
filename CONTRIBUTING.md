# Contributing to Langboard

Thanks for your interest in contributing! We welcome pull requests, issues, and feedback.

## Before You Start

- Make sure there's no open issue or PR that already addresses your change.
- If your change is significant, open an issue first to discuss your idea.
- Be respectful and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## How to Contribute

1. Fork the [Langboard GitHub repository](https://github.com/yamonco/langboard)
2. Create a new branch following [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)
   - fix/...
   - feat/...
   - ...
3. Submit a pull request to the `main` branch with a clear title and description. Reference any issues fixed, for example `Fixes #1234`. Ensure your PR title follows the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format.
4. A maintainer will review your PR and may request changes.

## Development Environment Setup

For detailed instructions on setting up your local development environment, see [development guidelines](./DEVELOPMENT.md).

## Pull Request Checklist

### GitHub collaboration language

Use English for pull request titles, descriptions, review comments, and automated
receipts. Langboard project cards, descriptions, and native checklists may use
Korean. Automation must preserve user supplied requirement titles when quoting
them, while writing its own labels and explanations in English.

The GitHub collaboration language check detects Korean prose when a pull request,
comment, or review is created or edited. Pull request titles must be English.
Intentional localization fixtures, user input examples, and external quotations
are allowed in descriptions and comments. Put short literal examples in inline
code, longer fixtures in fenced code blocks, and quoted content in Markdown
blockquotes. For a longer localized example, wrap only the example with
`<!-- langboard:localized-example:start -->` and
`<!-- langboard:localized-example:end -->` on separate lines. Keep the surrounding
explanation in English. These exceptions are for source material, not general
collaboration prose.

The check uses default branch code and read-only repository permissions. It reads
event text as data and does not execute pull request code or modify comments.

### Development checks

- Run `make format`
- Run `make lint`
- Run `make unit_tests`
- Update relevant documentation when behavior or configuration changes

Thank you for helping improve Langboard!
