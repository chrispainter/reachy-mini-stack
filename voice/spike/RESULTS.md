# Voice spike results

## Hermes quick lookups

Change: appended a "Household data" section to `household/hermes/SOUL.md` mapping the list/notes files in /opt/data, telling Hermes to go straight to the file instead of searching. Benchmark: `household/tools/hermes_bench.py`, run on the Pi (2026-10-05).

Before:

| Request | Wall s | Model calls | Model s | Answer |
|---|---:|---:|---:|---|
| What's on the grocery list? | 18.9 | 7 | 16.6 | The grocery list has milk and eggs. |
| Add bread to the grocery list. | 14.6 | 6 | 12.9 | Done — I added bread to the grocery list. |
| What's on the grocery list? | 16.3 | 7 | 15.5 | The grocery list has milk, eggs, and bread. |
| Remove bread from the grocery list. | 31.4 | 11 | 28.9 | Done, I removed bread from the grocery list. |

After:

| Request | Wall s | Model calls | Model s | Answer |
|---|---:|---:|---:|---|
| What's on the grocery list? | 7.2 | 2 | 4.9 | Milk and eggs. |
| Add bread to the grocery list. | 9.1 | 3 | 8.7 | Done — I added bread to the grocery list. |
| What's on the grocery list? | 7.4 | 3 | 7.1 | The grocery list has milk, eggs, and bread. |
| Remove bread from the grocery list. | 10.0 | 4 | 9.5 | Done — I removed bread from the grocery list. |
