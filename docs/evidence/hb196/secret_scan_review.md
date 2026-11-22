# HB-196 Part C item 11: the secret scan's hits, each read

The scan (`tools/secret_scan.py`, `secret_scan.txt`) ran `python -m squiddy.secret_scan` over the 22,359 tracked files
and, apart, over the 28 files of `a session handoff (held privately)`. `a session handoff (held privately)`: no hit. The tree: three hits, none a credential of this
project. Each was read with its matched value masked; no value is written here.

| Hit | What it is | Disposition |
|---|---|---|
| `the HB-170 evidence (held privately):3` `aws_access_key_id` | The origin URL the operator's browser recorded for an inbox file (HSDL's `730014.pdf`): a pre-signed S3 download URL of `chds-hsdl-prod`, whose `X-Amz-Credential` is HSDL's access key id; `X-Amz-Date` 20261112T161135Z, `X-Amz-Expires` 3600, so it expired on 2026-11-12 at 17:11Z. A third party's temporary signature; it grants nothing now. | Issue `3b997b40`: strip the query string before the repository is published, or keep it; HB-170's record is not edited here. |
| `the HB-170 evidence (held privately):3` `aws_access_key_id` | The same URL. | The same Issue. |
| `fixtures/evidence/scichem_runs/516c5438562c0b90c8400096d52c682742cf754de3c565f89a27c5128231d5f2.json:13548` `google_api_key` | Character 584,200 of a 1,476,283-character line: base64 text of the stored frame mesh (gzip). The 39 characters happen to fit the key's shape (`AIza` and 35 more); base64 on either side. | A chance match, not a key. Nothing to do. |
