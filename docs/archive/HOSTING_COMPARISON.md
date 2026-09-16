# Full Builder hosting comparison

Reviewed September 10, 2026. Planning only; no host selected or deployed.
Azure is the preferred pilot candidate if affordable; OVHcloud is the cost fallback.
Execution order and next-session instructions live in [AZURE_PILOT_PLAN.md](AZURE_PILOT_PLAN.md). Prices below are USD, before tax, and cover shared
infrastructure rather than eleven end-user licenses. Starting prices are not total deployment bills.

## What the host must support

- The same HTML Builder on desktop and installed phone browsers, with responsive and touch layouts.
- Python business services, image processing, and Linux document exports including LibreOffice.
- Microsoft Entra sign-in and server-enforced employee roles; separate concurrent user sessions.
- SharePoint documents and records, durable background jobs, and a proposed central QBO connection.
- Recoverable persistent state, encrypted server credentials, monitoring, and backups.

Hosting does not itself solve desktop-global state, request isolation, background-job recovery,
or shared QBO authentication. Those require application changes on every provider. Keep existing
production keychain rules until a replacement credential model is reviewed and implemented.

Compare 2–4 GB runtime configurations initially, with queued exports. This is an experiment size,
not a measured minimum. Keep existing documents/photos in SharePoint initially. Count host-side
sessions, credentials, jobs, logs, storage, transfer, and backups in the total bill.

## Self-managed servers

These can run the Python application and export tools together. We maintain the operating system,
deployments, application monitoring, and recovery. Included provider backups do not replace a tested
application restore procedure.

