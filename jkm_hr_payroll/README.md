# Community Payroll (`jkm_hr_payroll`)

Enterprise-style payroll for **Odoo 19 Community**. It uses the same model names and
salary-rule evaluation context as Odoo Enterprise Payroll, so rules can be ported unchanged.
Depends only on Community modules (`hr_work_entry_holidays`, `mail`).

## Quick start

1. **Access rights**: *Settings → Users*, give the user *Payroll: Officer* or *Administrator*.
2. **Contract**: on the employee (*Payroll* tab) set the contract start date, the wage and a
   *Pay Category* (salary structure type). *Employee* uses the **Regular Pay** structure
   (fixed monthly wage); *Worker* uses **Worker Pay** (hourly wage).
3. **Payslip**: *Payroll → Payslips → All Payslips → New*, pick the employee:
   the period, contract, structure and worked days are filled in automatically.
   Click **Compute Sheet**, then **Validate**, then **Mark as Paid**.
4. **Batch**: *Payroll → Payslips → Batches → New*, set the period, save, click
   **Generate Payslips**, select the employees, then **Validate** and **Mark as Paid**.

## How the salary is computed

* **Worked days** come from the work entries of the period (generated from the working
  schedule and approved time off). Types listed in *Unpaid Work Entry Types* on the
  structure are unpaid; days outside the contract appear as *Out of Contract* (unpaid).
* **Fixed wage**: each paid line is worth `wage × hours / period hours × rate`.
  **Hourly wage**: `hourly wage × hours × rate`.
* **Basic** = paid worked days (`payslip.paid_amount`), **Gross** = Basic + Allowances,
  **Net** = Basic + Allowances + Deductions.

## Other inputs and salary attachments

* Add *Other Inputs* on a draft payslip: **Bonus** (allowance), **Deduction**,
  **Reimbursement** (added to net, outside gross).
* *Payroll → Employees → Salary Attachments*: garnishments, assignments, child support
  or loans. The payslip amount is deducted from each payslip until the total is paid,
  then the attachment is completed automatically.

## Writing salary rules

*Payroll → Configuration → Rules*. Available in Python code:

| Variable | Content |
|---|---|
| `payslip` | the payslip (`paid_amount`, `date_from`, `_rule_parameter('CODE')`, `_sum('CODE', from, to)`, `_sum_category(...)`) |
| `employee`, `version` (alias `contract`) | employee and contract (`version.wage`, `version.hourly_wage`) |
| `categories['BASIC']` / `categories.BASIC` | total of a category so far |
| `rules['NET']['total']` (alias `result_rules`) | a previously computed rule |
| `worked_days['WORK100'].number_of_days` | worked days line |
| `inputs['BONUS'].amount` | sum of the inputs with that code |

Set `result` (and optionally `result_qty`, `result_rate`, `result_name`).
Dated values (tax rates, ceilings...) go in *Configuration → Rule Parameters* and are read
with `payslip._rule_parameter('code')`.

## Refunds

On a validated payslip click **Refund**: a credit-note payslip with all amounts reversed
is created; validate it to cancel the original pay.

## Not included (yet)

Accounting entries (journal posting), the payroll dashboard, localisation packages
(country-specific tax/social security rules) and bank payment files.
