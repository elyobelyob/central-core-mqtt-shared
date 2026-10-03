# AGENTS.md: central-core-mqtt-shared

## What we believe

Dementia care should be care. These principles come before any feature, design or price; check every change against them.

1. **Care first.** Every feature has to help a family look after someone better. If it only helps us, it doesn't ship.
2. **Dignity.** No cameras, no microphones, nothing that watches. Sensors notice the rhythm of the day, not the person.
3. **The family stays in control.** They choose who sees what, how alerts work and when to stop. Their data is theirs.
4. **Plain and honest.** We say what the sensors showed, never more. No medical claims, no scare tactics.
5. **Affordable.** The monthly fee stays low, and you pay only for extras you use.
6. **Open.** The code is public, so anyone can check it, run it or improve it.

## Central Core in one paragraph

Home monitoring for people living with dementia: a few door and motion sensors, no cameras or microphones, and a plain-English morning update for the family. It is pre-launch, but **build it as a multi-customer health-data product**. Scope every query to a home, rate-limit anything that sends messages, and never cut a security corner because "it's only one family".

The five repos sit side by side in a `cc-all` folder: `central-core-vault` (owns all data and design), `central-core-client` (family portal, talks only to the vault API), `central-core-hub-addon-releases` (Home Assistant add-on in each home, talks to the vault over MQTT), `central-core-mqtt-shared` (the MQTT protocol), `central-core.com` (public website). `cc-all/AGENTS.md` has the whole-system view.

## Everywhere

- Small commits on a `claude/<topic>` branch, a PR, green CI, merge, then deploy. Check the live result and logs before calling it done.
- Never commit `.env*`, keys or certs; never print secret values. GitGuardian flags made-up test passwords, so check before dismissing.
- Tests use `monkeypatch.setattr`, never `module.attr = fake` (leaked fakes broke unrelated tests in the full run).
- Write anything families read in plain English.
- **Never give medical advice, anywhere**: portal, morning updates, care reports, AI prompts, emails, the website and marketing. Describe only what the sensors showed and how it compares with that home's usual pattern. Never name, suggest or guess at an illness, infection or condition; never say something is a sign or symptom; never mention doctors, medication or treatment. This is an owner rule, and it also keeps Central Core outside medical-device regulation (MHRA). The most we ever suggest is that the family checks in.

## Checks: once, at the right level

- **While building:** run focused tests for what you touched (in the vault, plus `tests/test_security_hardening.py`).
- **Before the PR:** run the full suite once, locally, on the final commit. Vault: `make test` (parallel, one database per worker, a few minutes). Other repos: their whole suite; it is quick.
- **GitHub:** vault PRs run only the quick safety subset (`make test-quick`: security, no medical advice, the message lock, logins, migrations, Herbert, night watch); the full vault suite runs nightly on `main` and on "Run workflow". The client, add-on and protocol repos run their whole suite on each PR; the website has no GitHub CI (run its tests before deploying). A failed nightly run is fixed before new work.
- **Don't repeat:** never re-run a full suite that already passed on the same commit.
- **Review depth scales with risk:** Herbert Protocol, night-door alerts, money and billing, security, logins and roles, database migrations, and anything that sends messages get a full review by several reviewers. Ordinary features get one reviewer. Copy, styling and docs get none.

## This repo

The MQTT protocol shared by the vault and the hub add-on: topic builders, topic constants and payload definitions. A change here is a protocol change for every hub in the field.

## Commands

- `make install` once, then `make test`.

## Rules

- Keep changes backward compatible: hubs update on their own schedule, so the vault must keep understanding older hubs.
- Release by tagging (`vX.Y.Z`). The vault pins a tag in `requirements.txt`; the add-on pins a commit in `requirements.txt` and `central-core-hub/requirements.txt`. After a release, update the pins in both consumers deliberately.
- `README_AI.md` is older guidance; this file takes precedence where they differ.
