# Zero-Cost GitHub Architecture Policy

## Allowed production infrastructure

- Public GitHub repository.
- GitHub Actions on the standard `ubuntu-24.04` runner only.
- GitHub Releases for persistent result packages.
- GitHub Pages for the static result viewer and PWA.

## Disallowed infrastructure

- Google Cloud, AWS, Azure, Render, Oracle Cloud, Fly.io, Railway, Vercel server compute, Netlify server compute, or paid Cloudflare compute.
- Larger runners, macOS runners, Windows runners, self-hosted paid runners, GitHub Codespaces, GitHub Packages, Git LFS, and PAYG compute, storage, or APIs.
- A permanently running backend, cloud database, cloud queue, cloud VM, or embedded browser credentials.

## Frozen correctness boundary

MA_BOX_LONG_V1 Rev3, MA_BREAKOUT_ANALYTICS_V1 Rev3, legacy strategies, and canonical indicators, execution, portfolio, and metrics behavior remain unchanged. Cloud/mobile work is transport, packaging, static hosting, and user-interface work only.

## Public-source privacy policy

New or mutable public source, metadata, manifests, reports, logs, tests, generated artifacts, and documentation must not contain personal email addresses, absolute local paths, private LAN addresses, credentials, or local-machine identifiers.

Two immutable correctness artifacts are the only path exception. They may retain their historical absolute paths only while each file has its exact frozen SHA-256:

- `research/specs/MA_BREAKOUT_ANALYTICS_V1_REVISION_2_SOL_FROZEN_OUTPUT.txt` — `f01a50e304db4e654c57a0cfb560dc98ddc0a34aa478cd6248aa498f6434c69d`
- `research/specs/MA_BREAKOUT_ANALYTICS_V1_REVISION_3.md` — `0ac4a0fad9cbbc747b104b19e420e35368937e3359fd462786bd6317ad0d7647`

The public-candidate scanner verifies both exact paths and hashes. It rejects an absolute path anywhere else, and rejects either exception file if its bytes change.

## Governance

Architecture changes require a Sol High decision. Implementation after a frozen handoff is performed by Luna Max. Local mode remains supported; local databases, caches, reports, backups, credentials, and generated output remain local-only.
