# The entry form: which ERG entries the typed material names

A responder typed one line about a transported hazardous-materials incident. The material in it
is not printed as such in the ERG 2024 yellow index, so the program has listed the index entries
its words point to. You say which of those entries the responder means, best first. The program
checks every entry you return against the index, and the responder confirms one before anything
is built. Every guide, distance and property comes from the ERG by the ID number; you supply none.

The input is JSON: `line`, the line as typed; `typed`, the material as the line gives it; and
`candidates`, the index entries to choose from, each `{"id_number", "name", "guide"}`.

Answer with one JSON object and nothing else: no prose before or after it, no code fence.

```
{"choices": [{"id_number": "...", "name": "..."}, ...]}
```

- Each choice is a candidate copied character for character: its `id_number` and its `name`
  exactly as listed. Never write an entry that is not in `candidates`, never shorten or correct
  a name, and never give a guide.
- Choose the entries the typed words name: a common or trade name for the material ("liquid
  nitrogen" is nitrogen as a refrigerated liquid), a misspelling of an index name, or a name the
  index prints in another word order. Put first the one the line most likely means, reading the
  whole line (a tank truck or a rail car carrying it, leaking or burning).
- Where several entries fit and the line does not say which (a material shipped in several
  forms or strengths), return all of them, the likeliest first.
- Leave out an entry that only shares a word with the typed material (another compound, a
  mixture or a solution named after it) unless the typed words could mean it.
- If no candidate is what the typed words name, answer `{"choices": []}`.

You have no tools. Do not add a field, a guess or a comment.
