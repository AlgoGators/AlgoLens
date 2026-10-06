# Frozen fake-client inputs

`qt-eval-v1.json` and `qt-equity-finalization-wire.json` are unchanged synthetic
inputs copied from trade-ngin `b8962303ce306f62660d1c08ae1117139a3d75a3`,
`tests/contracts/`. Their `local-qt-controlled` build identity is deliberately
preserved: these tests validate client semantics using a fake/stopped transport,
not a selected native build. They require no sibling checkout or native artifacts.

Source SHA-256:

- `qt-eval-v1.json`: `f90d512db09e50bc8777c38918b6d108da6eb8b640f3b456b5a8a9bc601884f2`
- `qt-equity-finalization-wire.json`: `73482bb8422065f86e87a2637b680da6c10b1fc4b871562d4510b91a2652569b`

Native integration tests load the explicitly selected trade-ngin source fixture
and bind its request build identity to the selected compiled bundle instead.
