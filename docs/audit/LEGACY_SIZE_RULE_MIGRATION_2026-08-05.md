# Legacy size-rule migration — 2026-08-05

The old `asset_manifest.json.part_number_size_rules` map has been retired. It matched arbitrary
text, including the unsafe numeric `"3"` and `"6"` substrings. Size now comes from a real identity:

`SKU override → product → part type → Small profile`

`products.<id>.model_aliases` is used only to recognize an older saved product/model label exactly
after normalization; it is not a size matching rule. The legacy map remains as an empty
compatibility field so older manifest files can load safely, but the resolver does not read it.

| Retired text rules | Profile | Explicit parts-db translation |
| --- | --- | --- |
| `3`, `6` | `rd` | `whelen_round_lighthead`, exact legacy model aliases `3` and `6` |
| `ION`, `STANDARD MOUNT ION`, `SURFACE MOUNT ION`, `T-ION` | `sm` | Whelen ION, ION V-Series, Surface Mount ION, and ION-T HD Array |
| `VXE`, `VERTEX` | `sq`, `rd` | `whelen_vxe`, `whelen_vertex` |
| `M4` | `md` | `whelen_m4`, `soundoff_m4` |
| `MPOWER`, `M-POWER` | `sm` | SoundOff MPOWER plus its 3-inch and 4-inch fascia products |
| `N-FORCE`, `NFORCE`, `INTERSECTORS` | `sm` | SoundOff NFORCE, NForce Deck/Grille, and Intersector Surface-Mount |
| `U-SERIES`, `MIRROR BEAMS` | `sm` | Whelen U-Series and Mirror-Beam |
| `2 LAMP TRACER`, `TRACER 5 LAMP`, `TRACER 6 LAMP` | `tracer` | Whelen 2-, 3-, 5-, and 6-Lamp Tracer products (the 3-Lamp family member is normalized too) |
| `MINI T-SERIES`, `T-SERIES`, `MEGA T-SERIES` | `sq`, `sm`, `long` | Whelen Mini T-Series, T-Series, and Mega T-Series |
| `FIELD SERIES` | `tracer` | Whelen Field Series |
| `PIONEER` | `PN` | Pioneer Micro, Nano, Plus, and SlimLine. This preserves the modern explicit Pioneer profile; it intentionally replaces the old broad `lg` match. |
| `AM-900` | `md` | Feniex AM900 Work Light |
| `SA315P`, `SA315U`, `SA350MH`, `SP123BMC`, `295SLSA6` | `sm` | Superseded by `siren_speaker.render.size_per_view`; equipment sizing does not use icon profiles. |

This migration preserves the former profile intent for actual lights and removes accidental
matches on unrelated models/SKUs. Any newly added product inherits the explicitly assigned part
type profile until it is given its own product or SKU assignment in the Size Rules page.
