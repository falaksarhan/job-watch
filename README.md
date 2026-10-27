# job-watch

![tests](https://github.com/falaksarhan/job-watch/actions/workflows/tests.yml/badge.svg)

A weekly scan of public job boards that sends me only the postings I have not seen yet.

I wrote it in October 2026 for my own search for a remote AI operations role from Austria. Every Monday morning it reads about 60 company boards and five aggregator APIs, puts every posting through three filters, and sends the handful of new matches to my phone. Standard library Python, no account, no API key, no language model. The first digests were full of hybrid roles and off target titles, so the filters are strict on purpose.

## How it works

1. **Sources.** The Greenhouse, Ashby and Lever boards of the companies named in `profile.json`, plus the public APIs of Arbeitnow, Remotive, Remote OK, Jobicy and Himalayas.
2. **Three gates.** The title has to match the include patterns and none of the exclude patterns (engineer, product, marketing, junior, analyst and so on are out, and so are German language postings and titles pinned to one city). The location must not be pinned to other European countries. And the job description itself has to say remote: hybrid, days in the office, relocation and "must be based in the US" postings are dropped even when the board flags them as remote, because that flag turned out to be unreliable. Generic titles such as Head of Operations or Chief of Staff pass only when the text is about AI or automation work.
3. **Memory.** `seen.json` keeps the URL of every posting it has shown for 180 days, so a digest holds only new ones. The same role posted once per country collapses to one line.
4. **Delivery.** `run.sh` scans once a day, saves the digest, splits it into chat sized parts and hands each part to a notifier command. If the notifier fails (laptop asleep, app not open) it retries every hour until it gets through. My notifier is a small script that puts the text into my own WhatsApp chat; any command that takes a text file works.

## Example

The digest with `--all` on 27 October 2026, every current match instead of only the new ones:

```
Job watch 2026-10-27: 5 new match(es) (11 postings) out of 11 current

AI Deployment Manager, Scale | cursor | Remote
https://jobs.ashbyhq.com/cursor/0130118d-1cce-4eea-8325-2fc95ab6c584

AI Support Operations Specialist | jobgether | 4 countries incl. South Africa remote
https://jobs.lever.co/jobgether/1407f4be-62ff-43ae-805c-9a52c4d1c663

Founders Associate | jobgether | 4 countries incl. Austria remote
https://jobs.lever.co/jobgether/7bca61de-3050-4421-887c-0b57869943e5

Internal AI Enablement Lead | n8n | Remote Berlin Office Norway,Latvia,Netherlands,Hungary,Portugal,Poland,Serbia,Germany,Austria,Lithuania,Ireland,United Kingdom,Spain
https://jobs.ashbyhq.com/n8n/fea09cae-58f1-4f3e-b4a0-daba6e7e5002

Head of AI Native Operations | supabase | Remote, Global
https://jobs.ashbyhq.com/supabase/9c04bc60-78a1-4529-950d-4704ab475764
```

That run looked at about 9,800 postings. The title gate dropped 9,666, the location gate 91, the description gate 14 (7 hybrid or on site, 6 without a word about remote work, 1 restricted to another country), and 11 were kept. The output on stderr with `--dry` or `--all` shows these counts.

## Run

```bash
python3 scan.py --dry      # prints the digest, leaves seen.json alone
python3 scan.py --all      # every current match, ignores seen.json
python3 scan.py            # the weekly run: prints the digest and updates seen.json
python3 -m unittest        # 13 tests for the three gates and the digest
```

`--dry` and `--all` also print how many postings each gate dropped, on stderr.

## Schedule it

On a Mac, copy `launchd/com.example.jobwatch.plist` to `~/Library/LaunchAgents/`, replace the two paths in it and run `launchctl load` on it. It starts `run.sh` every Monday at 08:00 and then once an hour until 22:00; only the first run of the day scans, the others retry a notification that is still owed. With cron: `0 8-22 * * 1 /path/to/job-watch/run.sh`.

`run.sh` reads three settings from the environment: `JOB_WATCH_OUT` (folder for the saved digests), `NOTIFY_CMD` (the command that delivers a text file and exits 0 when it did) and `PART_SIZE` (roles per message, 12 by default).

## Make it yours

Everything personal is in `profile.json`: the board slugs, the aggregator queries, the title patterns and the words that name your home country. The location rules in `scan.py` are written for someone in Austria who can work anywhere in Europe; the `EU_OK`, `NOT_EU` and `EU_COUNTRIES` patterns near the top are the ones to change for another base.

## Files

```
scan.py          the scanner: sources, the three gates, the digest, the seen list
profile.json     boards, queries and title patterns
run.sh           daily run, saved digests, notifier with hourly retry
launchd/         example launchd job for a Mac
test_scan.py     13 tests, python3 -m unittest
```

MIT, Falak Sarhan Saade.
