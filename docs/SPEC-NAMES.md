# Name and description table specification: entries `#4636`–`#4653`

Pokémon Pokopia — the nine name tables and the nine item-description tables of update build
655360 (game version 2.0.1a), as they are stored inside `LD_C0_R.BIN`.

Revision 2. Status: normative for the build named above. Every figure in this document was
produced by walking that build's container; the method, the reproduction command and the
digests are in §15. Numbers from any other build are unverified.

**What revision 2 changed.** Revision 1 linked an item row to its catalogue id with
`r = nameIndex`, the `u16` at `+34` of `#983`. That link is wrong by exactly three: the
verified rule is **`r = nameIndex + 3`** (§6.3). Every figure that depended on the old link has
been recomputed — the save resolution of §9 (**74 of 74** items resolve, not 42 of 69) and the
orphan count of §8 (**21**, not 301). The name-table geometry of §3–§7 and the test vectors of
§12 are unaffected: they address slots by `r`, and `r` was never in doubt. Seven inventory
slots, one of them renamed on purpose by a LayeredFS patch, now confirm the id → text link on
screen (§6.3) — the first in-game confirmation of any link in this document.

**Correction of 2026-11-03: the item id is 13 bits, `u32 & 0x1FFF`.** This document reported
**70 of 74** items resolving, with four ids above 4,600 and "no row in `#983`". That figure is
**false**. A save inventory record is 5 bytes whose item id is the low 13 bits of a `u32`
(§9.1); the measurement behind the old figure read the first two bytes as a plain `u16`, so four
`B00` records leaked their variant and placement bits into the id and looked like ids from a
newer data set. With the mask, **74 of 74** resolve and the four records are ordinary furniture
(§12.3). The catalogue side of §3–§8 and the vectors of §12 do not change; the record definition
is now stated in §9.1.

---

## 1. Scope and version

| | |
|---|---|
| Game | Pokémon Pokopia, version **2.0.1a** |
| Data set | update build **655360** (RomFS of the update) |
| Container | `LD_C0_R.BIN` (247,317,504 B) + `LI_C0_R.IDX` (393,536 B, 12,298 entries) |
| Tables covered | names: entries **#4645 … #4653**; descriptions: entries **#4636 … #4644** |
| Languages | nine, both blocks in the same order: `jp, en, fr, it, de, es, zh-TW, kr, zh-CN` |
| Byte order | little endian throughout |
| Character encoding | UTF-8, NUL-terminated |

**In scope.** The table header, the 3,001 × 32-byte per-id record area, the text pool, the
NUL-delimited slot array, the index arithmetic that maps a catalogue id to its singular and
plural strings, the per-language shapes of the six-slot block, the coverage of the catalogue
(which ids have text and which do not), the resolution of a real save's item list, the
invariants a reader may rely on, and test vectors.

**Out of scope.**

1. **The text itself.** This document defines where text lives and how to reach it. It quotes
   exactly twenty short labels, and only where they *are* the evidence: the seven item names of
   the on-screen anchors (§6.3) and the thirteen `regalo de …` gifts of §8. It reproduces no
   description text and no bulk listing; elsewhere it uses the placeholders `<singular>` /
   `<plural>`.
2. **The game code that consumes the tables.** Nothing here comes from disassembly. The one
   in-game datum is the id → text link of §6.3, confirmed on screen for seven ids; the rest of
   the geometry was not exercised in game.
3. **The meaning of the 32-byte record fields.** Their geometry is measured (§4) and their
   semantics are not (§14). A reader does not need them.
4. **The id → text mapping of the description tables.** Not established (§10, §14).
5. **Any other build, platform, or the base game.**

**Terminology of "verified".** A claim marked *(measured)* was produced by the walk described
in §15 over all 12,298 container entries and all nine name tables in full. A claim marked
**[inference]** is a reading of the measurements that the data does not prove.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Table** | One container entry holding a header, a per-id record area and a text pool. Identified by its index in `LI_C0_R.IDX` (`#4650` = the 4,651st entry), never by a name: the container has no names. |
| **Record** | One 32-byte entry of the per-id record area. There are exactly `count` of them (3,001). |
| **Slot** | One NUL-delimited string in the text pool, addressed by its **position** in the pool, counted from 0. An empty slot is a single `0x00` byte and still counts as a slot. |
| **Block** | The six consecutive slots that belong to one id: slots `6*(r-4)` … `6*(r-4)+5`, where `r` is the id. |
| **Group** | Three consecutive slots inside a block. Group A = slots +0, +1, +2; group B = slots +3, +4, +5. |
| **Pool** | The text region of a table: from the first byte of the first slot to the end of the entry. |
| **Id** | The catalogue id `r` (0 … 3,000 in this build): the key this document maps to text. It is **not** the row index of the item table — an item's id is `r − 3` (§6.3). |
| **`nameIndex`** | The `u16` at record offset **+34** of a row of the item table `#983`. It holds **`r − 3`**, not `r`: the catalogue id of an item is `nameIndex + 3` (§6.3). The name is a misnomer kept from the earlier notes. |
| **Singular** | The string at block offset +0 (`slot 6*(r-4)`): the name of one unit. |
| **Plural** | The string at block offset +2 (`slot 6*(r-4)+2`): the name for several units. In three of the nine languages it is byte-identical to the singular in almost every id (§7). |
| **Empty block** | All six slots of an id are empty. 732 ids have one (§8). |

---

## 3. Table inventory

Nineteen container entries carry `count = 3001`; eighteen of them are text tables and the
nineteenth, **#1172**, is a different table that happens to share the count (`version = 0`,
20-byte rows, no text). `count` alone therefore does not identify a text table *(measured)*.

### 3.1 Name tables

All nine are `flag = 1` (block-compressed) and decode to the byte sizes below. `pool` is the
byte offset of the first slot inside the decoded entry; `slots` is the number of NUL-delimited
slots from `pool` to the end of the entry.

| Entry | Language | Decoded bytes | `count` | `version` | Pool starts at | Slots | Non-empty slots |
|---|---|---|---|---|---|---|---|
| `#4645` | jp | 174,680 | 3,001 | 2 | **96,102** | 18,007 | 2,269 |
| `#4646` | en | 296,600 | 3,001 | 2 | **96,102** | 18,002 | 9,076 |
| `#4647` | fr | 299,680 | 3,001 | 2 | **96,102** | 18,005 | 9,076 |
| `#4648` | it | 301,944 | 3,001 | 2 | **96,102** | 18,007 | 9,076 |
| `#4649` | de | 389,288 | 3,001 | 2 | **96,102** | 18,000 | 13,614 |
| `#4650` | es | 298,584 | 3,001 | 2 | **96,102** | 18,003 | 9,076 |
| `#4651` | zh-TW | 254,384 | 3,001 | 2 | **96,102** | 18,001 | 9,076 |
| `#4652` | kr | 282,344 | 3,001 | 2 | **96,102** | 18,006 | 9,076 |
| `#4653` | zh-CN | 252,800 | 3,001 | 2 | **96,102** | 18,002 | 9,076 |

*(all measured)*

### 3.2 Description tables

| Entry | Language | Decoded bytes | `count` | `version` | Pool starts at | Slots | Non-empty | `<br>` in text |
|---|---|---|---|---|---|---|---|---|
| `#4636` | jp | 258,736 | 3,001 | 2 | 96,096 | 1,937 | 1,154 | 1,108 |
| `#4637` | en | 166,968 | 3,001 | 2 | 96,096 | 1,556 | 837 | 746 |
| `#4638` | fr | 181,408 | 3,001 | 2 | 96,097 | 1,648 | 909 | 903 |
| `#4639` | it | 172,160 | 3,001 | 2 | 96,096 | 1,584 | 850 | 816 |
| `#4640` | de | 179,416 | 3,001 | 2 | 96,096 | 1,635 | 895 | 877 |
| `#4641` | es | 174,656 | 3,001 | 2 | 96,096 | 1,597 | 865 | 844 |
| `#4642` | zh-TW | 152,248 | 3,001 | 2 | 96,096 | 1,384 | 741 | 689 |
| `#4643` | kr | 170,424 | 3,001 | 2 | 96,096 | 1,573 | 843 | 797 |
| `#4644` | zh-CN | 146,912 | 3,001 | 2 | 96,096 | 1,337 | 703 | 653 |

