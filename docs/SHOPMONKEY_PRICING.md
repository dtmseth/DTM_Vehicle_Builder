# Shopmonkey pricing source of truth

The Builder’s Shopmonkey pricing automation starts with the live QuickBooks Online price rules audited on 2026-11-03. The DTM Vendor Pricing Guide extends that baseline only where it supplies a reviewed Standard Sell rule that QBO does not contain. A missing Wholesale rule stays disabled; the app does not copy Retail pricing into Wholesale without evidence.

## QuickBooks Online rules

| Rule | Customer scope | Products and services | Calculation |
| --- | --- | --- | --- |
| Gamber Johnson 30% | Retail | GAMBER JOHNSON CRADLE/DOCK | List less 30% |
| Gamber Johnson 40% Off List | All Customers | GAMBER JOHNSON | List less 40% |
| Havis 20% Off List | All Customers | HAVIS | List less 20% |
| Pac Tool 5% Off | Retail | PAC TOOL | List less 5% |
| Santa Cruz 25% Off List | Retail | SANTA CRUZ | List less 25% |
| Setina 20% Off List | Retail | SETINA | List less 20% |
| Setina 30% Off List | Wholesale | SETINA | List less 30% |
| SoundOff 45% | Retail | SOUNDOFF SIGNAL | List less 45% |
| Tiger Tough 10% Off List | Retail | TIGER TOUGH | List less 10% |
| Westin 25% Above Cost | Retail | WESTIN | Cost plus 25% |
| Whelen 36% Off List | Retail | WHELEN | List less 36% |
| Whelen 43% Off | Wholesale | WHELEN | List less 43% |

“All Customers” is loaded into Retail, Wholesale, and Default / untagged. The default type applies only when a customer matches neither configured pricing-type label; unrelated Shopmonkey labels do not disqualify it. Retail-only rules are not copied into Wholesale or Default / untagged. A customer matching both Retail and Wholesale is ambiguous and is skipped. The Westin product group is mapped to the Westin-family Shopmonkey brands: Brute, Fey, Superwinch, SW Military, Westin, and Westin Public Safety.

## Vendor guide additions

The guide adds reviewed Retail Standard Sell formulas that have no QBO rule: Kussmaul 10% off list, NightRide cost plus 25%, Patrol PC 26% off list, REDARC 10% off list, and TruckVault 10% off list.

The guide also documents programs that cannot be expressed as one unconditional brand percentage:

- Whelen national and territory packages at cost plus 35%, 10+ pricing, and master-discount exceptions.
- Setina volume discounts and crate quantities.
- Gamber Johnson 62% bulk pricing, shipping negotiation, and secondary-company component checks.
- SoundOff bulk pricing up to 65% off list and promotions sold at promo cost plus 35%.
- Santa Cruz volume tiers.
- Kussmaul 10–49 and 50+ quantity tiers.
- PAC Tool 25+ pricing.
- Price-sheet or fitment-dependent programs for American Aluminum, Angel Armor, and other vendors without a single formula.

## Exceptions requiring explicit handling

QBO’s Gamber Johnson Retail rule applies 30% only to the GAMBER JOHNSON CRADLE/DOCK product group, while its broader 40% rule applies to all customers. The current Shopmonkey automation matches brand and customer label, not a QBO product group. It therefore uses the 40% brand default and leaves the 30% exception documented until product-level matching is added.

Westin conflicts across sources. QBO applies cost plus 25% to Retail customers, while the vendor guide states Standard Sell is 15% off list. The audited loader follows QBO and does not silently load the guide formula.
