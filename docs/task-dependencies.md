# Simplified task dependencies

Only prerequisite relationships are shown. “Live gate” means implementation may start from the frozen contract, but the named task must exist before the combined milestone can pass.

| Task | Depends on |
| --- | --- |
| C0 | None |
| A1 | C0 |
| B1 | C0; A1 before integration/merge |
| A2 | A1; B1 for the live G2 path |
| B2 | A1, B1; A2 for live API integration |
| A3 | A2, B1 |
| B3 | B2, A3 |
| A4 | A3, B2 |
| B4 | B3, A3, A4 |
| A5 | A4, B4 |
| B5 | B4, A4, A5 |
| B6 | B5, A5 |
| A6 | A5, B5, B6 |

## Merge gates

| Gate | Depends on |
| --- | --- |
| G1 | A1, B1 |
| G2 | A2, B2 |
| G3 | A3, B3 |
| G4 | A4, B4 |
| G5 | A5, B5 |
| G6 | A6, B6 |

In one line: `C0 -> (A1 + B1) -> (A2 + B2) -> (A3 + B3) -> (A4 + B4) -> (A5 + B5) -> (B6 -> A6)`.
