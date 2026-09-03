# Legacy Build Photos migration plan

This is the reviewed, copy-first plan and execution record for `Shop Documents/Build Photos`. The
source tree remains untouched after every copied destination and app record was verified. It supplements
[`BUILD_REFERENCE_PHOTOS.md`](BUILD_REFERENCE_PHOTOS.md); that document remains the product contract.

## Completed execution (2026-08-27)

- Created the approved joint `Benton-Stearns Negotiator Van` agency with abbreviation `BSNV`.
- Created and directly mirrored 35 ordinary completed projects containing 46 sparse build groups.
- Provisioned their normal Company/Shop agency, year, group, vehicle, and photo folders.
- Copied all 1,043 files server-side into the corresponding **Completed Build Photos** folders.
  Per-group relative paths and sizes match, and both source and destination total 11,934,028,588
  bytes. A post-migration comparison of all 1,120 source items against the pre-migration manifest
  found zero ID/path/size/eTag changes, so legacy `Shop Documents/Build Photos` remains unchanged.
- Rechecked and deleted the 184 unintended empty Company roots and 184 unintended empty Shop roots
  by exact item ID. SharePoint recycle-bin recovery remains available. Cleared and directly
  re-mirrored only those operational folder-state fields on the corresponding 184 standalone
  agency records.
- Final independent verification found exactly 36 approved roots in each database, exact local/cloud
  equality for all 35 project records, a valid remote `BSNV` record, and cleared remote folder state
  for all 184 standalone agencies.

## Read-only inventory (2026-08-27)

- 28 agency-level source folders under Fire Builds, Police Builds, and Other Builds.
- 46 source build/photo groups.
- 1,043 files, including nested files such as the Cottage Grove K-9 subfolder.
- 45 groups explicitly identify build year 2025 or 2026.
- Those 45 groups consolidate to 34 unique agency/year projects across 27 existing saved agencies.
- `Benton-Stearns Negotiator Van` contains 90 direct photos but no year folder. EXIF samples from
  the first, middle, and last filename positions are all from November/December 2025, so **2025**
  is the approved year. It becomes the joint app agency `Benton-Stearns Negotiator Van` (`BSNV`),
  bringing the migration total to 35 completed agency/year projects.

## Agency reconciliation

Folder category is part of the match. For example, `Cottage Grove PD` maps to the Police Department,
not Public Works, and `Sartell FD` remains distinct from `Sartell PD`. No fuzzy match is applied as a
write; these are explicit reviewed aliases to durable existing agency IDs.

| Source agency folder | Saved app agency | Project years |
|---|---|---|
| Cohasset FD | Cohasset Fire Department | 2026 |
| Foley FD | Foley Fire Department | 2025 |
| Grand Rapids FD | Grand Rapids Fire Department | 2026 |
| Little Falls FD | Little Falls Fire Department | 2025 |
| Pequot Lakes FD | Pequot Lakes Fire Department | 2025 |
| Sartell FD | Sartell Fire Department | 2025, 2026 |
| City of Otsego | City of Otsego | 2026 |
| Brainerd PD | Brainerd Police Department | 2025, 2026 |
| City of Blaine | City of Blaine | 2025 |
| Cottage Grove PD | Cottage Grove Police Department | 2025, 2026 |
| Edina PD | Edina Police Department | 2025 |
| Grand Rapids PD | Grand Rapids Police Department | 2025, 2026 |
| Kandiyohi County Sheriff | Kandiyohi County Sheriff's Office | 2025 |
| Melrose PD | City of Melrose | 2026 |
| Mille Lacs County Sheriff | Mille Lacs County Sheriff | 2026 |
| Minneapolis PD | Minneapolis Police Department | 2025 |
| Nisswa PD | Nisswa Police Department | 2026 |
| Prairie County Sheriff | Prairie County Sheriff | 2025, 2026 |
| Proctor PD | Proctor Police Department | 2026 |
| Royalton PD | Royalton Police Department | 2025 |
| Sartell PD | Sartell Police Department | 2025 |
| Sauk Rapids PD | Sauk Rapids Police Department | 2025 |
| St. Cloud PD | St. Cloud Police Department | 2026 |
| St. Joe PD | St. Joseph Police Department | 2025, 2026 |
| Stearns County Sheriff | Stearns County Sheriff | 2025 |
| Walsh County Sheriff | Walsh County Sheriff | 2025 |
| Yellow Medicine County | Yellow Medicine County Sheriff's Office | 2025, 2026 |
| Benton-Stearns Negotiator Van | New joint agency `Benton-Stearns Negotiator Van` (`BSNV`) | 2025 |