*(all measured)*

Note the contrast with §3.1: the description pool starts **immediately after the record area**
(96,096 = 64 + 32 × 3,001) with no six-byte separator, and the number of slots is a fraction of
the number of ids. See §10.

### 3.3 How the language of each table was assigned

The container carries no language tag, so the assignment is measured from the text of each
table. Five statistics are computed over every non-empty slot, and the classification uses only
features that are unique to one candidate language:

| Feature | What it detects |
|---|---|
| Kana code points U+3040–U+30FF | Japanese |
| Hangul syllables U+AC00–U+D7A3 | Korean |
| Count of 20 simplified-only vs 20 traditional-only characters | Chinese variant |
| Count of slots containing `ß ä ö ü` / `ñ ¿ ¡` / `ç œ è ê` / `ò ì ù à` | de / es / fr / it |
| Frequency of five function words per language (`the/and`…, `und/mit`…, `et/avec`…, `y/con`…, `di/per`…) | corroboration only |

Measured profiles of the nine name tables (slots containing the feature / total occurrences):

| Entry | kana | hangul | simplified | traditional | `ßäöü` | `ñ¿¡` | `çœèê` | `òìùà` | function-word leader | → assigned |
|---|---|---|---|---|---|---|---|---|---|---|
| `#4645` | 2,268 | 0 | 0 | 15 | 0 | 0 | 0 | 0 | — | **jp** |
| `#4646` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | en 1,670 | **en** |
| `#4647` | 0 | 0 | 0 | 0 | 0 | 0 | 570 | 448 | fr 4,394 | **fr** |
| `#4648` | 0 | 0 | 0 | 0 | 0 | 0 | 32 | 92 | it 5,228 | **it** |
| `#4649` | 0 | 0 | 0 | 0 | 3,317 | 0 | 0 | 0 | de 363 | **de** |
| `#4650` | 0 | 0 | 0 | 0 | 0 | 416 | 0 | 0 | es 5,826 | **es** |
| `#4651` | 0 | 0 | 0 | 2,040 | 0 | 0 | 0 | 0 | — | **zh-TW** |
| `#4652` | 0 | 9,064 | 0 | 0 | 0 | 0 | 0 | 0 | — | **kr** |
| `#4653` | 12 | 0 | 2,072 | 0 | 0 | 0 | 0 | 0 | — | **zh-CN** |

The result is a bijection over the nine languages and matches the order
`jp, en, fr, it, de, es, zh-TW, kr, zh-CN` exactly *(measured)*. The same classifier applied to
the description tables returns the same nine languages in the same order, `#4636 → jp` …
`#4644 → zh-CN` *(measured)*. Two assignments are also corroborated by earlier independent
work on this build, which quoted Spanish text out of `#4641` and `#4650`.

---

## 4. Record layout (32 bytes)

Every one of the eighteen text tables has the same skeleton:

```
offset   +0x00    +0x04    +0x08                   +0x40                        +0x17760
        ┌────────┬─────────┬─────────────────────────┬───────────────────────────────┐
        │ count  │ version │ 56 zero bytes           │ record 0 … record 3000        │
        │ u32    │ u32     │                         │ 3,001 × 32 B                  │
        └────────┴─────────┴─────────────────────────┴───────────────────────────────┘
          record k starts at 64 + 32·k ; the area ends at 64 + 32·3,001 = 96,096
```

| Field | Offset | Type | Measured content | What it guarantees | What it does not guarantee |
|---|---|---|---|---|---|
| `count` | `+0x00` | u32 LE | **3,001** in all 18 text tables | the number of 32-byte records that follow the header | that the entry is a text table (see `#1172`, §3) |
| `version` | `+0x04` | u32 LE | **2** in all 18 | a format revision marker | that a future build keeps it; `#1172` has 0 |
| reserved | `+0x08`…`+0x3F` | 56 B | **all zero** in all 18 tables | nothing | nothing |
| record area | `+0x40` … `+0x1775F` | 3,001 × 32 B | see below | that one record exists per id, in id order | any statement about its fields |
| six offsets | record `+0x00`…`+0x17` | 6 × int32 LE | non-negative; 88.8 % of them fall inside the decoded entry and 82.6 % inside the pool (`es`); the first one rises **+35.50 B per id** in `es`, **+65.72** in `de` and **−5.81** in `jp` (endpoint slope between the first and last named id; a least-squares fit over all 3,001 records gives +34.53 / +61.40 / −6.50, so the progression is not linear and the figure is only an envelope) | that they are 32-bit quantities with a per-language progression | **that they address the text.** Only 5.95 % land on a slot start (1,429 of 24,008 in `#4650`; 1.40 % in `#4645`, 4.44 % in `#4649`) *(measured)* |
| two words | record `+0x18`, `+0x1C` | 2 × u32 LE | both **0** in 731 records of every table checked; non-zero otherwise | nothing established | their meaning |
| text pool | `+0x17766` onward | bytes | see §5 | where the slots start | — |

**The six int32, measured in more detail** (no semantics claimed):

* They are not slot indices: of the values that fall inside the entry, none exceeds 202,563
  while the pool ends at 298,584, and the values are byte-scale; 2,699 of the 24,008 values of
  `#4650` are ≥ the entry length, so they are not plain offsets into this entry either.
* **Two different sets of 732 — do not confuse them.** In each of the nine tables, and for the same
  732 ids, 732 records form an arithmetic sequence with step **−3** (`p, p−3, p−6, p−9, p−12,
  p−15`). That set is **not** the set of ids with an empty block: it is the **731** records whose
  `+0x18`/`+0x1C` words are both zero (id 0 among them; every zero-word record follows −3) plus
  **id 2,989**, whose `+0x1C` is `0x000A0000`. Of the 732 ids with an empty block (ids 0–3 plus
  the 728 unnamed ids of §8) only **439** follow the progression — id 0 and **438** of the 728 —
  while the other **293** show one of **143** other step patterns, the most frequent being
  `(16, −3, 17, 16, −3)` in 14 of them. Conversely **293** of the −3 records are *named* ids.
  The two sets merely have equal size (732 each): one is 731 zero-word records plus id 2,989, the
  other is the 728 unnamed ids plus ids 0–3.
* For the remaining named ids the step pattern is irregular: in `#4650` id 4 the six values are
  96,150 / 96,167 / 96,164 / 96,182 / 96,199 / 96,196. The named ids whose steps are all −3 are
  exactly the **292** named zero-word records plus **id 2,989**.
* The pattern of "which records have zero words at +0x18/+0x1C" is **identical** in `#4650`,
  `#4645` and `#4649` (same 731 records, cross-tabulated the same way against the item table),
  even though the six int32 differ per language. So the two words are a per-id flag, not a
  per-language value.

Most frequent word pairs at `+0x18`/`+0x1C`, `#4650` (of 3,001 records):

| `+0x18` | `+0x1C` | Records |
|---|---|---|
| `0x00000000` | `0x00000000` | 731 |
| `0x00800000` | `0x00018000` | 795 |
| `0x10900010` | `0x00019000` | 362 |
| `0x00800000` | `0x000A8000` | 193 |
| `0x00900050` | `0x00018000` | 127 |
| `0x10900050` | `0x00019000` | 81 |

