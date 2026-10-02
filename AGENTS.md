# AGENTS.md: central-core-mqtt-shared

## Central Core in one paragraph

Home monitoring for people living with dementia: a few door and motion sensors, no cameras or microphones, and a plain-English morning update for the family. Pre-launch: today it watches the owner's parents' home (`rookery-001`) and the owner's flat (`elyob-main-001`), but **build it as a future multi-customer health-data product**. Scope every query to a home, rate-limit anything that sends messages, and never cut a security corner because "it's only one family".

The five repos sit side by side in a `cc-all` folder: `central-core-vault` (owns all data and design), `central-core-client` (family portal, talks only to the vault API), `central-core-hub-addon-releases` (Home Assistant add-on in each home, talks to the vault over MQTT), `central-core-mqtt-shared` (the MQTT protocol), `central-core.com` (public website). `cc-all/AGENTS.md` has the whole-system view.

## Everywhere

- Small commits on a `claude/<topic>` branch, a PR, green CI, merge, then deploy. Check the live result and logs before calling it done.
- Never commit `.env*`, keys or certs; never print secret values. GitGuardian flags made-up test passwords, so check before dismissing.
- Tests use `monkeypatch.setattr`, never `module.attr = fake` (leaked fakes broke unrelated tests in the full run).
- Write anything families read in plain English.
- **Never give medical advice, anywhere**: portal, morning updates, care reports, AI prompts, emails, the website and marketing. Describe only what the sensors showed and how it compares with that home's usual pattern. Never name, suggest or guess at an illness, infection or condition; never say something is a sign or symptom; never mention doctors, medication or treatment. This is an owner rule, and it also keeps Central Core outside medical-device regulation (MHRA). The most we ever suggest is that the family checks in.

## This repo

The MQTT protocol shared by the vault and the hub add-on: topic builders, topic constants and payload definitions. A change here is a protocol change for every hub in the field.

## Commands

- `make install` once, then `make test`.

## Rules

- Keep changes backward compatible: hubs update on their own schedule, so the vault must keep understanding older hubs.
- Release by tagging (`vX.Y.Z`). The vault pins a tag in `requirements.txt`; the add-on pins a commit in `requirements.txt` and `central-core-hub/requirements.txt`. After a release, update the pins in both consumers deliberately.
- `README_AI.md` is older guidance; this file takes precedence where they differ.