## Sparse build translation

Each source build folder becomes one sparse build/unit-group entry inside its agency/year project.
Because the old tree does not reliably identify physical unit counts, unit numbers, or VINs, each
source group initially receives one stable pending individual. A plural folder such as `Tahoes`
does not justify inventing multiple vehicles. The app can split or enrich these later when real
identifiers become available.

`Vehicle` below means the source names a role or make but not a reliable model. This is intentional,
not missing migration work.

Concrete imported models that were absent from the five original app layouts are now selectable as
**artwork pending** vehicle definitions; their real view images can be added later without changing
the sparse project IDs or photo folders. Case-only historical values resolve to canonical layout
IDs. At initial import, plain `Vehicle` and the mixed `Tahoe & Silverado` source remained explicit
unresolved values: the app did not invent a model or split/reassign photos without owner review.

Owner review on 2026-08-28 resolved the mixed Walsh County group into Tahoe Patrol (18 files) and
Silverado 3500 Patrol (10 files), preserving the existing photo items. The same review enriched
Edina to Blazer EV Patrol, PIU K-9, and Lightning Unmarked. Walsh's saved IDs/paths already matched
the reorganized folders. Edina's saved paths were repaired from the durable vehicle IDs: its three
populated Shop vehicle trees retained 7 / 24 / 19 files and 48,834,978 / 382,827,034 / 325,923,152
bytes. The later flat-tree migration moved all vehicle folders directly beneath their project year
and removed these and the other verified-empty group containers to the SharePoint recycle bin.

Seven sparse groups still need an owner-supplied vehicle model; their roles alone are not enough to
infer one:

- City of Otsego — 2026 Truck Rack;
- Pequot Lakes Fire Department — 2025 Grass Rig;
- Cohasset Fire Department — 2026 Truck;
- Sartell Fire Department — 2026 Chief Truck;
- Stearns County Sheriff — 2025 K-9;
- Little Falls Fire Department — 2025 Grass Rig;
- Foley Fire Department — 2025 Grass Rig.

