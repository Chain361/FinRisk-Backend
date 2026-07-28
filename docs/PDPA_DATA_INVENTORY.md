# PDPA Data Inventory: Vendors and Projects

Scope: procurement project and vendor data stored in `vendors` and `projects`.

## Field Classification

| Field | Classification | Masking/access policy |
|---|---|---|
| `vendors.tin`, source `winner_tin` | Personal/high-risk identifier when vendor is a natural person; business identifier for juristic persons | Never expose raw value to `public_user` or public export. Store as `TEXT`; keep original `xxxx` masking; otherwise show only last 4 digits. |
| `vendors.name`, source `winner_name` | Personal data when prefixed with `นาย`, `นาง`, `นางสาว`, or small-shop style `ร้าน`; business/public procurement data for juristic persons | For `public_user`, mask natural-person style names but keep company names visible. |
| `projects.contract_no` | Contract identifier, can identify small vendors or link to external records | Hide from `public_user`; visible to scoped internal roles. |
| `projects.contract_date`, `projects.contract_finish_date`, `projects.contract_duration_days`, `projects.contract_status` | Contract details | Hide from `public_user` project detail; aggregate/dashboard fields remain visible. |
| `projects.vendor_id` | Internal join key to vendor record | Hide from `public_user`. |
| `projects.data_quality_note` | Internal data-quality note; may mention hidden identifiers | Mask long numeric sequences before public display. |
| `projects.project_name` | Public procurement data but can include person/place references | Keep visible for transparency; review future uploads if names of private residents appear. |
| Project location / latitude / longitude if added later | Potential personal/location data when tied to a household or private property | Public display should coarse-round coordinates; exact values internal only. |
| `fraud_risk_issues` in CSV source | Potential allegation about a person/vendor | Do not expose in public export. If added to API later, treat as internal/audit-only. |

## Implementation

- `src/privacy.py` contains masking helpers for TIN, person-like vendor names, sensitive notes, and coarse coordinates.
- `src/services/projects.py::project_summary_view` applies `mask_project_for_public()` when `user["role"] == "public_user"`.
- `src/routers/public.py` export intentionally returns only dashboard/open-data fields and does not include vendor/TIN/contract detail fields.

## Tests

- Public project detail must not expose raw TIN, `vendor_id`, or contract identifiers.
- Internal roles may still access unmasked project detail within normal role/scope guards.
- Public export must remain limited to the approved open-data field list.
