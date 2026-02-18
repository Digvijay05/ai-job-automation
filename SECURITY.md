# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability:

1.  **Do NOT open a public issue.**
2.  Email full details to security@example.com (replace with actual security contact).
3.  Include steps to reproduce the vulnerability.

 we will acknowledge your report within 48 hours and provide a timeline for a fix.

## Security Practices

- **Secrets Management**: Never commit secrets to the repository. Use `.env` files and secure environment variables.
- **Dependencies**: Regularly audit and update dependencies.
- **Code Review**: All code must pass security review before merging.
