# Operations Entra Setup

**Status:** Owner configured; ready for additional user assignments
**Last updated:** 2026-09-07

This is the one-time configuration for the existing DTM public-client app registration. It adds
application roles only; it does not add a client secret, application permission, premium connector,
or separate SharePoint permission scheme.

## Permanent role definitions

Create each role under **Microsoft Entra admin center → App registrations → the existing DTM app →
App roles → Create app role**. Set **Allowed member types** to **Users/Groups** and enable the role.
The Value is the permanent machine identifier and must match exactly.

| Display name | Value | Description |
|---|---|---|
| DTM App Administrator | `AppAdmin` | Administer all DTM Builder and Operations workspaces. |
| DTM Builder Editor | `BuilderEditor` | Create projects, design builds, and manage estimates. |
| DTM Operations Manager | `OperationsManager` | Coordinate scheduling, production, delivery, and corrections. |
| DTM Parts Editor | `PartsEditor` | Update parts receiving and readiness. |
| DTM Shop Editor | `ShopEditor` | Update Build / Shop, Tray, and Final Finish work. |
| DTM Programming & QC Editor | `ProgrammingQcEditor` | Update Programming & QC and Final Finish work. |
| DTM Operations Viewer | `OperationsViewer` | View Operations without changing workflow state. |

Do not repurpose a Value later. Add a new role if its meaning changes materially. Entra generates
the underlying UUID for each role; the application uses the stable Value claim rather than that
portal-generated ID.

## Initial assignment

1. Open **Enterprise applications → the existing DTM application → Users and groups**.
2. Assign the owner the **DTM App Administrator** role.
3. Sign out of Microsoft 365 inside Vehicle Builder and sign back in so Entra issues a fresh ID
   token containing `roles: ["AppAdmin"]`.
4. Confirm the Operations header appears, the shared backlog loads, and the assigned role exposes
   only its intended status actions.

Add other users only when their workspace is ready. Direct user assignment is sufficient for the
current small team. Group assignment may be used later if the tenant's licensing and assignment
policy support it.

Microsoft's role setup and assignment procedure is documented at
[Add app roles and get them from a token](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps).

## Rollback

Remove a user's enterprise-app role assignment and have that user sign out/in. Do not delete or
rename role Values that have already been issued. Removing assignments does not change the user's
inherited SharePoint site permission; it removes the corresponding DTM app capability.
