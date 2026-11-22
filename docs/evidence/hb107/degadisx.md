# HB-107 Part A: degadisx's reproduction record, read

**What was read.** Four files of `lyullee/degadisx` at commit
`35ffd39b4fd1e784ae0a26a38b21ef24c6485eaa`, fetched 2026-11-06 at rung 1 by
`scripts/fetch_allowlisted.py` from raw.githubusercontent.com (`corpus/fetch_log.jsonl`). They are held
in `corpus/raw/` as `reference-only` rows:

| doc_id | file | lines | sha256 |
|---|---|---|---|
| `degadisx-readme` | `README.md` | 69 | `82e5d9bb26d0a67d…` |
| `degadisx-reproduction` | `docs/reproduction.md` | 21 | `7df936511db5bb14…` |
| `degadisx-license` | `LICENSE` | 31 | `5ebd40fec464b105…` |
| `degadisx-pyproject` | `pyproject.toml` | 44 | `8a63cbfb431b93d2…` |

**Which commit is release 0.1.4.** github.com's smart-HTTP ref advertisement
(`docs/evidence/hb107/probe/raw/hb107-degadisx-info-refs.bin`) gives `HEAD -> refs/heads/main` at
`35ffd39b…`. Tag `v0.1.4` (tag object `f80df6f8…`) peels to the same commit. So release 0.1.4 is the
default branch head. The other tags are `v0.1.0`, `v0.1.2` and `v0.1.3`. `pyproject.toml:7` reads
`version = "0.1.4"`. github.com's robots.txt disallows its commit, tag and release Atom feeds and its
tags page to this client (`probe/probe_fetch_log.jsonl`), and api.github.com is not on this task's
Network line. So the advertisement is the rung-1 record of the SHA.

Line numbers below are the held files' lines (`R` = `docs/reproduction.md`, `M` = `README.md`).

## 1. What it reproduces, and to what tolerance

degadisx's audit has two layers (R5).

**Layer 1: a reference executable against EPA's listings (R7).** "Five EPA examples were replayed: B9
steady, B9 transient, EX1, EX2, and EX3."
- "The steady and jet/listing cases reproduced all non-timestamp listing lines."
- "The transient B9 listing had eight differences confined to seventh-significant-digit numerical
  formatting."
- These are the same five cases HB-102 ran: EX1, EX2, EX3, B9 and B9T
  (`docs/evidence/hb102/inventory.md` section 5).

**Layer 2: the Python code against a "source-built reference executable" (R8).**
- "Input-deck scalars and density-table values matched exactly."
- "scalar thermodynamic and closure checks differed only at floating-point round-off."
- At driver level: "step sequences were within 6e-10 relative for the DEG1 check, and representative
  profile/handoff values within 1e-6."
- "Some full-driver concentration outputs differed by up to about 3%, depending on quantity, because
  the original implementation intentionally retains coarse internal tolerances (including `ADDHEAT`
  settings)."
- No per-case table is published. The record does not say which of the five cases the 3 percent
  concentrations come from, or how many outputs it covers.

## 2. Routes covered and not covered

- **Covered (M7):** "the original model's ground-level steady and transient routes,
  pressurised-jet route, deck readers, and bridge from jet touchdown to the ground-level model."
  These are the four routes the task names. The five cases cover them: B9 is steady, B9T transient,
  and EX1 to EX3 are the jet, with EX2 and EX3 also bridged to the ground.
- **Added since 0.1.2, not DEGADIS 2.1 (M41-59):**
  - a `SourceLedger` handoff;
  - a "directed JETPLU source handoff", described as "a two-dimensional wind--vertical calculation";
  - an optional LH2 pool adapter (M22-31).
  The README says these do "not modify the JETPLU equations" (M54-55) and do "not add an LH2 pool or
  jet-impact model to the reproduced DEGADIS physics" (M30-31). The reproduction record does not say
  they were audited.
- **Not covered:** "it is not an LH2 extension and does not contain DEGALI research modules" (M3). A
  yawed horizontal release or cross-wind component "is not converted into a three-dimensional
  fixed-receptor prediction" (M58-59).

## 3. Does it read the same input files as the Fortran?

**Yes, by its own statement, and that is all.**
- M7 lists "deck readers" among the original routes.
- R8 says "Input-deck scalars and density-table values matched exactly" against the reference executable.
- But the decks are not in the repository (R14: "The reference Fortran code, EPA example input decks,
  EPA output listings, compiled executables, and all third-party data were used only in the local
  audit"; M37). A user must "obtain the materials from their original rightsholder/source" (R14).
- The corpus already holds those materials as `epa-degadis-source` and `epa-degadis-testcases`
  (reference-only since HB-106).

## 4. Its stated limits, quoted

- R10: "These are reproduction checks, not experimental validation. No claim is made that all outputs
  are bit-identical or that the software is valid outside the original model's assumptions."
- M7: "It is intended for transparent reproduction, software inspection, and research use. It is not a
  substitute for site-specific consequence-model selection or safety engineering review."
- R8: some full-driver concentrations differ "by up to about 3%".
- `pyproject.toml:15`: "Development Status :: 4 - Beta".

## 5. Against HB-102's own reproduction

| | HB-102 (gfortran, `ported` build) | degadisx 0.1.4 (its own record) |
|---|---|---|
| cases | EX1, EX2, EX3, B9, B9T | the same five (R7) |
| reference executable vs EPA listings | max relative difference 8.1e-7 (`b9t.tr2`), and only after the `ESTRT1.FOR` port edit. The dialect-patched build without it ran the ground-level stage with `EPSILON` = 0 (`.TR3` off by up to 15%). | "all non-timestamp listing lines" for steady and jet; B9T, eight differences in the seventh significant digit (R7). A seventh-digit difference is about 1e-6 relative, the same order as HB-102's 8.1e-7. |
| how the reference executable was built | three platform shims, three syntax edits, one `EQUIVALENCE` edit (`run_degadis.py`, `DIALECT_EDITS`, `PORT_EDITS`) | "source-built" (R8). No compiler, flags or source edits are named. |
| Python vs Fortran | not attempted | about 1e-6 on profiles and handoffs; up to about 3% on some full-driver concentrations (R8) |

**Does degadisx mention the `/ERROR/` COMMON padding or `EPSILON`?** **No.** A case-insensitive search
of all four held files for `error`, `epsilon`, `equivalence`, `common`, `gfortran`, `compiler`,
`entrain`, `align` and `pad` finds no line. The nearest is R8's "`ADDHEAT` settings", a different
numerical parameter.

So the record cannot say whether its "source-built reference executable" met the `EQUIVALENCE`
misread HB-102 found, or how it avoided it. Its Layer 1 result, all non-timestamp lines for B9
steady, is what HB-102's `ported` build gets and its `patched` build does not get. That suggests the
reference build had working `/ERROR/` storage, but the record does not say how. degadisx's data policy
(`docs/data-policy.md`, M37) and `CHANGELOG.md` were not fetched. The task names neither.

## 6. What this gives DN-020, without ruling

- degadisx is a real, documented port of DEGADIS 2.1. It covers the routes HB-102 ran. Its record of
  reproducing the EPA listings is of the same order as HB-102's.
- Its Python-against-Fortran agreement is weaker than its Fortran-against-listing agreement: up to
  about 3% on some concentrations. It says so itself, and that is a value DN-020 can quote.
- It is MIT licensed, beta, from one author, version 0.1.4 (2026-09-12 on PyPI). It depends on
  `numpy>=1.23` and `scipy>=1.10` (`pyproject.toml:21`).
- It was not installed or run here (the task's "Not in this task").
