# The load read: is this sentence about the sentence before it?

You read one pair of sentences from a hazardous-materials incident brief that a program has
already assembled. A responder reads the brief under load, so a sentence that only restates
or comments on the sentence before it adds reading and no information.

The input is JSON: `before`, a sentence, and `sentence`, the sentence that follows it in the
same paragraph or list item.

Decide one thing: is `sentence` about `before` (it restates it, explains what it just said,
or comments on it as a sentence: "This line ...", "That is, ...", "In other words, ...")
rather than adding a fact of its own?

- If `sentence` carries any fact, number, receipt, place, time, instruction or condition that
  `before` does not, it is **not** about `before`: answer `false`.
- Only when removing `sentence` would leave the reader with everything it said, answer
  `true`.

Answer with one JSON object and nothing else: no prose before or after it, no code fence.

```
{"about_previous": false, "reason": "one short sentence saying why"}
```

You have no tools. Do not add, change or judge anything else in the brief.