In `#4649` (de) the most frequent non-zero value of `+0x18` is `0x20202020` — four `0x20`
(space) bytes — in **691** of the 3,001 records. Counting the value alone stops there: the
counter of *values* is not the counter of *pairs*. Out of those 691 records, the most frequent
combined pair of the whole table is `(0x20202020, 0x00012020)`, in **559** of them; the other 132
carry the same `+0x18` with `+0x1C` = `0x000A2020` (119 records), `0x00082020` (10) or `0x00092020`
(3). That a word can spell ASCII spaces is why this document does not call the field "a flag word"
without qualification. What it means is listed as an open question in §14.

**Normative consequence.** A reader that follows this specification uses the record area only to
know *how many* ids the table covers (`count`) and where the pool begins. It must not use the
six int32 to locate text: the arithmetic in §6 is what locates text, and it is exact for every
id of every one of the nine tables.

---

## 5. Text pool

| Property | Names (`#4645`–`#4653`) | Descriptions (`#4636`–`#4644`) |
|---|---|---|
| First slot at | **+96,102** = 96,096 + 6 | +96,096 (eight tables) / +96,097 (`#4638`) |
| Bytes between record area and pool | 6 zero bytes, in all nine | 0 (`#4638`: 1) |
| Terminator | one `0x00` per slot | same |
| Length prefix | none | none |
| Padding between slots | none | none |
| Alignment | none — slots start at arbitrary byte offsets | none |
| Encoding | UTF-8, no BOM | UTF-8, no BOM |
| Invalid UTF-8 slots | **0** (9 tables, 9,076…13,614 slots each) | **3** — all of them slot 0 (offset 96,096) of `#4636`, `#4642` and `#4643`; 0 in the other six |
| String length (bytes) | 2–65 (min varies 2…6 by language; max varies 39…114) | 2–214 |
| Distinct strings | 2,114…5,365 per table | 606…958 per table |
| End of pool | end of the decoded entry | end of the decoded entry |
| Trailing zeros | 19…31 B (= 18…25 further empty slots after id 3000) | 5…11 B |

*(all measured; the per-table figures are in §3)*

**Empty strings.** An empty string is a slot of length zero, i.e. a single `0x00` byte. It is a
real slot: it occupies one byte of the pool and it advances the slot counter by one. This is why
an id that has no text at all still consumes six bytes of the pool (six consecutive `0x00`), and
it is the reason a reader must never "skip empty strings" when counting (§6).

**Reading algorithm.** Given the decoded entry `blob`:

```
pool = 96102                      # for #4645..#4653; measured, not assumed
slots = []
p = pool
while p < len(blob):
    q = blob.index(0, p)           # slots never run past the end of the entry
    slots.append(blob[p:q])        # length 0 is a valid, meaningful slot
    p = q + 1
```

The loop yields 18,000…18,007 slots for the name tables. 17,982 of them are the blocks of ids 4
… 3,000 (2,997 ids × 6); the remaining 18…25 are *extra empty slots* after the last block
(measured: all of them empty, in all nine tables). They carry no text and no id.

---

## 6. Slot rule

**The rule.** For a catalogue id `r` in **4 … 3,000**, its block starts at slot index

```
k = 6 * (r - 4)
```

and consists of the six slots `k, k+1, k+2, k+3, k+4, k+5`. Slot `k` is the singular, slot
`k+2` is the plural (§7). Ids **0 … 3 have no block**: `6*(r-4)` is negative for them, and their
records are all-zero-flagged (§4). Ids **above 3,000** do not exist: `count` is 3,001, the
record area holds ids 0…3,000 and the pool holds no block for 3,001.

**Why the index must be positional.** The pool is a flat array of NUL-delimited slots with no
directory of its own; the record area does not address it (§4). The only thing that assigns a
slot to an id is the arithmetic above. Two independent measurements support it:

1. **Per-language shape agreement.** Under this rule, each of the nine independently authored
   tables has exactly 2,269 ids whose slot `k` is non-empty, and the nine sets of ids are
   identical, element for element *(measured)*. A wrong offset cannot produce the same 2,269-id
   pattern in nine tables of different lengths (156,698 … 293,186 pool bytes).
2. **Placeholder pattern of the block.** Under this rule the non-empty slot pattern is a single
   constant per language (§6.1), whereas the pool itself is irregular. That means the block
   structure — not the text lengths — determines the layout, which is what an id-indexed table
   looks like.

### 6.1 The six slots, per language

Bit *j* of the mask is 1 when slot `k+j` is non-empty. The mask is **constant for all 2,269
named ids and zero for all 728 unnamed ids** in every table *(measured)*:

| Language | Mask | Block shape | Non-empty slots for a named id |
|---|---|---|---|
| jp (`#4645`) | `0x01` | `<singular>, '', '', '', '', ''` | 1 |
| en, fr, it, es, zh-TW, kr, zh-CN | `0x2D` | `<singular>, '', <plural>, <singular'>, '', <plural'>` | 4 |
| de (`#4649`) | `0x3F` | `<singular>, <singular>, <plural>, <singular'>, <singular>, <plural'>` | 6 |

Two consequences that surprise readers:

* **Japanese has no plural slot at all.** `#4645` fills only slot `k`; slots `k+1 … k+5` are
  empty for every one of the 2,269 named ids. Reading `slot k+2` in Japanese yields the empty
  string, not a plural.
* **German fills the middle slots.** `#4649` has 13,614 non-empty slots = 6 × 2,269, and slot
  `k+1` and `k+4` are byte-identical to the singular for all 2,269 ids *(measured: lengths and
  digests equal)*.

### 6.2 Why the naive "two strings per id" mapping is wrong

A reader can build a *dense* list — every non-empty slot, gaps skipped — and index it as
`dense[2*(r-4)]`. It never fails, and it is never accurate:

| Test | Dense rule `dense[2*(r-4)]` | Slot rule `slots[6*(r-4)]` |
|---|---|---|
| Ids it "resolves" in `#4650` | **2,997 of 2,997** — it never fails | 2,269 |
| Of the 728 ids whose block is entirely empty | gives a non-empty string to **728 of 728** | gives the empty string |
| Agreement with the slot rule over the 2,269 named ids | **1** id | — |
| Save items resolved (§9) | 74 / 74 | 74 / 74 |
| Of those, text identical | **0** of 74 | — |

*(all measured, `#4650` and the save of §9)*

The dense rule cannot fail because it has no test to fail. It drops the gaps, so a Latin block's
four non-empty strings collapse into four consecutive positions and the dense index advances by 2
per id while the real block advances by 6: `dense[2*(r-4)]` therefore reads from a block about
half the requested id **[inference]**. That it lands on *something* for every one of the 2,997
ids is not evidence of correctness — it lands on another id's string. On the first named id
(id 4) both rules agree; after that they diverge everywhere (agreement on 1 id in 2,269). Note
the last two rows: on the real save the dense rule *covers* exactly as many items as the correct
rule (74 of 74) and its strings agree with the correct ones on **none** of them. Coverage is not
an address test.

### 6.3 From an item row to `r`: the field holds `r − 3`

The item table `#983` is the only part of this build that says which catalogue id an obtainable
item uses, and it does not store the id itself. Row `i` of `#983` (header 64, stride 68) carries a
`u16` at `+34`; that value is **`r − 3`**:

```
r          = u16(#983 row i, +34) + 3
singular   = slots[6*(r-4)]
plural     = slots[6*(r-4) + 2]
item name  = singular(r)
```

Seven anchors, read on screen in the emulator from the inventory of save slot `G00`. The first
six items were already in the bag; the seventh was injected into an empty slot for the test.

