{
    'name': 'GBB Industries ERP on Odoo',
    'version': '19.0.1.0.0',
    'summary': 'Every GBB ERP screen mapped to Odoo 19, with GBB registers, '
               'checklists, BOM revision control and a load/unload demo data set',
    'description': """
GBB Industries: in-house ERP to Odoo 19
=======================================
* GBB ERP menu that mirrors the existing sidebar (Sales, Design & Engineering,
  Purchase & Stores, Operations, Analytics, Accounts, HR & People, Security, Master)
* Inquiry numbering E-n per financial year, quotation numbers GBB/SQ/<FY>/<E-no>,
  project codes <FY>-3101 onwards
* Quotation cost breakup (confidential) with Director approval
* Fixture BOM with material grade, shape, finish size, auto raw-material size,
  standard / critical-spare flags and BOM revisions with Design Change Records
* ISO checklists: Inquiry Review, Order Review, Fixture Design (105 points),
  Cradle Design (36 points), Internal Review, Packaging, Final Inspection,
  JH Daily Check, Exit Clearance
* Registers: Lessons Learnt, Tool Breakage, Job Rejection, Advances,
  Security In/Out, Accident / Incident
* Demo data wizard: load and fully remove GBB demo data in one click
""",
    'author': 'Ochre Digital',
    'website': 'https://ochre.digital',
    'category': 'Manufacturing',
    'license': 'LGPL-3',
    'depends': [
        'crm',
        'sale_management',
        'sale_crm',
        'sale_mrp',
        'sale_project',
        'purchase',
        'purchase_mrp',
        'mrp',
        'stock',
        'project',
        'project_mrp',
        'project_stock',
        'project_purchase',
        'hr',
        'hr_timesheet',
        'hr_skills',
        'hr_holidays',
        'hr_attendance',
        'hr_maintenance',
        'maintenance',
        'survey',
        'l10n_in',
    ],
    'data': [
        'security/gbb_security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/master_data.xml',
        'data/checklist_templates.xml',
        'views/master_views.xml',
        'views/crm_views.xml',
        'views/sale_views.xml',
        'views/project_views.xml',
        'views/mrp_views.xml',
        'views/purchase_stock_views.xml',
        'views/checklist_views.xml',
        'views/register_views.xml',
        'views/hr_views.xml',
        'report/gbb_reports.xml',
        'wizard/demo_loader_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
