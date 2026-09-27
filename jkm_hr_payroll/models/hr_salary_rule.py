# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class HrSalaryRule(models.Model):
    _name = 'hr.salary.rule'
    _description = 'Salary Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True, index=True,
        help="Careful, the code is used in many references, changing it could lead to unwanted changes.")
    struct_id = fields.Many2one(
        'hr.payroll.structure', string="Salary Structure", required=True, index=True, ondelete='cascade')
    country_id = fields.Many2one(related='struct_id.country_id')
    sequence = fields.Integer(
        required=True, index=True, default=5,
        help='Use to arrange calculation sequence')
    quantity = fields.Char(
        default='1.0',
        help="It is used in computation for percentage and fixed amount. "
             "E.g. a rule for Meal Voucher having fixed amount of 1€ per worked day can have "
             "its quantity defined in expression like worked_days['WORK100'].number_of_days.")
    category_id = fields.Many2one(
        'hr.salary.rule.category', string='Category', required=True,
        domain="['|', ('country_id', '=', False), ('country_id', '=', country_id)]")
    active = fields.Boolean(
        default=True,
        help="If the active field is set to false, it will allow you to hide the salary rule without removing it.")
    appears_on_payslip = fields.Boolean(
        string='Appears on Payslip', default=True,
        help="Used to display the salary rule on payslip.")
    appears_on_employee_cost_dashboard = fields.Boolean(
        string='Contributes to Employer Cost', default=False,
        help="Used to compute the employer cost of a payslip.")
    condition_select = fields.Selection([
        ('none', 'Always True'),
        ('input', 'Other Input'),
        ('range', 'Range'),
        ('python', 'Python Expression'),
    ], string="Condition Based on", default='none', required=True)
    condition_other_input_id = fields.Many2one(
        'hr.payslip.input.type', string="Condition Input",
        help="The rule applies only if the payslip contains an input of this type.")
    condition_range = fields.Char(
        string='Range Based on', default='version.wage',
        help='This will be used to compute the % fields values; in general it is on basic, '
             'but you can also use categories code fields in lowercase as a variable names '
             '(hra, ma, lta, etc.) and the variable basic.')
    condition_range_min = fields.Float(string='Minimum Range', help="The minimum amount, applied for this rule.")
    condition_range_max = fields.Float(string='Maximum Range', help="The maximum amount, applied for this rule.")
    condition_python = fields.Text(
        string='Python Condition', required=True,
        default="""
# Available variables:
#----------------------
# payslip: hr.payslip object
# employee: hr.employee object
# version: hr.version object (alias: contract)
# rules: dict containing the rules code (previously computed)
# categories: dict containing the computed salary rule categories
#             (sum of amount of all rules belonging to that category).
# worked_days: dict containing the computed worked days
# inputs: dict containing the computed inputs.

# Note: returned value have to be set in the variable 'result'

result = rules['NET']['total'] > categories['NET'] * 0.10""",
        help='Applied this rule for calculation if condition is true. You can specify condition like basic > 1000.')
    amount_select = fields.Selection([
        ('percentage', 'Percentage (%)'),
        ('fix', 'Fixed Amount'),
        ('input', 'Other Input'),
        ('code', 'Python Code'),
    ], string='Amount Type', index=True, required=True, default='fix',
        help="The computation method for the rule amount.")
    amount_fix = fields.Float(string='Fixed Amount', digits='Payroll')
    amount_percentage = fields.Float(
        string='Percentage (%)', digits='Payroll Rate',
        help='For example, enter 50.0 to apply a percentage of 50%')
    amount_other_input_id = fields.Many2one('hr.payslip.input.type', string="Amount Input")
    amount_python_compute = fields.Text(
        string='Python Code',
        default="""
# Available variables:
#----------------------
# payslip: hr.payslip object
# employee: hr.employee object
# version: hr.version object (alias: contract)
# rules: dict containing the rules code (previously computed)
# categories: dict containing the computed salary rule categories
#             (sum of amount of all rules belonging to that category).
# worked_days: dict containing the computed worked days
# inputs: dict containing the computed inputs.

# Note: returned value have to be set in the variable 'result'

result = version.wage * 0.10""")
    amount_percentage_base = fields.Char(
        string='Percentage based on', help='result will be affected to a variable')
    partner_id = fields.Many2one(
        'res.partner', string='Partner',
        help="Eventual third party involved in the salary payment of the employees.")
    note = fields.Html(string='Description', translate=True)

    def _raise_error(self, localdict, error_type, e):
        raise UserError(self.env._(
            "%(error_type)s\n"
            "- Employee: %(employee)s\n"
            "- Contract: %(contract)s\n"
            "- Payslip: %(payslip)s\n"
            "- Salary rule: %(name)s (%(code)s)\n"
            "- Error: %(error_message)s",
            error_type=error_type,
            employee=localdict['employee'].name,
            contract=localdict['version'].display_name,
            payslip=localdict['payslip'].name,
            name=self.name,
            code=self.code,
            error_message=e,
        ))

    def _compute_rule(self, localdict):
        """Return ``(amount, quantity, rate)`` for this rule."""
        self.ensure_one()
        localdict['localdict'] = localdict
        if self.amount_select == 'fix':
            try:
                return self.amount_fix or 0.0, float(safe_eval(self.quantity or '1.0', localdict)), 100.0
            except Exception as e:  # noqa: BLE001
                self._raise_error(localdict, self.env._("Wrong quantity defined for:"), e)
        if self.amount_select == 'percentage':
            try:
                return (
                    float(safe_eval(self.amount_percentage_base or '0.0', localdict)),
                    float(safe_eval(self.quantity or '1.0', localdict)),
                    self.amount_percentage or 0.0,
                )
            except Exception as e:  # noqa: BLE001
                self._raise_error(localdict, self.env._("Wrong percentage base or quantity defined for:"), e)
        if self.amount_select == 'input':
            code = self.amount_other_input_id.code
            if code not in localdict['inputs']:
                return 0.0, 1.0, 100.0
            return localdict['inputs'][code].amount, 1.0, 100.0
        # Python code
        try:
            safe_eval(self.amount_python_compute or '0.0', localdict, mode='exec')
            return (
                float(localdict['result'] or 0.0),
                float(localdict.get('result_qty', 1.0)),
                float(localdict.get('result_rate', 100.0)),
            )
        except Exception as e:  # noqa: BLE001
            self._raise_error(localdict, self.env._("Wrong python code defined for:"), e)

    def _satisfy_condition(self, localdict):
        self.ensure_one()
        localdict['localdict'] = localdict
        if self.condition_select == 'none':
            return True
        if self.condition_select == 'input':
            return self.condition_other_input_id.code in localdict['inputs']
        if self.condition_select == 'range':
            try:
                result = safe_eval(self.condition_range or '0.0', localdict)
                return self.condition_range_min <= result <= self.condition_range_max
            except Exception as e:  # noqa: BLE001
                self._raise_error(localdict, self.env._("Wrong range condition defined for:"), e)
        # Python expression
        try:
            safe_eval(self.condition_python, localdict, mode='exec')
            return bool(localdict.get('result'))
        except Exception as e:  # noqa: BLE001
            self._raise_error(localdict, self.env._("Wrong python condition defined for:"), e)