| Item id (`#983` row) | `u16` at `+34` | `r = field + 3` | Slot `k = 6*(r−4)` | `k+2` | Text read on screen |
|---|---|---|---|---|---|
| 63 | 2,281 | **2,284** | 13,680 | 13,682 | `baya atania` |
| 14 | 2,486 | **2,489** | 14,910 | 14,912 | `haba` |
| 3,948 | 2,603 | **2,606** | 15,612 | 15,614 | `amuleto puro` |
| 3,913 | 2,568 | **2,571** | 15,402 | 15,404 | `lodo negro` |
| 3,926 | 2,581 | **2,584** | 15,480 | 15,482 | `restos` |
| 3,927 | 2,582 | **2,585** | 15,486 | 15,488 | `huevo suerte` |
| 1,324 | 2,278 | **2,281** | 13,662 | 13,664 | `mesa natural` (see below) |

The seventh row is the decisive one. A LayeredFS patch rewrote the text of slot 13,662 — 22 bytes
in `#4650` and 22 in `#4646`, nothing else in the container — and the game then labelled item
**1,324** with the patched text (`MESA DEL MOD` in `es`, `MOD TABLE!!` in `en`), while item 63 kept
reading its own name. Slot 13,662 is `6*(2281−4)`, and 2,281 is `2,278 + 3`. Under the field-only
rule the two would swap: item 1,324 would read slot 13,644 (all six slots empty) and item 63 would
read the patched slot 13,662. The screen showed the opposite, which is what makes this an anchor
and not an assumption.

**The test object is gone; the anchor is not.** What was reverted is the save, not the evidence:
`G00` was restored from `build/backups/CMNDAT-G00-20261103-2038.BIN` (md5
`998a8c8532817edda42622f07778a5b9`), so inventory slot 43 is empty again and item 1,324 is no
longer in the bag that §9 measures — the counts of §9 are the ones of that reverted save. The
container itself was never written: the patched text was a LayeredFS overlay, unmounted after the
test, and the six untouched anchors still read the names in the table above.

**Why the field alone produces false identifications.** Reading the field as `r` shifts every
item **three ids back**, so `slots[6*(field-4)]` reads the block of the *preceding* id:

* The preceding block is usually **not** empty. With the field used as `r`, 3,127 of the 4,600
  rows (68.0 %) point at a named id, so the reader returns a plausible string instead of failing.
  Item 63 reads `mesa natural` — the name of id 2,281 — instead of `baya atania`; item 3,948 reads
  `escudo habilidad` instead of `amuleto puro`. Off-by-three is silent, which is what makes it
  dangerous.
* No coverage test catches it. On the 74 items of the real save (§9) the field-only rule returns a
  string for **51**, and **50 of those 51 are another item's name**; the fifty-first agrees only
  because ids 1,936 and 1,939 happen to share the same text. It also *loses* ids that do have a
  name: item 14 reads slot 14,892 (empty) instead of `haba`, and 23 of the 74 items the correct
  rule resolves come out empty under the old link.
* The inverse error — adding 3 to a value that is already `r` — reads the *following* block and
  fails in the same silent way. The rule is positional on both sides: `r` addresses the block, and
  the item table stores `r − 3`.

---

## 7. Singular and plural

```
singular(r) = slots[6*(r-4)]        # slot offset +0 of the block
plural(r)   = slots[6*(r-4) + 2]    # slot offset +2 of the block
```

**Where `r` comes from, and the three anchors that pin it.** The offsets above take `r` as given;
the item that owns `r` is reached the other way round, through `#983`: **`r = u16(row+34) + 3`**
(§6.3). Three of the seven on-screen anchors, in singular/plural terms:

| Item id | `r` | Singular slot `6*(r−4)` | Plural slot `+2` | Text read on screen (singular) |
|---|---|---|---|---|
| 63 | 2,284 | 13,680 | 13,682 | `baya atania` |
| 3,926 | 2,584 | 15,480 | 15,482 | `restos` |
| 3,927 | 2,585 | 15,486 | 15,488 | `huevo suerte` |

Reading the `+34` field as `r` moves all three three ids back — to slots 13,662, 15,462 and
15,468 — and returns the names of the preceding items instead. The plural is not on screen in
that test (the inventory shows the singular), so the `+2` offset of this section still rests on
the morphological evidence below, not on the emulator.

**What is in the slot between them (offset +1, and its twin at +4).**

| Language | Slot +1 / +4 | Measured |
|---|---|---|
| jp | empty | 2,269 of 2,269 named ids |
| en, fr, it, es, zh-TW, kr, zh-CN | empty | 2,269 of 2,269 |
| de | non-empty, byte-identical to the singular | 2,269 of 2,269; lengths 3…56 B |

**Group A versus group B.** The block is *two* groups of three. Group B is not always a copy of
group A (measured, per language, over the 2,269 named ids; `A` = slot +0, `A'` = slot +3,
`P` = slot +2, `P'` = slot +5):

| Language | Both groups identical | `A ≠ A'` | `P ≠ P'` | Among `A ≠ A'`: `A'` is longer |
|---|---|---|---|---|
| jp | 0 | 2,269 | 0 | — (`A'` is empty: group B does not exist) |
| en | 1,464 | 805 | 805 | 805 |
| fr | 1,646 | 622 | 623 | 622 |
| it | 1,515 | 752 | 753 | 751 |
| de | 1,627 | 635 | 642 | 635 |
| es | 1,593 | 676 | 676 | 676 |
| zh-TW | 2,268 | 0 | 1 | — |
| kr | 2,269 | 0 | 0 | — |
| zh-CN | 2,268 | 1 | 0 | 0 |

**[inference]** Group B carries a *qualified* variant of the same name: where the two singulars
differ, the second is longer, it never fully contains the first and it never has the first as a
prefix (0 of 676 in `es`), but it shares a suffix of ≥ 3 bytes with it in 518 of 676 (`es`), 627
of 805 (`en`) and 635 of 635 (`de`) — the measured signature of a qualifier *prepended* to the
same name. What the qualifier means is not established (§14).

**Plural equals singular.** In three languages the plural is normally the same string as the
singular, and in the others the singular/plural relation is a morphological suffix — a check
that the offset +2 really is the plural:

| Language | plural == singular | common prefix ≥ 5 chars between singular and plural |
|---|---|---|
| en | 501 (22.1 %) | 2,246 of 2,269 |
| fr | 352 (15.5 %) | 1,878 |
| it | 982 (43.3 %) | 2,037 |
| de | 780 (34.4 %) | 2,238 |
| es | 336 (14.8 %) | 1,889 |
| zh-TW | 2,269 | 2,263 |
| kr | 2,269 | 2,257 |
| zh-CN | 2,268 | 2,262 |

*(all measured)*

**Valid range of `r`.** `4 ≤ r ≤ 3000`. Outside it:

| `r` | What happens |
|---|---|
| 0, 1, 2, 3 | `6*(r-4)` is negative; there is no block and the record is empty of text (§4). The item table does reference ids 1, 2 and 3 (§8). |
| 3,001 or more | past the table: `count` is 3,001 and the pool ends after id 3,000's block plus 18…25 empty slots |
| any value whose `k+5` exceeds the slot count | malformed input; a reader must reject it rather than wrap |

---

## 8. Coverage and holes

