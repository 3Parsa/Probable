# probable - WIP

Generate ranked, targeted password candidate lists from known facts about a
target, and check them against a captured hash.

## Install

```
pip install -e .
```

## `probable generate`

Reads a YAML input file describing the target and writes a ranked candidate
wordlist.

```
probable generate profile.yaml --size medium -o candidates.txt
```

- `--size {small,medium,large}` (default `medium`) — output tier; controls
  how many ranked candidates come back, not generation depth.
- `-o/--output PATH` — write candidates to a file (one per line). Omit to
  print to stdout.
- `--stdout` — also print to stdout even when `-o` is set.

### Input schema

```yaml
target: Ahmet Yilmaz     # optional; treated as a name token

names:
  - Ahmet
  - Ahmet1998

dates:
  - 1998-06-12           # YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, or bare YYYY

pets:
  - Boncuk

teams:
  - Galatasaray

places:
  - Istanbul

partner: Ayse             # string or list of strings

custom:
  - go-eagles
```

Every field is optional. List fields (`names`, `dates`, `pets`, `teams`,
`places`, `custom`) accept a YAML list; `partner` accepts either a single
string or a list.

## `probable eval`

Hashes each line of a candidate wordlist and reports whether/where it
matches a target hash.

```
probable eval --wordlist candidates.txt --hash <hex digest> --algo sha256
```

- `--wordlist PATH` — candidate file, one candidate per line.
- `--hash HEX` — target hash to search for.
- `--algo {sha256,sha1,md5}` (default `sha256`).

Prints `cracked at position N of TOTAL` on a match, or
`not found in TOTAL candidates` otherwise.
