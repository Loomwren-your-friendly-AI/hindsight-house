These files are test fixtures. They are unmodified copies of the stock Hindsight memory plugin that the hindsight-house plugin extends:

- stock-base/ is the stock plugin, version 1.2.3.
- stock-variants/stock_121/ is the stock plugin, version 1.2.1.
- stock-variants/stock_main_init.py is a variant of the stock __init__.py (the tests call it "main"), used by the drift-guard tests.

The tests copy them into a scratch folder and never run them outside the test child process.

Licence: the upstream project is MIT licensed, Copyright (c) 2025 Vectorize AI, Inc. The licence text is in LICENSE-hindsight-upstream. It was fetched on 2026-10-29 from https://raw.githubusercontent.com/vectorize-io/hindsight/main/LICENSE (SHA-256 01fde0bedf83bdc185065d7af524a61690efe576a67f922eaff3a1280c17b63a).
