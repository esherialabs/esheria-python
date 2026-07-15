# Release Provenance

This repository is a generated, allow-listed mirror of the source distributed
in the public `esheria` Python package. It is not a mirror of Esheria's private
application, infrastructure, regulatory corpus, or customer systems.

Each synchronized release includes `RELEASE_PROVENANCE.json`, which records the
reviewed source commit, package version, file hashes, aggregate tree hash, and
whether the source tree was clean. A release is publishable only when
`publishable` is `true` and CI passes against the exact generated tree.

The synchronization workflow builds this tree from an explicit file allow-list,
scans all files for credential and private-data patterns, builds the wheel and
source distribution, runs package and MCP tests, and installs the wheel in a
clean environment before a gated publication job may update this repository.

PyPI and MCP Registry releases are immutable. Corrections use a new patch
version and retain the prior release history.
