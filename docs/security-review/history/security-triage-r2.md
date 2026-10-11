# Independent review triage, round 2

## Intent

Repair all Pete findings in the supplied reports while retaining functional reads and externally approved writes. Every real mutation requires trusted identity, current controller scope, an exact original request grant, and durable sanitized intent before backend I/O. Deployment, packaging and public configuration must agree with those controls.

## Reviewers

- gpt-6-sol reported two findings.
- gpt-6-luna reported one finding.
- gpt-5.6-terra reported one finding.

All reviewed the same frozen source at `0813ba8`. All reports were read in full by the parent. The interrupted first round supplied no verdict and is excluded.

## Act on

| Finding | Model | Parent judgment |
| --- | --- | --- |
| Consumed matching grant shadows a fresh approval | gpt-6-sol | Valid correctness failure. Sorted filenames select a used ID before the database rejects it. Select and consume an eligible unused grant in one transaction. Preserve replay refusal and expiry checks. |
| Cancellation during completion audit leaves the authority healthy | gpt-6-luna | Valid fail-closed defect. The await sits outside the body exception guard. Cover successful and failed completion, disable writes synchronously on interrupted persistence, and avoid awaiting the blocked sink again. |
| Assembled DXT lacks an artifact scan | gpt-6-sol | Valid publication coverage gap. Scan the built directory before archiving and attaching it, using the pinned existing scanner. |
| Runtime schema describes read-only as default False | gpt-5.6-terra | Valid contradictory public metadata. State default True and explicit writable opt-in. |

## Consider

None.

## Noted

- All models identify source and synthetic verification limits. Storage power-loss behavior, actual firmware, desktop installation and container mounts remain unverified.
- The first-round dispatch failures are operational recovery context. Only Terra has an explicit terminal provider failure in the selected transcript. Missing native reports and recovered agent inventories do not establish separate raw terminal errors for each native reviewer.

## Dismissed

None.

## Agreement map

The actionable findings are independent discoveries by individual models. None explicitly contradicts another. Each follows a concrete execution path or artifact input. The parent accepted them on that evidence rather than on a vote.

## Attention follow-up

Preserve the frozen raw suite output beside the audit trail. Record the post-cleanup test log and its command, then run the full suite after the new authority changes. Append a row closing the earlier design comparison with the selected-design artifact. Keep the trail append-only. Do not count interrupted dispatches as reviews.
