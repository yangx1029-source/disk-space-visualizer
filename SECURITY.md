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

The local Dashboard is intentionally restricted to an IPv4 loopback address or
`localhost`. It validates `Host` and `Origin` headers and is not designed to be
published through a reverse proxy, LAN bind, tunnel, or public Internet endpoint.
Please include the API `request_id` and relevant redacted JSONL log entries when
reporting a Dashboard issue; local filesystem paths can be sensitive.