| Quantity | Value | How to recount |
|---|---|---|
| Ids in the catalogue | 3,001 (0 … 3,000) | `count` at `+0x00` |
| Ids with a block (`4 … 3000`) | 2,997 | — |
| **Ids with a name** | **2,269** | §6 loop, `slots[6*(r-4)] != b""` — identical in all 9 tables |
| **Ids without a name** | **728** | 2,997 − 2,269; all six slots empty in all 9 tables |
| Ids 0 … 3 | no block | `6*(r-4) < 0` |
| **Named ids that no item row references ("orphans")** | **21** | names minus `{nameIndex + 3}` of `#983`; 2,248 + 21 = 2,269 |
| Distinct non-zero `nameIndex` values in `#983` | 2,307 | `u16` at `64 + 68*i + 34`, `i` in 0…4,599 |
| … distinct `r = nameIndex + 3` | 2,307 | the `+3` is injective |
| … of which point to a named id | 2,248 | 2,248 + 21 = 2,269 |
| … of which point to an unnamed id | 59 | 2,248 + 59 = 2,307 |
| Item rows with `nameIndex = 0` | 925 | of 4,600; `r` would be 3, which has no block |
| Item rows whose `r` has a name | 3,585 (77.9 %) | — |
| Item rows whose `nameIndex` has a name — the field read as `r`, i.e. wrong by three | 3,127 (68.0 %) | the silent cohort of §6.3 |
| All-zero rows of the variation table `#41` | **2,133** | of 4,096 rows × 16 B; `u16` partId at `+4` is 0 and the row is all zero |
| Distinct partId values in `#41` | 1,553 | — |

*(all measured against the same dump; the item table is `count = 4600`, `version = 3`,
stride 68, header 64)*

Two clarifications that the earlier internal reports got slightly wrong:

* "728 ids without a name" counts ids **4 … 3,000** only. Including ids 0…3, there are **732**
  records whose six slots are all empty — but that is **not** the same set as the 732 records
  whose six int32 form the −3 progression of §4: the two sets share only **439** ids. Equal
  counts, different sets; neither can be derived from the other.
* An "orphan" is a *named id with no item row*: the item table never points at it, but the name
  table has its text. The **21** are, in id order `87, 95, 96, 97, 101, 102, 138, 139, 140, 144,
  145, 182, 325, 490, 669, 1165, 1193, 1418, 1522, 1820, 2034`: thirteen `regalo de …` gift
  objects — `Ditto`, `Articuno`, `Zapdos`, `Moltres`, `Mewtwo`, `Mew`, `Raikou`, `Entei`,
  `Suicune`, `Lugia`, `Ho-Oh`, `Kyogre`, `Volcanion` (ids 87…325) — plus eight world objects
  (ids 490, 669, 1,165, 1,193, 1,418, 1,522, 1,820, 2,034). The thirteen are **[inference]**:
  hand-out gifts that were never obtainable as items, which is why no `#983` row references
  them. The eight are **not** identified as unobtainable — the only thing measured about them is
  that no item row points at them. Of the 21, only **1** has an all-zero row in `#1172` (a
  different 3,001-row table with 20-byte stride, `version = 0`) — the other 20 have data there,
  the reverse of what the pre-revision set showed. What `#1172` is, and whether an all-zero row
  means "unused", was not measured here.

---

## 9. Resolution against a real save

The resolution chain for a saved item is:

```
item id  →  row of #983 (64 + 68·id, id < 4600)  →  u16 at row+34 = nameIndex
         →  r = nameIndex + 3                                          (§6.3)
         →  slots[6*(r-4)]  (singular)   and  slots[6*(r-4)+2]  (plural)
```

Measured on a save produced by the emulator (two inventory pages `G00` and `B00`, 130 slots of
5 bytes each — the record is defined in §9.1). An id of 0 means an empty slot, and a stack
occupies several slots, so *occupied slots* and *distinct ids* are different counts — the two are
listed separately here because conflating them was what made an earlier figure wrong:

| Quantity | Value |
|---|---|
| Slots occupied in `G00` | 53 |
| Distinct item ids in `G00` | 52 |
| Slots occupied in `B00` | 37 |
| Distinct item ids in `B00` | 37 |
| Shared between the two pages | 15 |
| **Distinct item ids in the save** | **74** |
| Resolved by the slot rule (`r = nameIndex + 3`) | **74** of 74 (100.0 %) |
| Not resolved | **0** |
| — `r` in 4…3,000 but the block is empty in all nine languages | **0** |
| — item id ≥ 4,600, so there is no row in `#983` at all | **0** |

### 9.1 The inventory record: `u32 & 0x1FFF` and a `u8` count

The inventory page is an array of 130 records of **5 bytes**, starting at `0x46ECEA` of the
decompressed payload (header `0x130`, declared length at `+0x10`). The offset belongs to save
version **`0x0200017D`** (game 2.0.1): it is per save version, not a universal constant.

| Offset | Type | Meaning |
|---|---|---|
| `+0` | `u32` | item id = **`raw & 0x1FFF`** (13 bits, ids 0…8,191); bits 13…31 carry **variant and placement** of the object |
| `+4` | `u8` | `count`, the stack size (0…255) |

The mask is part of the format, not a convenience. Reading the first two bytes as a plain `u16`
keeps the variant bits of some records in the id, and those bits are exactly what an editor
changes when it rotates or re-skins a piece of furniture: a reader without the mask turns a bed
into an id that this build's item table cannot have.

| Quantity | Value |
|---|---|
| Records whose id changes when the mask is applied | **4** |
| Largest `u32 & 0x1FFF` of the save | **3,998** |
| Largest unmasked `u16` of the save | **42,548** |
| Ids of the save with no row in `#983` | **0** |

The 53 occupied slots of `G00` hold 52 distinct ids: item 101 sits in two slots. `B00` has no
repeat, so its 37 slots are 37 ids.

**No id of this save lacks a row in `#983`.** The four ids an earlier revision listed as out of range: `10208, 34278, 42546, 42548`
— those were the unmasked `u16` of four `B00` records whose variant bits were set, and each one is
a row of `#983` once masked. §12.3 keeps the arithmetic of that mistake and the ids the four
records really hold. There is no item in the save whose `r`
points at an empty block either: after the `+3`, `nameIndex` max is 2,997 and `r` max is 3,000,
so every item of the save both resolves and resolves to its own text.

**Which save these figures belong to.** The rows above are one specific save, so they are pinned
by its digests rather than by a date: `G00/CMNDAT.BIN` md5 `998a8c8532817edda42622f07778a5b9`,
`B00/CMNDAT.BIN` md5 `efbb5b243ae98f20756dd3a31687d9b9` (payloads decompressed from header
`0x130`). The `G00` page measured here is the reverted one — slot 43 is empty. While the test object
of §6.3 (item 1,324) sat in that slot, the same measurement gave 53 distinct ids in `G00`, 75 in the
union and 71 resolving; those were the figures this section carried before the revert, and they
described a save that no longer exists on disk.

**How to reproduce the table, now that the live save moves.** The game rewrites `G00` while it is
being played (on 2026-11-04 it went from `998a8c85…` to `68aee5eb…` at 00:40:48 and to `c6bdc674…` at
00:52:28, each time with 40 distinct ids instead of 52 and 64 in the union instead of 74 — all of them
still resolving, because the mask does not depend on the state of the game). So the figures are
reproduced from a **frozen copy** of the pinned save, kept outside the repository under `build/`
because it is save data: `build/save-snapshot/` (or `build/t_e4f8d673/save-snapshot/`), holding
exactly the two digests above. `tools/spec/measure_save_items.py` measures that copy by default and
takes a slot directory as its argument to measure another save.

The verifier follows the same rule rather than failing on a moving file: when the save passed with
`--save` does not carry the pinned digests, it checks the figures of §9, §6.2 and §12.3 against the
frozen copy (`--snapshot DIR`, or the two `build/` paths) and, on top, re-checks the §9.1 invariants
— every id within 13 bits, the mask changing nothing where bits 13.. are zero, every distinct id
resolving — against the save it was given. A document compared against a *different* save without a
copy of the pinned one still fails, and it should: that is the check working, not a drift in the
specification.

**How to read the 74/74.**

* All 74 resolve, each one in all nine languages at once, with the same slot arithmetic, and the
  singular/plural pair is morphologically consistent (§7). The largest id of the save is **3,998**,
  well inside the 4,600 rows of `#983`; the ids above 4,600 that an earlier revision of this
  section reported were the artefact of dropping the 13-bit mask (§9.1), not items from a newer
  data set.
