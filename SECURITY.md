# Security policy

Thank you for helping keep FlowlyStack and its users safe.

## Report a vulnerability privately

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting instead: open the **Security** tab of this repository and choose **Report a vulnerability**. Only the maintainer can see your report, and we can talk privately inside GitHub.

Please include:

- what you found and why it matters,
- the steps to reproduce it,
- the FlowlyStack version and how you run it (Docker or from source, your system),
- anything else that helps, such as a screenshot or a short proof of concept.

Please do not include real prompts, tokens or passwords in your report.

## What to expect

- We aim to reply within about a week.
- We will tell you whether we can reproduce the problem and keep you updated until it is fixed.
- When a fix is released, we are happy to credit you in the release notes, if you would like that.

FlowlyStack is a small project run by one person, so please be patient. We take every report seriously.

## Supported versions

Only the latest release receives security fixes.

## Scope

FlowlyStack is built to run on your own computer, with a local owner login. It is not meant to be open on the internet without care.

- If you want to reach it from outside your computer, follow [docs/remote-access.md](docs/remote-access.md).
- Reports that depend on turning the login off, or on exposing the app to the internet without the steps in that guide, are out of scope.
- Problems in a third-party tool we depend on (for example Docker or Meilisearch) are best reported to that project, but please tell us if FlowlyStack's use of it makes the problem worse.
