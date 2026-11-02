# Aler layout: generated vs approved CAD (V2.0.3), full-resolution check

Source of the approved drawing: the vector PDF plot `A01_01_0001_Aler_RFID_TIN_TAG_Layout_V2.0.3_03July2026-Model.pdf`.
Every number below was read from that PDF's text and drawing data, not from an image. Side-by-side pictures:
`compare_centre.png`, `compare_right.png`. Generated layout = this release's code with the Aler correction files uploaded.

## Matches the approved drawing

| Item | Result |
|---|---|
| Tag numbers | All 59 register tags appear on the approved drawing; none missing, none extra |
| ABS values | 57 paired ABS values match to the metre. R-862 shows 261.083 (ABS-1, physical) in the register and "261.144 / 261.083" on the CAD, which is intended |
| Tag types | All 31 that could be paired (N, S, T, X, G, L, A) match |
| TIN numbers | The same 15 TINs (169, 170, 171, 172, 177, 178, 179, 185, 186, 187, 188, 217, 218, 221, 222) |
| Tag labels | Boxed tag number with the ABS under it, directly beside the line, as on the CAD |
| Turnouts | A-end, B-end and T tag at the point centre now agree with the approved P11-P20 data |

## Differences

| # | Difference | Approved CAD | Generated | Type |
|---|---|---|---|---|
| 1 | Tag directions | Triangle tips read from the drawing | 13 of 51 readable tags differ: R-785, R-787, R-789, R-795, R-827, R-829, R-835, R-837 (CAD: Reverse, register: Nominal) and R-792, R-794, R-800, R-826, R-828 (CAD: Nominal, register: Reverse) | Data in the register |
| 2 | TIN number labels | Each TIN number written once (15 labels) | N-169 and N-177 written twice (17 labels) | Drawing |
| 3 | Reference-distance lines | 14 x 200 m, plus 123 m, 125 m, and 2 x 600 m (gate). Only for the approach to a main signal or stop board | Extra: 40, 100 (x2), 168, 242, 243, 316 m. Missing: 200 m for S26 (R-827 to R-829) and for both stop boards (R-794 to R-792, R-828 to R-826) | Drawing rule, plus item 1 |
| 4 | Signal head symbol | Black outline lamp symbols (circle with a diagonal slash), one per lens: 3 for a distant, 4 for a home; double yellow is a second yellow lens; no colours or letters | Coloured lamps with R / Y / G letters; double yellow drawn as one wide lamp | Drawing |
| 5 | TIN colours | Cyan (171, 179), rose (172, 177, 188), blue (170, 178, 185, 187), yellow (169, 186), orange (218, 222), dark green (217), light green (221) | Light blue (120,190,240) for 171 / 179, lighter pink for 172 / 177 / 188, and other shades | Palette |
| 6 | Sand hump | Half disc at the line end, with a bar | Triangle on the line | Drawing |
| 7 | Not drawn | Track circuit names (CLAT, DMAT ...), "(Axle Counter Section)", "(IB/BPAC Section)", "UP AC Clear", fouling mark boxes "F / M" at points, vertical A-end / B-end ABS beside each points, inner box and dot on the station building | Only what is entered as annotations (track circuits, sections, features). Fouling marks, per-points ABS text and the building detail are not drawn | Data and drawing |
| 8 | Neighbour station text | "(PEMBARTI-8.83KM) (PBP) / KAZIPET JN (KZJ)" | "PEMBARTI (ID 00102: +8.83 KM)". Station codes (PBP, WP, SC) are not stored | Format |
| 9 | Total tags | The approved sheet says "TOTAL NO. OF TAGS - 057" but draws 59 distinct tags | Says 059 (the real count) | Approved sheet inconsistent |

## Suggested order

1. Confirm the 13 tag directions with the signalling team (item 1), then correct the register. The CAD is the authority.
2. Fix the drawing: one label per TIN (2), the reference-distance rule (3), the TIN palette (5), the sand hump (6).
3. Redraw the signal heads as slashed-circle lens symbols (4), with the lens count per signal type.
4. Add fouling marks and per-points ABS text (7).