* Coverage alone does not certify the chain: with the `+34` field used directly as `r`, only
  **51** of the 74 resolve, and **50 of those 51 carry another item's name** (§6.3). The test that
  matters is not "did I get a string" but "did I get *this* id's text", and only the `+3` passes it
  — the seven anchors of §6.3 are that test, run on screen.

The dense rule of §6.2 — `dense[2*(r-4)]`, gaps skipped — returns a string for **74** of the 74
as well, the same count as the correct rule, and agrees with it on **0** of those 74: it hands
every item a neighbour's label. Coverage without an address test is not accuracy.

*The save-side offsets used here (`0x130` header, inventory at `0x46ECEA`, 5-byte records, 130
slots) are not derived from this specification; they come from earlier work on the same save
format and are used only to obtain an independent list of item ids. The record layout itself is
§9.1, and the offset is tied to save version `0x0200017D` (2.0.1). The rule under test is the
name-table one.*

---

## 10. Description tables (`#4636`–`#4644`)

What is **measured**:

* Same header as the name tables: `count = 3001`, `version = 2`, 56 zero bytes, and a
  3,001 × 32-byte record area ending at `+96,096` — byte for byte the same skeleton.
* The pool starts at `+96,096` in eight of the nine tables and at `+96,097` in `#4638`, i.e.
  **immediately after the record area**, not at 96,102. The name tables' six-byte separator does
  not exist here.
* The pool does **not** hold six slots per id: the tables have 1,337 … 1,937 slots and 703 …
  1,154 non-empty strings for 3,001 ids, with 606 … 958 distinct strings per table. Whatever
  the layout is, it is neither a per-id array nor a deduplicated string table.
* Strings are much longer than names: 2 … 214 bytes.
* Slots are UTF-8 and, unlike in the name tables, not all of them decode: exactly **three** slots
  fail UTF-8 decoding — slot 0 of `#4636` (19 B), `#4642` (2 B) and `#4643` (40 B) — so a reader
  must use a replacement policy here instead of strict mode.
* The markup `<br>` occurs 653 … 1,108 times per table, i.e. inside most non-empty strings: these
  are multi-line item descriptions, not labels.
* The six int32 of the records do not address this pool either: they land on a slot start in
  15 … 34 cases out of 24,008 (0.06 % … 0.14 %).

What remains **unmeasured**, and is therefore not asserted anywhere in this document:

1. The id → description mapping. Nothing measured so far assigns a slot to an id.
2. Whether the description tables share the six-slot anatomy at all.
3. How a shared description (a distinct count below the slot count) is referenced by several ids.
4. Whether the record fields of these tables have the same meaning as in the name tables.

A reader can extract the strings of a description table (§5 algorithm) but cannot yet say which
id owns which string.

---

## 11. Invariants

**A reader may assume** (measured over the whole build):

1. Entries `#4645`–`#4653` and `#4636`–`#4644` exist, decode with the container rules, and start
   with `count = 3001`, `version = 2`, then 56 zero bytes.
2. The record area is exactly `64 + 32·count` bytes; the name-table pool begins at
   `64 + 32·count + 6`; the description-table pool begins at `64 + 32·count`.
3. Slots are NUL-delimited UTF-8 with no length prefix, no alignment and no padding; an empty
   string is one `0x00` byte and counts as a slot.
4. In every name table, `slots[6*(r-4)]` is the singular of id `r` and `slots[6*(r-4)+2]` is its
   plural, for `r` in 4 … 3,000.
5. The set of ids with a singular is the same 2,269 ids in all nine name tables.
6. Within one language, the six-slot non-empty pattern is a constant for all named ids
   (`0x01` jp, `0x3F` de, `0x2D` the other seven).
7. Every non-empty slot is valid UTF-8 — true in all nine name tables (0 exceptions), false in the
   description tables, which have exactly three (§5, §10).
8. The item table `#983` stores **`r − 3`** at `+34` of each row, i.e. `r = nameIndex + 3` for
   every row with a non-zero `nameIndex`; no row yields an `r` above 3,000 (max `nameIndex` is
   2,997), and the 925 rows with `nameIndex = 0` yield `r = 3`, which has no block (§6.3, §8).

**A reader must not assume** (each of these is false somewhere in this build):

1. That the two groups of three are identical — false for 805 ids in `en`, 676 in `es`, 635 in
   `de`, 622 in `fr`, 752 in `it` (and meaningless in `jp`, where group B is empty) (§7).
2. That the plural differs from the singular — identical for 2,269 of 2,269 in `kr` and
   `zh-TW`, 2,268 in `zh-CN`.
3. That slots +1 and +4 are empty — they are filled in `de` for all named ids.
4. That every table has a plural — Japanese has none.
5. That the slot count is 18,003 — it ranges 18,000 … 18,007, and 18,003 is the `es` figure.
6. That the pool always starts at 96,102 — that is true for the nine name tables only; the
   description tables start at 96,096/96,097.
7. That the 32-byte records address the text — at most 5.95 % of their fields land on a slot
   start, and of the 732 empty blocks only **439** follow the −3 progression (**293** do not) (§4).
8. That `count = 3001` identifies a text table — `#1172` also has it.
9. That "resolves to a non-empty string" means correct — see §6.2 and §6.3: the dense rule and the
   field-without-`+3` rule both return strings for most items and both name the wrong item.
10. That the `u16` at `+34` of `#983` is the catalogue id — it is the id minus three, and using it
    directly returns the *preceding* item's name for 46 of the 47 items it "resolves" (§6.3).

---

## 12. Test vectors

Raw bytes of a slot are `decoded_entry[offset : offset + length]`; `sha256` is over exactly
those bytes, so a correct reader can be checked without looking at any game text. The empty
string's digest is `e3b0c442…b855`, the SHA-256 of zero bytes.

### 12.1 First and last named id, and an id with an empty block

`id 4` = first id with a name; `id 3000` = last; `id 131` = first id whose block is empty in all
nine languages. The **Slot** column is the *absolute* slot index in the pool, i.e. `6*(r-4)` for
the singular and `6*(r-4)+2` for the plural.

| Case | Id | Entry | Lang | Slot | Offset in entry | Length | `sha256(slot bytes)` |
|---|---|---|---|---|---|---|---|
| first named | 4 | `#4645` | jp | 0 (singular) | 96,102 | 30 | `652281bc8c1c21700ee0815e96219034d870e5f73cd9b85228118ecbb27281ed` |
| first named | 4 | `#4645` | jp | 2 (plural) | 96,134 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| first named | 4 | `#4646` | en | 0 | 96,102 | 18 | `132d0ebd4c51640ef3ad2a84b384e7af90125bf7d834c53b4d31a89a1dfa5570` |
| first named | 4 | `#4646` | en | 2 | 96,122 | 19 | `e00e34cd63f3e0795f931a0ad0ee0ae31aef63c200b35194cdc65e6562a95d06` |
| first named | 4 | `#4650` | es | 0 | 96,102 | 19 | `9ca4c5493c7f23cea6663ddeb154f27ae2388d04596d556a6d917780cf543765` |
| first named | 4 | `#4650` | es | 2 | 96,123 | 20 | `8347a1aaaebc312569c0d32ca5b5a02adb2b31326b3cd0db0060c3aab0091886` |
| first named | 4 | `#4653` | zh-CN | 0 | 96,102 | 21 | `18ac6f6b23ef0d8b6ed7fb0e6904343f1f6ce908dce463d956ada5fc0b26e991` |
| first named | 4 | `#4653` | zh-CN | 2 | 96,125 | 21 | `18ac6f6b23ef0d8b6ed7fb0e6904343f1f6ce908dce463d956ada5fc0b26e991` |
| last named | 3,000 | `#4645` | jp | 17,976 | 174,610 | 39 | `7316ddc73f39e959635c748ea8410a56e30cb3da0682e0e1263ed52fb61e5eac` |
| last named | 3,000 | `#4646` | en | 17,976 | 296,476 | 24 | `e4ad1b3bc83e979a9bd20606d33700f492229e5fe6d885f59406f8fa7f94f452` |
| last named | 3,000 | `#4646` | en | 17,978 | 296,502 | 25 | `848e0d272e5401f968a9bd6abd0dd281789427dddc7cf7b9ef221890e0d9503c` |
| last named | 3,000 | `#4650` | es | 17,976 | 298,447 | 27 | `cfbd5b41541564558c5986a82dcbcaa6dd7ced9bed72c08bb1e1c234777be532` |
| last named | 3,000 | `#4650` | es | 17,978 | 298,476 | 28 | `0b76906944ba9691df60297bef20d3b3bdc75435f909c7d72d545a9269a40047` |
| last named | 3,000 | `#4653` | zh-CN | 17,976 | 252,666 | 27 | `da08ce9ec85f10fc50b4ab4831394ba37687fad44df0f296b2fc5d182999b439` |
| empty block | 131 | `#4645` | jp | 762 | 100,437 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| empty block | 131 | `#4646` | en | 762 | 105,434 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| empty block | 131 | `#4650` | es | 762 | 105,916 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| empty block | 131 | `#4653` | zh-CN | 762 | 105,924 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

