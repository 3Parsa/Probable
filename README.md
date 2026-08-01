# probable

probable generates password candidate lists for a specific, named target and ranks them by how likely a real person is to actually use them.

Most tools in this space pick one side of a tradeoff. CUPP and similar permutation tools take a target's known facts (name, birthday, pet) and mechanically cross them together, but the output is an unordered pile: every permutation of every fact, with no sense of which ones a real person would plausibly pick. PassGAN and other statistical/ML approaches go the other way. They learn what passwords look like from a huge breach corpus and generate very plausible-looking strings, but they know nothing about the specific person you're testing. They generate what's common, not what's theirs.

probable does both. It takes the same kind of operator-supplied facts CUPP takes (names, dates, pets, teams, places), expands and combines them the way a person actually would (case toggles, leet substitutions, year suffixes, separator joins), then ranks the entire output by real password structure frequency pulled from a 14.3 million password breach corpus (RockYou), with an additional bonus for candidates that are actually built from the target's own facts rather than generic filler. The result is a list where the most crackable-looking candidates come first, not buried at position 4,000 of an alphabetized dump.

It also ships a benchmark harness that runs the list through hashcat against a real (retired) password hash and reports exactly where in the list the real password landed. That's the whole pitch. Not "here are some guesses," but "here is a ranked list, and here's proof the ranking puts the real answer near the top."

## Authorized use only

This operates only on targets you are authorized to test: your own accounts, consenting volunteers who've agreed to be a test subject, or systems you have in-scope permission to assess. Every input is operator-supplied by hand. There is no scraping, no social media collection, and no ingestion of leaked credential dumps as target input. You tell probable what you already know about the target; it doesn't go find out for you.

## Install

```
pip install -e .
```

This installs the `probable` console script along with its dependencies (Typer, PyYAML, FastAPI, Uvicorn). Python 3.10+.

## Generating a wordlist

`probable generate` takes a YAML file describing the target and writes a ranked candidate list.

```
probable generate profile.yaml --size medium -o candidates.txt
```

Options:

- `--size {small,medium,large}` (default `medium`) sets the output tier. This controls how many ranked candidates come back, not how deep the generation goes: `small` is the top 50, `medium` the top 500, `large` is every ranked candidate with no cutoff.
- `-o` / `--output PATH` writes the list to a file, one candidate per line. Omit this and it prints to stdout instead.
- `--stdout` also prints to stdout even when `-o` is set.

The input file:

```yaml
target: Michael Reed     # optional, treated as a name token

names:
  - Michael
  - Reed

dates:
  - 1995-03-15           # YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, or bare YYYY

pets:
  - Buddy

teams:
  - Liverpool

places:
  - London

partner: Emily           # a single string, or a list of strings

custom:
  - go-eagles
```

Every field is optional. `names`, `dates`, `pets`, `teams`, `places`, and `custom` each accept a YAML list; `partner` accepts either a bare string or a list. Team names get looked up against a database of real club data (see below). An unrecognized team name still works, it just falls back to being treated as a plain word.

## Checking a wordlist against a real hash

`probable eval` hashes each line of a candidate file and tells you whether, and where, it matches a target hash.

```
probable eval --wordlist candidates.txt --hash <hex digest> --algo sha256
```

- `--wordlist PATH` is the candidate file, one per line.
- `--hash HEX` is the target hash.
- `--algo {sha256,sha1,md5}` (default `sha256`) only applies to the plain hashlib path below.

This prints `cracked at position N of TOTAL` on a match, or `not found in TOTAL candidates` otherwise. By default it hashes each candidate directly with `hashlib`, no external dependencies, which is fine for a quick sanity check against a single hash.

For a real attack, pass `--hashcat --mode N` to route through an actual hashcat install instead:

```
probable eval --wordlist candidates.txt --hash <hex digest> --hashcat --mode 1400
```

`--mode` is hashcat's numeric hash-mode identifier (`0` for MD5, `100` for SHA1, `1400` for SHA256, and so on) and is required whenever `--hashcat` is set. If hashcat isn't on your machine, this fails with an actionable error message telling you so, rather than a raw traceback. `--hashcat-bin PATH` points at a hashcat executable that isn't on `PATH`.

