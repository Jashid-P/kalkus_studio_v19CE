# Community Payroll Accounting (`jkm_hr_payroll_account`)

Accounting bridge for `jkm_hr_payroll`, modelled on Odoo Enterprise *Payroll Accounting*.
Installs automatically when both Payroll and Invoicing/Accounting are installed.

## What happens

* **Validate** a payslip → a **draft journal entry** is created in the structure's
  *Salary Journal*, dated at the end of the payslip month (or the payslip *Accounting Date*).
* Each salary rule books its total on its **Debit Account** and/or **Credit Account**.
  Positive amounts are debited on the debit account and credited on the credit account;
  negative amounts (deductions) do the opposite.
* Any difference between debits and credits goes to an *Adjustment Entry* line on the
  journal's default account.
* **Refund** → validating the refund creates the reverse entry.
* **Set to Draft / Cancel** → a draft entry is deleted, a posted entry is reversed.
* **Register Payment** (after posting the entry) pays the net salary to the employee;
  once it is reconciled the payslip becomes **Paid** automatically.

## Configured on install (per company with a chart of accounts)

* A *Salaries* journal (code `SLR`) set on the salary structures.
* Default accounts on the default rules, found by name in your chart (created if missing):

| Rule | Account |
|---|---|
| Basic Salary, Reimbursement | debit: Salary Expense |
| Bonus | debit: Bonus expense (or Salary Expense) |
| Deduction, Attachment/Assignment of Salary, Child Support | debit (booked as credit): salaries payable / deductions payable |
| Salary Advance / Loan | debit (booked as credit): Advance to Employee |
| Net Salary | credit: Salaries Payable (reconcilable), employee as partner |

Check them in *Payroll → Configuration → Rules → Accounting* tab.

## Options

* *Invoicing/Accounting Settings → Payroll → Batch Payroll Move Lines*: one entry per batch
  and period, with merged (anonymous) journal items. Created once all the batch payslips are validated.
* On rules: *Set employee on account line*, *Split on names*, *Excluded from Net*,
  analytic distribution, tax grids. Contracts can carry an analytic distribution too
  (used before the rule's one on expense/income lines).