### 12.2 The German six-slot block (all six slots non-empty)

Id 4, `#4649` (de): the two middle slots hold the singular and the two groups are identical, so
four slots share one digest and two share another — a compact check of the mask `0x3F`.

| Slot | Offset | Length | `sha256(slot bytes)` |
|---|---|---|---|
| 0 | 96,102 | 20 | `294458c64bda2bd08105338b7bce14d1db6d86d16f998c2d5dc61930350e7125` |
| 1 | 96,123 | 20 | `294458c64bda2bd08105338b7bce14d1db6d86d16f998c2d5dc61930350e7125` |
| 2 | 96,144 | 21 | `eb501ad2b8d0e55762feceb7c2f6a67073a2c9275593284be3bae213be3c6e73` |
| 3 | 96,166 | 20 | `294458c64bda2bd08105338b7bce14d1db6d86d16f998c2d5dc61930350e7125` |
| 4 | 96,187 | 20 | `294458c64bda2bd08105338b7bce14d1db6d86d16f998c2d5dc61930350e7125` |
| 5 | 96,208 | 21 | `eb501ad2b8d0e55762feceb7c2f6a67073a2c9275593284be3bae213be3c6e73` |

### 12.3 The four records the unmasked `u16` put out of range

An earlier revision listed these four `B00` records as ids above 4,600 with no row in `#983`, and
computed where their row would start. The ids were wrong: the record's id is `raw & 0x1FFF`, and
the bits above it carry variant and placement of the object (§9.1). The table gives the unmasked
`u16` that the defective reader produced, the masked id, its `r`, and the text the masked id
actually resolves to in `es` and `en`:

| Page | Slot | Unmasked `u16` | `u32 & 0x1FFF` | `r` | Slot `6*(r-4)` | `es` | `en` |
|---|---|---|---|---|---|---|---|
| `B00` | 6 | 42,546 | **1,586** | 1,654 | 9,900 | `sofá chic` | `chic sofa` |
| `B00` | 24 | 10,208 | **2,016** | 1,434 | 8,580 | `alfombra redonda pequeña` | `small round rug` |
| `B00` | 122 | 42,548 | **1,588** | 1,656 | 9,912 | `cama de camarote` | `guest-room bed` |
| `B00` | 123 | 34,278 | **1,510** | 1,563 | 9,354 | `cama antigua` | `antique bed` |

All four names come out of the same `r = field + 3` chain as every other item of §9, and all four
are furniture — the class of object whose orientation and variant are worth storing in the high
bits. The four "impossible" values are above 8,191, the ceiling of the 13-bit mask, which is what
should have made the old reading suspect: no item of this build can have an id that large.

### 12.4 How to reproduce any vector

```
$ python tools/spec/measure_names.py <ROMFS> [--save <SAVE-SLOT-DIR>] [--json <OUT.json>]
```

`<ROMFS>` is the romfs directory of build 655360 and `<SAVE-SLOT-DIR>` the directory holding
`G00/CMNDAT.BIN` and `B00/CMNDAT.BIN`. Section `K` of the output prints exactly the rows of
§12.1 (the `id 131` rows appear there labelled "first unnamed id"); sections `A`–`J` print the
rest of this document's figures. The script never writes to either input.

A reader is correct on these vectors if it produces the same offset, length and digest for each
row, and reproduces the three slot masks of §11.1.

The document itself can be re-checked against the dump, row by row: the verifier below parses
this file, recomputes every row of the tables in §3.1, §3.2, §3.3, §4, §5, §6.2, §6.3, §7, §8,
§9, §9.1, §10 and §12, the −3 / empty-block statements of §4, §8, §11.7 and §14, the seven
on-screen anchors of §6.3 and §7 (including the text quoted for them), and the four masked ids of
§12.3 with their `es` and `en` names, and fails if a single figure has drifted. The save-dependent
rows of §9, §9.1, §6.2 and §12.3 are checked when a save slot is available (`--save`); without it
they are skipped with a note, never assumed.

```
$ python tools/spec/verify_spec_names.py <ROMFS> docs/SPEC-NAMES.md
save: <SAVE-SLOT-DIR>
checks: 473 ; failures: 0
```

It prints one summary line and a `FAIL` line per drifted figure (`failures: 0` means every parsed
row reproduces against the dump). Like the measurer, it opens the dump read-only and prints no
game text. It is the last line of defence: if a later edit to this document invents or transcribes
a number wrongly, this command says so.

---

## 13. Discrepancies with our earlier notes

The figures below circulated in `ESTADO.md`, `INFORME-NO-USADO.md` and the task brief for this
document. Where a measurement disagrees, this document uses the measurement.

| Earlier statement | Measured here | Comment |
|---|---|---|
| "6 slots per id, two **identical** groups of 3" | Groups identical for 1,593 of 2,269 ids in `es` (1,464 `en`, 1,646 `fr`, 1,515 `it`, 1,627 `de`, 2,268 `zh-TW`, 2,269 `kr`); they differ for the rest | The duplication holds often but is not an invariant. §7 |
| "singular / **empty** / plural" | Empty in eight of the nine languages; **filled** in `de` (2,269 of 2,269, identical to the singular); in `jp` the slot after the singular does not exist at all | §6.1, §7 |
| "18,003 slots" per name table | 18,000 … 18,007 depending on the table; 18,003 is `es` | §3.1 |
| "pool starts at 96,102" (stated of the text tables generally) | True for the nine name tables; the nine description tables start at 96,096 (and 96,097 for `#4638`) | §5, §10 |
| "2,269 ids with a name, identical in the 9 languages" | Confirmed | §8 |
| "728 ids without a name" | Confirmed for ids 4…3,000; **732** records have no text if ids 0…3 are counted | §8 |
| "301 orphans class B" *(pre-revision figure)* | **21**, not 301: named ids with no row in `#983`. The 301 were an artefact of dropping the `+3` | **Corregida en revisión 2** — §8 |
| "2,133 empty variations in `#41`" | Confirmed (2,133 of 4,096 rows) | §8 |
| "42/69 items resolve; 27 do not — 23 + **4 with `nameIndex` outside `#983`**" *(pre-revision figure)* | **74 of 74** resolve (52 + 37 − 15 = 74 on the save as reverted); no id lacks a row in `#983`; no `nameIndex` can be "outside" anything, its max is 2,997 | **Corregida en revisión 2** — §9, §12.3. A "71 of 75" figure also circulated: it was measured while a test object sat in slot 43 of `G00`, and that object is no longer in the save |
| "70 of 74 resolve; 4 with **no row** in `#983`" *(figure of 2026-11-03, before the mask)* | **Falso**: 74 of 74 resolve. The item id of a save record is `u32 & 0x1FFF`; the four ids (10,208 / 34,278 / 42,546 / 42,548) were the unmasked `u16` of four `B00` records whose variant and placement bits were set | **Corregida el 2026-11-03** — §9.1, §12.3 |
| "the old 2-strings-per-id mapping resolves 65/69 and is right by accident" *(pre-revision figure)* | It resolves **2,997 of 2,997** ids and agrees with the correct rule on **1** of 2,269; on the save it covers 74 of 74 and agrees on **0** | **Corregida en revisión 2** — coverage is not an address test, §6.2 |
| "`nameIndex` is the catalogue id (`r = nameIndex`)" — revision 1, §6/§8/§9 | `r = nameIndex + 3`. The seven on-screen anchors of §6.3 fix the offset; the field alone names the *preceding* item | **Corregida en revisión 2** — §6.3 |
| "282 of the 301 orphans have an all-zero row in `#1172`" | **1** of 21 does; 20 have data there | **Corregida en revisión 2** — §8 |
| "`nameIndex` maximum observed 2,997" | Confirmed (max of the 2,307 distinct values) | §8 |
| Item table `#983`: `count 4600`, `version 3`, stride 68, `nameIndex` u16 at +34 | Confirmed | §8 |

