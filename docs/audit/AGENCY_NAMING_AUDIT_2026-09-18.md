# Agency Naming Audit — 2026-09-18

## Scope and safety

This began as a read-only re-audit after the owner merged the reviewed QBO duplicates.
Builder had 243 agency records at audit time; QBO now has 239 active top-level
Customers, down from 242. The live QBO read found 44 initial naming candidates. Two
Minnesota State Patrol Customers previously on the duplicate-ignore list were
later confirmed to be separate posts with unique DisplayNames.

The follow-up remediation merged the stale Hubbard and ICE Builder agencies into
their active survivors and rebound both projects without deleting project data.
Inactive-customer reconciliation removed the three unreferenced Saint Lewis test
agencies (`455`, `456`, and `457`). The three distinct Minnesota State Patrol
Customers were imported as `2400`, `2600`, and `4700`. Builder now has 240
agency records.

## Duplicate review

- Hubbard’s Builder project `7fe91739-7831-45d4-9fb3-c97babd24116` was rebound
  from merged-away QB `100000091` to the agency linked to surviving QB `100000111`.
- ICE’s Builder project `8f8b30dc-2325-40a2-8521-ab7c07c84b88` was rebound from
  merged-away QB `446` to the agency linked to surviving QB `443`.
- QBO `407` (Cold Spring) is gone from the active result, consistent with the
  completed merge.
- Minnesota State Patrol QBO IDs `38`, `39`, and `88` are distinct Customers:
  their unique DisplayNames end in `2600`, `2400`, and `4700`. They are not
  duplicates, and IDs `38` and `88` were removed from the import-ignore list.

## Applied QBO renames — 39

The initial proposal was revised against official entity names. Official `St.`
styling was retained, except for `Saint Paul`; Hennepin County was owner-confirmed
as sheriff-only. All 39 changes below were applied in QBO, read back for verification,
and imported into Builder by durable QBO Customer ID.

| QBO ID | Before | After |
|---:|---|---|
| 102 | City Of Rice | City of Rice |
| 32 | City of St Augusta | City of St. Augusta |
| 319 | City of St Louis Park | City of St. Louis Park |
| 124 | City of St Michael | City of St. Michael |
| 360 | Clearwater County Sheriff | Clearwater County Sheriff's Office |
| 408 | Columbia Heights Police Dept. | Columbia Heights Police Department |
| 169 | Crow Wing County Sheriff | Crow Wing County Sheriff's Office |
| 429 | Custer County Sheriff | Custer County Sheriff's Office |
| 430 | Dundas Police Dept. | Dundas Police Department |
| 433 | Fergus County Sheriffs Department | Fergus County Sheriff's Office |
| 100000001 | Granite County Sheriff Office | Granite County Sheriff's Office |
| 103 | Hector Volunteer Fire Dept. | Hector Volunteer Fire Department |
| 404 | Hennepin County | Hennepin County Sheriff's Office |
| 100000111 | Hubbard County Sheriff’s Office | Hubbard County Sheriff's Office |
| 30 | Kanabec County Sheriff's Department | Kanabec County Sheriff's Office |
| 387 | Koochiching County Sheriff | Koochiching County Sheriff's Office |
| 392 | McCone County Sheriff | McCone County Sheriff's Office |
| 374 | Mille Lacs County Sheriff | Mille Lacs County Sheriff's Office |
| 100000061 | Mille Lacs Tribal Police | Mille Lacs Tribal Police Department |
| 10 | Morrison County Sheriff | Morrison County Sheriff's Office |
| 364 | Nelson County Sheriff Department | Nelson County Sheriff's Office |
| 101 | Nobles County Sheriff | Nobles County Sheriff's Office |
| 363 | Prairie County Sheriff | Prairie County Sheriff's Office |
| 133 | Renville County Sheriff | Renville County Sheriff's Office |
| 231 | Sibley County Sheriff | Sibley County Sheriff's Office |
| 199 | St Cloud Refrigeration | St. Cloud Refrigeration, Inc. |
| 90 | St Cloud State Public Safety | St. Cloud State University Department of Public Safety |
| 117 | St. Cloud Auto Wrecking L.L.C. | St. Cloud Auto Wrecking, LLC |
| 391 | St. Paul Police Department | Saint Paul Police Department |
| 449 | Stark County Sheriffs Office | Stark County Sheriff's Office |
| 288 | Stearns County Highway Dept | Stearns County Highway Department |
| 2 | Stearns County Sheriff | Stearns County Sheriff's Office |
| 247 | Swift County Sheriff | Swift County Sheriff's Office |
| 100000041 | Three Affiliated Tribes Police | Three Affiliated Tribes Police Department |
| 447 | Waite Park Fire Deptartment | Waite Park Fire Department |
| 127 | Walsh County Sheriff | Walsh County Sheriff's Office |
| 331 | Washington County Sheriff | Washington County Sheriff's Office |
| 123 | Webster County Sheriff | Webster County Sheriff's Office |
| 34 | Winthrop Police Deptartment | Winthrop Police Department |

## Sales-rep link repair

Fourteen projects retained deleted duplicate sales-rep IDs even though their
stored names exactly matched a surviving rep. Eleven were rebound to the active
Dan Orth record and three to the active Don Starry record. All repairs were
mirrored to shared project storage, and a second audit found no unresolved or
stale project rep links. Project saves now make this same exact-name repair
automatically; ambiguous or fuzzy names still require an explicit selection.

## Final project-link audit

All 69 existing Builder projects were compared with current per-record agencies
and active QBO Customers. Eleven stale or blank project agency IDs were repaired
by unique canonical-name matches. This included the standardized Waite Park,
Granite, Kittson, Roseau County, and Rice County names as well as stale records
for Amery, Zumbrota, Rolette, ICE, and Bayport.

Roseau Police Department, Kittson County Sheriff's Office, and Roseau County
Sheriff's Office had no active or inactive QBO Customer, so they were created as
QBO IDs `458`, `459`, and `460`, respectively, imported into Builder, and linked
to their projects. All eleven repaired projects and all three agency records were
confirmed in shared storage. A final reconciliation found no stale, blank,
ambiguous, or name-mismatched agency links.

`Benton-Stearns Negotiator Van` remains the one intentional local-only custom
identity. There is no matching QBO Customer, and the record does not establish
whether Benton or Stearns County should be the accounting owner, so it was not
silently reassigned.

## Applied synchronization result

- QBO verification: all 39 IDs returned the approved target name.
- Builder import: 39 updated, 200 unchanged, 0 created, 239 total.
- Existing official names `St. Augusta Fire Department`, `St. Cloud Fire
  Department`, `St. Cloud Police Department`, `St. Joseph Police Department`,
  and `St. Joseph Public Works` were deliberately left unchanged.