| Provider | Published comparison point | Assessment |
|---|---|---|
| [OVHcloud US](https://us.ovhcloud.com/vps/) | Advertised from **$4.54/month**, 2 vCores, 4 GB RAM, 40 GB disk, daily backup | Strong cash-cost candidate. Confirm the selected region, term, renewal price and actual availability before treating this as the ongoing quote. |
| [Hostinger VPS](https://www.hostinger.com/vps-hosting) | 4 GB **$6.49/month introductory**, renews at **$11.99/month for two years**; 8 GB $8.99 introductory, renews at $14.99 | Competitive price with weekly backups. Monthly equivalents are billed upfront; evaluate commitment and renewal cost. |
| [IONOS VPS](https://www.ionos.com/servers/vps) | 4 GB **$4/month for three months**, listed regular **$11**, with a one-year term | Useful low-cost comparison; $4 is not the continuing monthly rate. |
| [AWS Lightsail](https://aws.amazon.com/lightsail/pricing/) | Public IPv4 Linux **$12/month for 2 GB**, **$24 for 4 GB** | Predictable bundles without a multi-year hosting commitment. Snapshots are extra; simpler purchasing than assembling EC2 services. |
| [DigitalOcean Droplets](https://www.digitalocean.com/pricing/droplets) | **$12/month for 2 GB**, **$24 for 4 GB** | Comparable predictable server baseline. Backups extra. |
| [Akamai/Linode](https://www.akamai.com/cloud/pricing/north-america) | Shared CPU **$12/month for 2 GB**, **$24 for 4 GB** | Another direct Lightsail/DigitalOcean alternative. Backups extra. |
| [GoDaddy VPS](https://www.godaddy.com/hosting/vps-hosting) | 2 GB **$8.99/month**, 4 GB **$17.99/month**, advertised with three-year terms | Existing billing convenience; compare the commitment and regular price. No application or M365 integration advantage from also registering the domain there. |
| [Hetzner](https://www.hetzner.com/cloud/) | Select actual US region and available machine before quoting | Worth considering, but European/ARM entry prices are not equivalent to a US x86 deployment. [June 2026 price changes](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/) make older comparisons unreliable. |
| [Vultr](https://docs.vultr.com/products/compute/cloud-compute) | Current live price not verified in this research | Technically relevant general-purpose VM alternative. Do not substitute third-party pricing for a current regional quote. |

## Managed application hosting

These reduce operating-system administration. We still own application security, dependencies,
data protection, and job correctness. Usage billing, sleeping instances, and temporary filesystems
need to be designed around; always-on polling can erase scale-to-zero savings.

| Provider | Published cost model | Assessment |
|---|---|---|
| [Azure Container Apps](https://azure.microsoft.com/en-us/pricing/details/container-apps/) | Consumption billing with monthly free grants: 180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests | Major candidate because of Microsoft integration and managed containers. At 1 CPU/2 GiB the compute grants represent 50 active instance-hours, not an always-on free server. Logs, storage, registry and other services can add cost. |
| [Google Cloud Run](https://cloud.google.com/run/pricing) | Usage billing and free allowances | Strong container alternative for intermittent workloads. Separate scheduled/background work appropriately; request and instance billing behave differently. M365 authentication is possible without making employees use Google accounts. |
| [Railway](https://docs.railway.com/pricing) | Hobby **$5 minimum**, Pro **$20 minimum**, credited toward resource usage | Convenient deployment. These are spending floors, not unlimited compute or fixed total prices. Remains a candidate, no longer the default first choice. |
| [Render](https://render.com/pricing) | **$7/month for 512 MB**, **$25/month for 2 GB**, plus applicable workspace/storage charges | Straightforward app hosting. Tiny/free instances are not evidence that document exports will fit. Hosting administrator seats are separate from Builder users. |
| [Fly.io](https://fly.io/docs/about/pricing/) | Regional machine usage plus volumes/transfer | Good container flexibility; compare an actual regional machine quote and persistent job behavior. Operational setup sits between a simple app platform and a conventional server. |

Azure offers [built-in Entra authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication).
We still need explicit employee authorization and Builder role checks. Existing Microsoft 365
subscriptions do not pay Azure compute charges.

[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
also deserves mention: current documentation provides an ARM allowance equivalent to 2 OCPUs and
12 GB RAM. Treat it as an experiment until regional capacity, ARM dependencies, and recovery are
proven. It is not the first production recommendation solely because of a zero-dollar headline.

Netlify remains useful for the existing broker and potentially frontend hosting. It is not a
drop-in host for the current persistent Python/LibreOffice process. Vercel and Cloudflare may suit
parts of a split deployment, but adding another platform is not justified merely to obtain free
static hosting. This is a workload-fit judgment, not a claim that those platforms lack backends.

## Trial terms

- [Azure](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account): eligible new
  customers receive $200 for 30 days. Verify account eligibility before relying on credits.
- [Google Cloud](https://cloud.google.com/signup-faqs): eligible new customers receive $300 for
  90 days. Included services and continuing paid resources need checking when choosing the pilot.
- [Railway](https://docs.railway.com/pricing/free-trial): $5 credit or 30 days, whichever ends first.
  Limited Trial accounts restrict outbound networking; verify Microsoft/Intuit connectivity.
- [Fly.io](https://fly.io/docs/about/free-trial/): two total VM hours or seven days, whichever comes
  first. Trial machines stop after five minutes; adding a payment method ends the trial.
- [Lightsail](https://aws.amazon.com/free/compute/lightsail/): advertises 90 days on selected
  bundles under qualifying paid-account terms. The $12 Linux bundle is eligible in the advertised
  offer; do not assume the $24 bundle is. Check existing-account eligibility and AWS Free Tier terms.
- [Render free services](https://render.com/docs/free): sleep after 15 minutes without traffic and
  cannot attach a persistent disk. Useful for demos, not proof of reliable continuous jobs.
- Hostinger and IONOS advertise 30-day money-back guarantees. Those require a purchase and are not
  free trials. No current DigitalOcean credit offer was verified for this account.

## Selection status

The owner prefers Azure if the measured ongoing cost is acceptable. Prepare the portable prototype
first, then test Azure; evaluate OVHcloud if the result does not justify Azure's cost. The detailed
scenarios below explain the target. Trial credits help testing but do not determine the production
choice. No host removes the shared-user or central QBO migration work.

## OVHcloud versus Azure: owner preference and priced scenarios

The owner prefers Azure if the cost is competitive. Azure Container Apps Consumption is the
candidate here, not an Azure VM, Dedicated plan, or Kubernetes cluster. No purchase or deployment
is authorized by this comparison.

September 10 Central US USD retail rates were retrieved directly using Microsoft's public
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
filtering `serviceName eq 'Azure Container Apps' and armRegionName eq 'centralus' and priceType eq
'Consumption'`. Standard rates: active vCPU $0.000024/second, idle vCPU $0.000003/second, active and
idle memory $0.000003/GiB-second, requests $0.40/million beyond the grant. Container Registry Basic
in the same region is $0.1666/day, about $5/month. These are retail rates, not an account quote.

Illustrative monthly scenarios, not measured Builder forecasts:

| Scenario | Assumptions | Approximate monthly cost |
|---|---|---|
| Small app kept ready, separate jobs | One 0.5 vCPU/1 GiB app replica; 176 active hours and 554 genuinely idle hours. Another 20 active hours at 1 vCPU/2 GiB for exports and scheduled jobs combined. | App compute about $13–17 depending on free-grant allocation; jobs about $2.16. Add $5 registry and $5–10 allowance for modest storage, secrets, logs, backup and transfer: budget **$25–35**. |
| Larger app kept ready, separate jobs | Same hours, but 1 vCPU/2 GiB app, plus the same jobs allowance. | App compute about $32–35, jobs $2.16, registry and other allowance as above: approximately **$40–50**. |
| Larger app continuously active | One 1 vCPU/2 GiB replica billed active for all 730 hours. | Compute about $73.44 after grants, plus registry and other allowance: approximately **$85–90**, potentially more with additional workers. |

The compute examples assume the subscription's monthly grants remain available, fewer than two
million requests, and no other replicas. The lower warm-app figures allocate grants to active
usage; budget ranges accommodate a smaller saving. Grant accounting is subscription-wide, not
repeated for the worker. Ancillary allowances are estimates, not separately verified deployment
quotes. Existing Microsoft 365/QBO subscriptions, tax, engineering, and paid support are excluded.
The storage assumption is modest host-side state with existing documents/photos retained in
SharePoint. A new always-on database, premium network features, high log volume, or substantially
more job hours changes the estimate.

Per [Azure billing rules](https://learn.microsoft.com/en-us/azure/container-apps/billing), keeping
a minimum replica permits reduced idle billing only when it meets idle conditions. Requests and
background CPU/network activity can make it active. Existing app polling must be measured and
adapted. Scheduled checks and exports should use durable jobs that can run independently of
someone leaving a browser open. Small-server sizing and larger export sizing both need tests.

OVHcloud advertises 4 GB/2 vCores from $4.54/month with daily backup. Its Configure link selects
`pricing=upfront12`; the rendered configurator did not expose checkout totals or renewal terms.
Treat it as a promotional starting quote pending confirmation, not a verified flexible monthly
price. It provides more continuously available resources for less cash, with OS patching and
server recovery owned by us. Azure handles the underlying hosting platform; we still maintain
our container dependencies, application, access rules and data recovery.

Decision rule carried into [AZURE_PILOT_PLAN.md](AZURE_PILOT_PLAN.md): prepare an Azure-first pilot
with **$25–35/month as the target**, and revisit
OVHcloud if the measured ongoing bill exceeds approximately $50 without a worthwhile benefit.
This threshold is a proposed decision rule, not an approved spending limit. Use the trial to
measure post-credit cost, page opening time, concurrent users, large exports and background checks.
Configure modest replica limits and cost alerts when a deployment is approved;
[Azure budgets are alerts, not hard spending caps](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).
M365 sign-in and central QBO are possible on both; Azure's built-in authentication reduces some
integration work but does not eliminate the shared-application migration.
