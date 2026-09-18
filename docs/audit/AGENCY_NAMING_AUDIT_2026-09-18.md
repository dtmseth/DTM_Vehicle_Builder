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

## Proposed QBO renames — approval pending

This list was regenerated directly from the 239 active top-level QBO Customers.
No QBO names were changed while producing it.

| QBO ID | Before | After |
|---:|---|---|
| 102 | City Of Rice | City of Rice |
| 32 | City of St Augusta | City of Saint Augusta |
| 319 | City of St Louis Park | City of Saint Louis Park |
| 124 | City of St Michael | City of Saint Michael |
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
| 199 | St Cloud Refrigeration | Saint Cloud Refrigeration |
| 90 | St Cloud State Public Safety | Saint Cloud State Public Safety |
| 16 | St. Augusta Fire Department | Saint Augusta Fire Department |
| 117 | St. Cloud Auto Wrecking L.L.C. | Saint Cloud Auto Wrecking L.L.C. |
| 174 | St. Cloud Fire Department | Saint Cloud Fire Department |
| 23 | St. Cloud Police Department | Saint Cloud Police Department |
| 40 | St. Joseph Police Department | Saint Joseph Police Department |
| 366 | St. Joseph Public Works | Saint Joseph Public Works |
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

## Recommended manual sequence

1. Rename the remaining linked Customers in small reviewed batches. This can
   be done through Builder's agency save path; it performs a sparse update of
   the linked QBO Customer.
2. Run the normal customer import. Builder matches by durable QBO Customer ID,
   updates its agency name, and refreshes linked project display names; a rename
   does not unlink the Builder customer.
3. Re-run this audit and review any remaining custom/federal names individually.
