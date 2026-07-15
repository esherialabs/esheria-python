# Contributing

Thank you for helping improve the Esheria CLI, Python client, and MCP server.

Before starting a substantial change, open an issue describing the problem,
the proposed public-package behavior, and any compatibility or security
impact. Keep contributions within the Apache-2.0 package boundary. Do not add
customer data, credentials, private source locations, licensed regulatory
corpora, or code from Esheria's hosted-service implementation.

For a local change:

1. Use Python 3.11 or newer.
2. Install development dependencies with `python -m pip install -e '.[dev]'`.
3. Run `python -m pytest -q`.
4. Run `python -m build` and `python -m twine check dist/*`.
5. Confirm `esheria --help`, `esheria mcp serve --help`, and
   `esheria-mcp --help` from the built wheel.

By submitting a contribution, you agree that it is licensed under the Apache
License, Version 2.0, and that you have the right to submit it.
