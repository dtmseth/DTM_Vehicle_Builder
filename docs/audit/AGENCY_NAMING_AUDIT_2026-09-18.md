# Agency Naming Audit — 2026-09-18

## Scope and safety

This is a read-only re-audit after the owner merged the reviewed QBO duplicates.
Builder had 243 agency records at audit time; QBO now has 239 active top-level
Customers, down from 242. The live QBO read found 44 naming candidates. Two
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

## Standardization candidates

### Saint — 12

- `City of St Augusta` → `City of Saint Augusta`
- `City of St Louis Park` → `City of Saint Louis Park`
- `City of St Michael` → `City of Saint Michael`
- `St Cloud Refrigeration` → `Saint Cloud Refrigeration`
- `St Cloud State Public Safety` → `Saint Cloud State Public Safety`
- `St. Augusta Fire Department` → `Saint Augusta Fire Department`
- `St. Cloud Auto Wrecking L.L.C.` → `Saint Cloud Auto Wrecking L.L.C.`
- `St. Cloud Fire Department` → `Saint Cloud Fire Department`
- `St. Cloud Police Department` → `Saint Cloud Police Department`
- `St. Joseph Police Department` → `Saint Joseph Police Department`
- `St. Joseph Public Works` → `Saint Joseph Public Works`
- `St. Paul Police Department` → `Saint Paul Police Department`

### Sheriff's Office — 23

- Clearwater, Crow Wing, Custer, Fergus, Granite, Hubbard, Kanabec,
  Koochiching, McCone, Mille Lacs, Morrison, Nelson, Nobles, Prairie, Renville,
  Hennepin, Sibley, Stark, Stearns, Swift, Walsh, Washington, and Webster County records
  use `Sheriff`, `Sheriffs`, `Sheriff Office`, or `Sheriff Department` instead
  of `County Sheriff's Office`. A bare name ending in `County`, such as
  `Hennepin County`, is now included in this warning.

### Department names — 5

- `Columbia Heights Police Dept.` → `Columbia Heights Police Department`
- `Dundas Police Dept.` → `Dundas Police Department`
- `Hector Volunteer Fire Dept.` → `Hector Volunteer Fire Department`
- `Mille Lacs Tribal Police` → `Mille Lacs Tribal Police Department`
- `Three Affiliated Tribes Police` → `Three Affiliated Tribes Police Department`

### City casing — 1

- `City Of Rice` → `City of Rice`

### Other full-name/typo review

- `Stearns County Highway Dept` → `Stearns County Highway Department`
- `Waite Park Fire Deptartment` → `Waite Park Fire Department`
- `Winthrop Police Deptartment` → `Winthrop Police Department`

## Recommended manual sequence

1. Rename the remaining linked Customers in small reviewed batches. This can
   be done through Builder's agency save path; it performs a sparse update of
   the linked QBO Customer.
2. Run the normal customer import. Builder matches by durable QBO Customer ID,
   updates its agency name, and refreshes linked project display names; a rename
   does not unlink the Builder customer.
3. Re-run this audit and review any remaining custom/federal names individually.