---

## 14. Open questions

1. **What the six int32 of each record address.** They grow 35.5 B per id, 82.6 % fall inside the
   pool, but only 5.95 % land on a slot start. The step pattern is not uniform either: the 731
   zero-word records step −3 throughout, 438 of the 728 unnamed ids do too, and the remaining
   named ids mix positive steps with −3 (id 4: `+17, −3, +18, +17, −3`), apart from id 2,989;
   the 728 empty blocks alone show 144 distinct patterns (§4). No hypothesis tested (slot offsets,
   block starts, deduplicated-stream offsets, lengths) reproduces the values.
2. **What the 8 bytes at record +0x18 … +0x1F are.** Zero in exactly 731 records of `#4645`,
   `#4650` and `#4649` (the same 731 records), and in `de` the most frequent value is four `0x20`
   bytes. A per-id flag of unknown meaning.
3. **What group B (slots +3 … +5) is for.** It is a longer, qualified variant of group A in the
   622–805 ids per language where the two differ.
4. **What the German middle slots hold.** They equal the singular for all 2,269 ids; whether the
   game reads them, and why only German fills them, is unmeasured.
5. **How far the game follows the positional rule.** The id → text link is now confirmed on
   screen for seven ids (§6.3), one of them an injected item whose slot was renamed on its own.
   The six int32, the two flag words and the purpose of group B are still read from data only;
   nothing in game exercised them.
6. **The description tables' id → text mapping**, and whether they share the six-slot anatomy.
   §10 lists what is measured and what is not.
7. **Whether ids 0 … 3 are reserved or simply unused.** They have records (with zero flags) and no
   block, and the item table does reference ids 1, 2 and 3.
8. **Whether the 18 … 25 empty slots after id 3,000 are padding or reserved for future ids.**
9. **Whether other builds keep this geometry.** One build was measured. `count` and `version`
   should be checked before trusting any constant here elsewhere.

---

## 15. How this was measured

**Reader.** A standalone reader (`tools/spec/measure_names.py`) was written from the published
container specification, with no code shared with the project's packer, and validated against
that document's own published digests before anything else was printed:

```
$ python tools/spec/measure_names.py <ROMFS>
== 0. container and reader self-check
  entries: 12298 ; BIN: 247317504 B
  payload bytes: 548327864
  sha256(record stream): 1bd1f1fee2bdb116238ea3cc3147f712c423e3b21428746bead580a2e6f41551
  sha256(concatenation): 08a98bd557df2b2bbb195782cfedf34a2f1792b8d8cbacbeeea1944752ff9f05
```

Both digests equal the values published in the container specification, so the decoded bytes this
document measures are the build's payloads, entry for entry, all 12,298 of them.

**Walk.** For each of the eighteen text tables the script decodes the entry, reads `count` and
`version`, parses the 3,001 × 32 record area, derives the pool start by skipping the zero bytes
after the record area, splits the pool into slots, and then evaluates every rule of §5–§8 for
every id. The classification of §3.3 and the statistics of §6–§7 are computed per table, not per
sample.

**What "measured" excludes.** The save-side offsets of §9 (`0x130`, `0x46ECEA`, 5-byte entries,
130 slots) come from earlier work on the save format; they were used only to obtain the list of
item ids to resolve. Everything said about the *rule* is measured against the container.

**Source untouched.** MD5 of both container files, before and after all measurements:

```
358a672d506ce2b0399149ede64a6760  LD_C0_R.BIN
7e056a097f28a62f002ad961a611edf8  LI_C0_R.IDX
```

Identical to the digests published in the container specification, and identical before and after
this document's measurements. The dump was never written to; the save was read only.

**No game text.** Every figure above is a count, an offset, a length or a digest. The only strings
this document quotes are the twenty short item labels of §6.3 and §8, and they are quoted because
they *are* the evidence for the id → text link: no description text, no bulk listing. The
reproduction script prints no string from the game, which is what makes it safe to ship next to
this document.

**Second opinion on the document itself.** `tools/spec/verify_spec_names.py` parses this file and
recomputes 473 of the figures it states, straight from the dump (`checks: 473 ; failures: 0` at
the time of writing, revision 2 plus the 2026-11-03 correction). It was written after the
document, and it is what makes the tables above cheaply auditable rather than merely plausible —
it catches the next transcription slip. It is also what caught this document's own 13-bit id
defect: the checks of §9.1 (every id inside `0x1FFF`, every id below `count`, the mask a no-op
where bits 13… are zero, and the mask changing exactly four records) and the four masked ids of
§12.3 with their `es`/`en` names fail on the pre-fix reader — 20 failed checks against the same
save — which is the property the earlier 449-check version lacked. When the save slot is present
it also checks §9 and the two save rows of §6.2, including the page digests, the occupied-slot
counts and the empty slot the section names.

**The save side of §9.** `tools/spec/measure_save_items.py` is the independent measurement behind
§9 and §9.1: it opens `G00/CMNDAT.BIN` and `B00/CMNDAT.BIN` read-only, decompresses the payload
from header `0x130`, walks the 130 five-byte records at `0x46ECEA` — reading the id as
`u32 & 0x1FFF` and the count as the byte at `+4`, and printing the unmasked `u16` wherever the mask
changes the value — and then resolves every distinct id through `#983` → `field + 3` → `#4650`. It
prints the per-page counts, the union, the mask diagnostic, the ES/EN/JP cross-check (`failures:
0`), and the figures of the rules the document rejects (field-as-`r`, dense rule), so every number
in §9 can be re-derived with one command instead of trusted. On the save of this document it
prints `resolved: 74 of 74` and `no row in #983: 0`.

```
$ python tools/spec/measure_save_items.py <SAVE-SLOT-DIR>
...
=== reading the item id (mask 0x1FFF) ===
  G00: unmasked u16 max 3994 ; masked id max 3994 ; all masked ids <= 0x1FFF: True
    records where the mask changes the id: 0 []
  B00: unmasked u16 max 42548 ; masked id max 3998 ; all masked ids <= 0x1FFF: True
    records where the mask changes the id: 4 [(6, 42546, 1586), (24, 10208, 2016),
                                              (122, 42548, 1588), (123, 34278, 1510)]
...
=== resolution through #983 -> field+3 ===
  resolved: 74 of 74
  no row in #983: 0 []
  empty block (es): 0 []
  incoherent in the 9: 0 []
...
failures: 0
```
