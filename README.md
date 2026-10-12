# GBB Industries on Odoo 19: demo repository

This repository holds one Odoo 19 module, `gbb_erp`, that shows every screen of GBB's in-house ERP inside Odoo, plus a demo data set that can be loaded and removed in one click.

## What is in it

| Area | What the module adds on top of standard Odoo |
|---|---|
| GBB ERP menu | One app called **GBB ERP** with the same sidebar sections and screen names as the current ERP: Sales, Design & Engineering, Purchase & Stores, Operations, Analytics, Accounts, HR & People, Security, Master, Tools. Each item opens the matching Odoo screen. |
| Sales | Inquiry numbers E-n per financial year (April to March), inquiry review tab, quotation numbers `GBB/SQ/<FY>/<E-no>`, revisions `-R01`, confidential cost breakup per fixture (GBB default breakup, machining = material x factor, profit %, risk), Director approval before a quote is sent or booked, order booking and order review tabs, order status (Under Design, Under Manufacturing, Dispatched, On Hold). |
| Design | Project code `<FY>-3101` onwards per fixture line on order booking, 22 design stages, the 24 planner activities as tasks, daily work sheet as timesheets, BOM pending and PO pending flags. |
| BOM | GBB columns on BOM lines (grade, shape, finish size, auto RM size using the same rule as `computeRMSize`, RM weight from density, Std, Critical spare, RM available). One button builds every part's own BOM (RM in kg) and machining route from the part category. BOM revisions create a Design Change Record that lists every part added, removed or changed, the quantity already on PO or in production, and the purchase action needed. |
| Checklists | ISO formats loaded verbatim from the current ERP: Fixture Design (105 points), Cradle Design (36), Internal Review, Packaging (12), Final Inspection for Fixture, Casting Base, Cradle and Tailstock with nominal and tolerance, JH Daily Check (11), Exit Clearance, Vendor Assessment. |
| Registers | Design Change Records, Lessons Learnt, Job Rejection (on Odoo scrap), Tool Breakage, Instruments and Calibration with acceptance criteria, Security In / Out with "post to attendance", Accident / Incident, Employee Advances. |
| Demo data | **GBB ERP > Tools > Load / Remove Demo Data**. Loads about 6,000 linked records; removal deletes exactly those rows and restores company details and numbering. |

## Deploy on Odoo.sh

1. Push this repository to the GitHub repository linked to the Odoo.sh project (or add it as a submodule). The module folder `gbb_erp` must sit at the repository root.
2. Odoo.sh builds the branch. Open the **staging** branch database.
3. Apps > Update Apps List > search **GBB Industries ERP on Odoo** > Install. Dependencies (CRM, Sales, Purchase, Inventory, Manufacturing, Project, Timesheets, Employees, Time Off, Attendances, Maintenance, Surveys, Indian accounting) install automatically.
4. Open **GBB ERP > Tools > Load / Remove Demo Data** and press **Load Demo Data** (about one to two minutes).
5. To reset before or after a demo, press **Remove Demo Data**, then load again.

Command line alternative on the Odoo.sh shell:

```bash
odoo-bin -d <staging-db-name> -i gbb_erp --stop-after-init
```

## Demo logins

All demo users use the password `gbb@demo`.

| Login | Role in the demo |
|---|---|
| `girish@gbb.demo` | Director: approves quotations, sees everything |
| `arun@gbb.demo` | Sales: inquiries, quotations, orders |
| `sachin@gbb.demo`, `vishal@gbb.demo` | Service: complaints |
| `sandip@gbb.demo`, `netaji@gbb.demo`, `rushikesh@gbb.demo` | Design: projects, checklists, BOMs |
| `stores@gbb.demo` | Purchase and stores |
| `planning@gbb.demo` | Planning, production, maintenance |
| `quality@gbb.demo` | Quality |
| `accounts@gbb.demo` | Accounts and confidential HR |
| `security@gbb.demo` | Security register |

## Notes

* Tested on Odoo 19.0 (Community core) with Indian localisation: install, load, remove (database row counts back to the starting point), load again; all 77 GBB ERP menus opened without errors as admin and as the sales, design, stores, planning, accounts and security users. On Odoo.sh (Enterprise) the same module runs unchanged; Enterprise adds Shop Floor tablets, Quality, PLM (ECO), Payroll, GST return reports and full financial reports on top.
* Vendors marked `[demo]`, material rates per kg and machine hour rates are demo values.
* Removal keeps two settings switched on: Work Orders and Storage Locations.
* Load the demo on a staging or demo database, never on production.
