"""CI support for the frozen prospective models (engine, C3, C1, A, A+odds; frozen-2026-10-13).

The frozen models and their harness are *not* in this package: they ship byte-for-byte in
``prospective/bundle/frozen-2026-10-13.tar.gz`` and are verified against its ``manifest.json``
before every use. This package only checks that bundle, fetches and verifies the inputs the bundle
does not carry, and decides — fail closed — which models' advice may be published.
"""
