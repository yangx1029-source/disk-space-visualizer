# Security Policy

## Supported versions

Security fixes target the latest release on `main`.

## Reporting a vulnerability

Please do not publish a filesystem path, XSS payload, or dependency issue in a
public issue. Use GitHub Security Advisories for this repository when available;
otherwise contact the maintainer privately through the GitHub profile. Include a
minimal reproduction, affected version, platform, and impact. Do not attach
private disk contents.

Reports are investigated before public disclosure. The application is read-only
by design: it scans, hashes, and writes reports, but never deletes user files.