For the actual benchmark this tool exists to support, crack rate and crack *position* across many target hashes at once, call `wordgen.eval.harness.evaluate()` directly rather than the single-hash CLI path. That's what the `--hashcat` path is built on top of.

## Web interface

```
probable web --host 127.0.0.1 --port 8000
```

- `--host` (default `127.0.0.1`) and `--port` (default `8000`).
- `--reload` auto-reloads on code change, for development.

This is FastAPI and Uvicorn serving the exact same `core.engine.generate()` the CLI calls, so there's no separate generation logic to keep in sync. Open the printed URL and you get a form with one text field per token type (names, dates, pets, teams, places, partner, custom, each comma- or newline-separated) and a size dropdown. Generate shows the top 50 ranked candidates plus the total count. Download streams the entire ranked list as `candidates.txt`.

## How the ranking works

Every candidate string gets scored across five categories, each backed by real structural frequencies extracted from the RockYou breach corpus (14.3 million passwords, weighted by their count field, not just unique-line presence):

- **Case pattern.** Lowercase, uppercase, capitalized-first, or mixed. `lowercase_only` alone accounts for roughly 93% of real passwords, which is why `michael1` legitimately outranks `Michael1995` on this axis alone.
- **Suffix.** What the candidate ends with: a four-digit year, `123`, a single trailing digit, `!`, `?`, or one of the punctuation characters (`_`, `.`, `-`, `#`, `$`, `@`, plus the lower-frequency `&`, `*`, `+`, `%`).
- **Leet substitutions.** `4` for `a`, `3` for `e`, `1` for `i`, `0` for `o`, `5`/`$` for `s`, `@` for `a`. `1_for_i` is the most common at about 2.8% of the corpus, `4_for_a` about 1.3%; `@`/`$` substitutions are real but rare, well under a tenth of a percent each.
- **Separators.** A punctuation character joining two parts together (`michael_1995` vs `michael.1995` vs `michael1995`). No separator at all is by far the common case; where one is used, underscore beats dot beats hyphen/hash/at-sign/dollar, in that order, in the real data.
- **Plausibility.** A character-bigram language model, built from a dictionary word list and a first-names list rather than RockYou (passwords aren't a representative sample of natural-language letter sequences), scoring how much a word looks like a real word versus keyboard noise. This is what makes `michael1995` outrank `qxzvb1995` even though both have an identical case pattern and suffix.

Each category is log-weighted and min-max normalized within its own range before summing, so no single category's scale (or internal skew) can drown out the other four.

On top of that frequency score, candidates built from the target's actual combined facts (a name crossed with their real birth year, a pet name crossed with their team) get an additive personalization bonus. It's larger for name+date combinations than for name+team ones, since a birth year in a password is a far more common real-world pattern than working in a teammate's name. Without this, pure population-frequency scoring buries the candidates that are actually personalized to the target under generic single-token filler that just happens to be statistically common across everyone. The reverse case gets handled too: a bare word supplied only as incidental personal context (a place, a partner's name, a pet's name, a custom fact, used standalone rather than combined with anything else) gets a small penalty against the same logic in reverse. `london1` alone tells you nothing more about this specific target than any other common word with a digit on the end, so it shouldn't rank ahead of `Michael1995`.

## Team database

`teams.json` covers 314 football clubs across every major league, built from Wikipedia's current-season club rosters and each club's own infobox (founding year and nickname) rather than a hand-maintained list. Typing a team name expands it into its nickname, founding year, and (for a handful of hand-curated clubs) notable player names. These become combo bases the same way a date or pet name would, so `Liverpool` plus a name token can produce something like `Michael1892` from the club's founding year, not just `MichaelLiverpool`.

## Scope and limits

The corpus behind every weight in this tool (RockYou, plus the dictionary and first-names data behind the plausibility model) is English-leaning. Names, words, and patterns from other languages will still generate and still rank, just without the same depth of real frequency data backing the score. This generates and ranks single words, not multi-word passphrases; if your target uses a passphrase-style scheme, this tool isn't built for that shape of guess.

## License

MIT. See `LICENSE`.