| Source build folder | Model | Build type/role | Files |
|---|---|---|---:|
| '26 CFD Truck | Vehicle | Truck | 25 |
| '25 Foley Grass Rig | Vehicle | Grass Rig | 7 |
| '26 GRFD Chevy 3500 | 3500 |  | 15 |
| '25 LFFD F-150 Chief Truck | F-150 | Chief Truck | 13 |
| '25 LFFD GMC Grass Rig | Vehicle | Grass Rig | 13 |
| '25 PLFD F-550 Rescue Truck | F-550 | Rescue Truck | 14 |
| '25 PLFD Grass Rig | Vehicle | Grass Rig | 10 |
| '25 SFD Expedition Command | Expedition | Command | 32 |
| '25 SFD Lightnings | F-150 Lightning |  | 20 |
| '26 SFD Chief Truck | Vehicle | Chief Truck | 27 |
| '26 Otsego Truck Rack | Vehicle | Truck Rack | 7 |
| Benton-Stearns Negotiator Van | Van | Negotiator | 90 |
| '25 BPD Utility | PIU |  | 17 |
| '26 BPD Tahoes | Tahoe |  | 26 |
| '25 Blaine Utility | PIU |  | 9 |
| '25 CGPD Durangos | Durango |  | 43 |
| '26 CGPD Jeep | Jeep |  | 2 |
| '25 EPD Blazer EVs | Blazer EV |  | 7 |
| '25 EPD K-9 | Vehicle | K-9 | 24 |
| '25 EPD Lightning | F-150 Lightning |  | 19 |
| '25 GRPD Durangos | Durango |  | 19 |
| '26 GRPD Durango | Durango |  | 26 |
| '25 Kandi Durangos | Durango |  | 19 |
| '26 MPD Durango | Durango |  | 29 |
| '26 MPD F-150 | F-150 |  | 1 |
| '26 Silverado | Silverado |  | 39 |
| '25 MPD Harley's | Harley |  | 15 |
| '26 NPD Utility | PIU |  | 37 |
| '25 Prairie Co Ram 1500 | Ram 1500 |  | 11 |
| '26 Prairie Co Durangos | Durango |  | 41 |
| '26 PPD PIU | PIU |  | 25 |
| '25 RPD Tahoe | Tahoe |  | 31 |
| '25 Sartell Blazer EVs | Blazer EV |  | 16 |
| '25 Sartell Mach-E | Mach-E |  | 8 |
| '25 SRPD F-150 | F-150 |  | 30 |
| '25 SRPD Utility '25 | PIU |  | 23 |
| '26 SCPD Chevy Traverse | Traverse |  | 38 |
| '26 SCPD PIU Full Cage | PIU | Full Cage | 27 |
| '26 SCPD PIU Half Cage (Troy) | PIU | Half Cage (Troy) | 37 |
| '25 SJPD Tahoe | Tahoe |  | 19 |
| '26 SJPD Explorer | PIU |  | 32 |
| '25 Stearns K-9 | Vehicle | K-9 | 1 |
| '25 Stearns Utility | PIU |  | 19 |
| '25 Walsh Tahoe & Silverado | Tahoe & Silverado |  | 28 |
| '25 YMC Tahoes | Tahoe |  | 33 |
| '26 YMC Durangos | Durango |  | 19 |

## Project and copy behavior used

1. Take a fresh local project/agency backup and a read-only source manifest with item IDs, paths,
   sizes, and eTags.
2. Create or extend exactly one ordinary project per durable agency ID and build year. Existing
   agency/year projects are extended, never duplicated.
3. Set imported projects to `project_status: completed` with a completion timestamp so they appear
   only in Project Archives. Do not add a historical flag, label, or migration-only project field.
4. Provision their normal Company/Shop trees by project ID. Standalone Agency Manager/QBO records
   remain out of scope.
5. Copy every source group recursively into its pending individual's **Completed Build Photos**.
   Preserve filenames and report collisions; never overwrite a different destination item.
6. Verify per-group and total counts (1,043), byte sizes, eTags/hashes where available, saved
   destination item IDs, and in-app browse/open behavior.
7. Keep `Shop Documents/Build Photos` unchanged through project creation, copy, verification, and
   app cutover. Archiving/deleting that source tree requires a later explicit approval.

## Mistaken-root cleanup result

The first live provisioning pass created 219 agency roots in each new database because it treated
all Agency Manager/QBO Customers as project agencies. The corrected runtime is project-scoped.
Current projects plus the confidently mapped historical agencies accounted for 35 roots already
present in each database; adding `BSNV` brought the approved final set to 36. The remaining 184
Company roots and 184 Shop roots were rechecked and were all empty.

Cleanup used the saved Graph item IDs, rechecked the exact parent and live empty child listing
immediately before deletion, and cleared only the corresponding folder-state fields on those
standalone agency records. The first settings reconciliation encountered one transient direct-mirror
failure after deletion; the resumable state-only pass reverified both roots, then successfully
re-mirrored all 184 records. This cleanup remained separate from—and did not touch—the legacy
`Build Photos` source.
