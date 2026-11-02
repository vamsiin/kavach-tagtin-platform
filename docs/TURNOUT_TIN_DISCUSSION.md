# Turnout TIN placement: discussion brief

For the RFID Tool review meeting. Purpose: agree how a turnout's two TINs are **entered**, **read** and **drawn**,
so the generated layout matches the approved one. Nothing in sections 4-5 is built yet; each item needs a yes / no
or a correction from the signalling team.

## 1. What the team reported

The TIN inputs are provided correctly, but the tool does not read them accurately for turnouts. In some places the
two TINs of a turnout overlap or collide in the generated layout.

## 2. How the tool reads TIN input today

| Step | What the tool does |
|---|---|
| Input | TIN rows: TIN number, section (Station / Block), start and end chainage, colour, and **the line it is on**. There is no "turnout TIN" field. |
| Line bands | Each line is drawn as a band, coloured by the TIN rows on that line. |
| Turnout | A turnout is drawn from its **A-end** (on one line) to its **B-end** (on the line it leads to). The first half takes the colour of the TIN found at the A-end, on the A line. The second half takes the colour of the TIN found at the B-end, on the B line. The two halves meet at the centre. |
| Number labels | TIN numbers are written once per TIN per line, beside the line at the middle of its stretch. **Nothing is written on a turnout.** |
| "Stray" rows | A TIN row that ends at a T tag **and** whose number also exists on another line is treated as a turnout piece entered by mistake: it is not drawn on the line, and the data check says "delete this row". |
| T tag | One T tag per turnout, linked by "Linked element", or else any T tag between the A-end and B-end. |

## 3. What Aler shows (current data, after this release's fixes)

| Points | Lines | A-end | B-end | T tag | TIN at A-end | TIN at B-end |
|---|---|---|---|---|---|---|
| P11 | DN MAIN to UP MAIN | 262.067 | 261.979 (from T tag) | R-838 | N-169 Yellow | N-179 Light Blue |
| P12 | DN MAIN to COMMON LOOP | 262.103 | 262.197 (from T tag) | R-834 | N-169 Yellow | N-169 Yellow |
| P13 | UP MAIN to UP LOOP | 262.254 | 262.148 (from T tag) | R-843 | N-179 Light Blue | N-188 Pink |
| P18 | UP MAIN to UP LOOP | 262.992 | 263.086 (from T tag) | R-842 | N-177 Pink | N-177 Pink |
| P19 | DN MAIN to COMMON LOOP | 263.009 | 262.923 (from T tag) | R-836 | N-171 Light Blue | N-186 Yellow |
| P20 | DN MAIN to UP MAIN | 263.140 | 263.044 (from T tag) | R-840 | N-171 Light Blue | N-177 Pink |
| P17 | COMMON LOOP to siding | 263.050 | (siding) | none | N-186 Yellow | not a KAVACH line |

## 4. Causes found so far

1. **The Aler register is missing the approved correction data.** `sample_data/ALER_Points_LC_from_approved_layout.csv`
   (A-end and B-end of every points) and `ALER_Tags_corrections_turnouts.csv` (each T tag linked to its points) were
   never uploaded. Without them the B-ends were estimated and the T tags were not tied to their turnouts. This is the
   main reason T tags were not at the point centre.
2. **The T tag is at the centre of its points.** In the approved data every T tag chainage equals (A-end + B-end) / 2, within 1 m:
   R-838 262023 against 262022.5, R-834 262150, R-836 262966 against 262965.5, R-840 263092, R-842 263039, R-843 262201 against 262202.
   Fixed in this release: the T tag is drawn at the centre, and where a B-end is missing it is worked out as
   2 x T tag - A-end (all six Aler values then agree with the approved file to within 1 m).
3. **The far end of a turnout often lies beyond the TIN rows of the line it leads to** (P18 B-end 263.086 is past the
   UP LOOP TIN, which stops at 263.031; P19 B-end past the COMMON LOOP TIN). The tool found no TIN and painted that half
   grey. Fixed: the nearest TIN within 60 m is used.
4. **Turnout TIN rows entered on the loop are hidden as "stray".** If the team enters a turnout's TIN as a row on the
   loop (the same number also on the main line), rule 2 above removes it from the drawing. This may be the
   "not reading the input" the team sees. It needs a decision (question Q1).
5. **No TIN number is shown on a turnout**, so a turnout with two different TINs shows one colour change and no
   numbers. Not fixed; see R3.

## 5. Proposed rules (for decision)

| # | Proposed rule | Default if no answer |
|---|---|---|
| R1 | A turnout has two TINs: one for the half nearer the A-end, one for the half nearer the B-end. They meet at the point centre, where the T tag stands. | As now |
| R2 | Each points gets two optional inputs, "TIN on A half" and "TIN on B half". If blank, they come from the line TINs at each end (as now). If filled, they override the line TINs. | Not built; needs a database field |
| R3 | The TIN number is written beside each half of the turnout only where it **differs** from the TIN on the line it joins, in the open space beside the diagonal, one label per half, never on top of each other. | Not built |
| R4 | A TIN row that describes a turnout piece is accepted, not hidden. It colours its half of the turnout and is not drawn on the loop. The "delete this row" warning goes. | Rows still hidden |
| R5 | Where both halves have the same TIN (P12, P18), the turnout is one colour with one label. | As now |
| R6 | The T tag must lie at the centre of its points (within 2 m). Otherwise: warning "T tag not at point centre". | Warning exists only for "outside the turnout" |
| R7 | Two turnouts whose centres are closer than 30 m get their labels offset on opposite sides of the diagonals. | Labels are pushed apart by the packer |

## 6. Questions for the signalling team

1. **Q1.** How is a turnout's TIN entered on the approved layout and in the SIP: as a TIN on the loop that covers the
   diagonal, or as its own TIN for the turnout? Please mark one turnout (P19) on the approved layout.
2. **Q2.** Does a turnout always have two different TINs, or can both halves be one TIN (Aler P12, P18)? When one,
   is the T tag still needed?
3. **Q3.** Is the point centre the exact midpoint of the A-end and B-end, or the toe / heel of the points?
4. **Q4.** Which line's TIN does the A half take when two TINs overlap there (for example N-171 and N-172 around P20)?
5. **Q5.** Where do the approved layouts write the TIN numbers of a turnout: on the diagonal, or only on the lines?
6. **Q6.** Should the siding after P17 carry a TIN (it is outside KAVACH, drawn white)?

## 7. What we need before the meeting

- A zoomed crop of the approved Aler layout around P11-P13 and P18-P20.
- The SIP / ToC list of TINs per turnout.
- Confirmation that the two correction CSVs above are the approved A-end / B-end / T-tag data, so they can be
  uploaded to the Aler register.

## 8. Decisions

| Date | Decision | Owner |
|---|---|---|
|  |  |  |
