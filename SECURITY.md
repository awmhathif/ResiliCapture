# Security policy

## Supported versions

Security fixes are targeted at the latest published ResiliCapture release and the current development branch.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a vulnerability that could expose recordings, local files, credentials, or permit code execution. Use GitHub private vulnerability reporting when it is enabled for the repository, or contact the maintainers through the private security contact listed on the repository.

Include the affected version, reproduction steps, impact, and any proof-of-concept material needed to understand the issue. Do not include private screen recordings unless they have been intentionally sanitized.

## Security principles

ResiliCapture is designed to process recordings locally. Release builds should not add telemetry, cloud upload, or remote-control behavior without explicit documentation and user consent. Completed recovery segments are retained until a final output is verified or the user explicitly deletes them.
