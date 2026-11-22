# HB-124 Part A step 2: the SLAB test cases' material inputs

**Sources.**
- `epa-slab-users-guide-1990`: Ermak, *User's Manual for SLAB*, LLNL, June 1990. Held PDF sha256
  `2ce0e7b775ee20972fdc6e751e6cbb109d6d881ab0a46c9ab18ccbe6e655503d`. The PDF has no text layer, so every guide page
  below was read from its rendered image (pdftoppm, 110 to 200 dpi), as HB-66's `rendered:` readings were.
- `epa-slab-code`: `slab.zip`, sha256 `0d19cf8e91b8ecfd958463bbe0da3fa94917b7d6a594dc4ed0f25353d4f41df4`. Its input
  files `SLAB/INPR1` to `SLAB/INPR4` were extracted to scratch:

  | file | sha256 |
  |---|---|
  | INPR1 | `79c2e345…` |
  | INPR2 | `94bd9d6b…` |
  | INPR3 | `7c6786b8…` |
  | INPR4 | `c98ea9e1…` |

  The code is `reference-only` (HB-106). Its values are transcribed here as numbers, and the pack quotes none of them.

**The input order.** These are input lines 3 to 11, after IDSPL and NCALC. The order is the guide's Table 1, "Definition
of input variables" (PDF p. 50; HB-102 `inventory.md` section 3): WMS (kg/mol: "Molecular weight of source material
(KG)"), CPS (J/kg-K), TBP (K), CMEDO, DHE (J/kg), CPSL (J/kg-K), RHOSL (kg/m3), SPB, SPC.

## Every test case

| case | IDSPL | material (guide section) | WMS | CPS | TBP | CMEDO | DHE | CPSL | RHOSL | SPB | SPC | where |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PR1 | 1 (evaporating pool) | methane, LNG (4.1) | 0.016043 | 2238. | 111.7 | 0. | 509900. | 3348.5 | 424.1 | -1. | 0. | INPR1 lines 3 to 11 |
| PR2 | 2 (horizontal jet) | ammonia (4.2) | .017031 | 2045.9 | 239.57 | .81 | 1170000. | 4611.8 | 603. | 2976.01 | 0. | INPR2 lines 3 to 11 |
| PR3 | 4 (instantaneous) | methane (4.3) | 0.016043 | 2238. | 111.7 | 0. | 509900. | 3348.5 | 424.1 | -1. | 0. | INPR3 lines 3 to 11 |
| **PR4** | 3 (vertical jet) | **chlorine (4.4)** | 0.070906 | 498.1 | 239.1 | 0.88 | 287840. | 926.3 | 1574. | 1978.34 | -27.01 | INPR4 lines 3 to 11 |

The materials are identified by WMS, which equals the molar mass in kg/mol, and by the guide's section text. PR1's and
PR3's SPB of −1. selects SLAB's default saturation-pressure option (the guide, PDF p. 53, printed p. 47: "specifying
the value of SPB to be '−1.0' and the value of SPC to be '0.0'").

## Chlorine: PR4, as the guide prints it

- **Section 4.4, "Vertical Jet Release"** (PDF p. 133, printed p. 127): "This problem is a hypothetical release of
  vapor chlorine from a vertical jet."
- **The input echo, "Output File : OUTPR4"** (PDF p. 136, printed p. 130; the page is printed rotated). PROBLEM INPUT
  reads `WMS = 0.070906`, `CPS = 498.10`, `TBP = 239.10`, `CMEDO = 0.88`, `DHE = 287840.`, `CPSL = 926.30`,
  `RHOSL = 1574.00`, `SPB = 1978.34`, `SPC = -27.01`.
  - These equal INPR4's lines 3 to 11.
  - The page's own "RELEASE GAS PROPERTIES" block repeats them in E-format: `CPSL = 9.2630E+02`, `RHOSL= 1.5740E+03`.
  - That block's DHE reads `2.8784E+06` on the printed page, at 300 dpi, and the kit's docling text reads the same.
    The distributed `SLAB/OUTPR4` (line 46) and HB-102's gfortran rebuild (`docs/evidence/hb102/runs/slab/nuout4`
    line 46) both print `2.8784E+05`, which is 287840.
  - The printed exponent is a misprint or a defect of the scan, and the pack does not read it. It reads the PROBLEM
    INPUT line, `DHE = 287840.`, which agrees with INPR4, OUTPR4 and Table 2.
- **Table 2, "Material properties in SI units for use in the SLAB code"** (PDF p. 54, printed p. 48). The chlorine row
  is `Cl2 .070906 498.1 239.10 287840. 926.3 1574. 1978.34 -27.01`, with γ 1.308. These are the same values; the
  pack records them as `agree` cross-checks.

**The candidate values the pack takes** (`packs/src/materials_properties.yaml` `slab_test_input`; provenance "SLAB
user's guide test-case input, 1990"; tier `model-test-input`):

| field | as printed | in the pack | temperature |
|---|---|---|---|
| `heat_of_vaporization_j_mol` | DHE 287840. J/kg | 287840. × 0.070906 = **20,409.58304 J/mol** | 239.10 K: Table 1 and section 3.1.2.5 define DHE as the "Heat of vaporization at the boiling point temperature" (PDF p. 53) |
| `liquid_heat_capacity_j_mol_k` | CPSL 926.30 J/kg-K | 926.30 × 0.070906 = **65.6802278 J/mol/K** | none printed |
| `liquid_density_kg_m3` | RHOSL 1574.00 kg/m3 | **1574.0 kg/m3** | none printed |

**Where the guide's values come from: not stated.**
- The guide prints no source for Table 2 or for the test cases' inputs.
- It says, PDF p. 53 (printed p. 47): "Values of material properties can be found in a number of references including
  Reid, Prausnitz, and Sherwood (1977) and Braker and Mossman (1980). … Table 2 lists recommended values for the
  properties of a limited number of materials in the appropriate units to be used in the SLAB code." Its references
  list Reid, Prausnitz and Sherwood, *The Properties of Gases and Liquids*, 3rd ed. (PDF p. 150).
- That names where values *can be found*. It does not attribute Table 2's values to either reference, and no
  temperature is printed for CPSL or RHOSL.
- So the values are labelled for what they are: a program's recommended and test-case inputs, not a
  benchmark-validated property (DN-020 ADDENDUM-02).

## Where SLAB's other test inputs differ from the pack's reference-table values (for the Desktop, not taken)

Ammonia's PR2 inputs and Table 2's ammonia row differ from each other:

| quantity | PR2 | Table 2 |
|---|---|---|
| DHE (J/kg) | 1170000. | 1370840. |
| RHOSL (kg/m3) | 603. | 682.8 |
| CPSL (J/kg-K) | 4611.8 | 4294. |
| TBP (K) | 239.57 | 239.72 |

The NIST Fluid Systems row the pack takes for ammonia (240.00 K) prints 681.43 kg/m3 and 76.058 J/mol*K, that is,
4,465.9 J/kg-K by the molar mass 17.031. Table 2 is close to NIST's density; PR2's 603 is not. A test case's inputs
are scenario-specific, which is one more reason the pack labels chlorine's values `model-test-input` and reads every
material that NIST Fluid Systems covers from NIST.
