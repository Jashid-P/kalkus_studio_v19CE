# -*- coding: utf-8 -*-
{
    'name': 'Theme Web Responsive',
    'summary': 'Enterprise-style responsive Odoo 19 web interface',
    'description': '''
Responsive Community web client for Odoo 19.

Provides an Enterprise-style application launcher, responsive navbar,
light/dark theme variables, mobile navigation, and a responsive home screen.
''',
    'author': 'Kalkus Studio',
    'category': 'Hidden',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['web', 'base_setup'],
    'data': [
        'views/webclient_templates.xml',
        'views/res_users_views.xml',
    ],
    'assets': {
        # --------------------------------------------------------------------
        # VARIABLES / HELPERS
        # --------------------------------------------------------------------
        'web._assets_primary_variables': [
            # Component-scoped variables go *after* web's primary_variables so
            # they can build on web's own variables ($o-main-text-color, ...),
            # while still landing before web's `**/*.variables.scss` glob so
            # our declarations win over web's `!default` ones.
            ('after', 'web/static/src/scss/primary_variables.scss',
             'jkm_web_resposive/static/src/**/*.variables.scss'),
            ('before', 'web/static/src/scss/primary_variables.scss',
             'jkm_web_resposive/static/src/scss/primary_variables.scss'),
        ],
        'web._assets_secondary_variables': [
            ('before', 'web/static/src/scss/secondary_variables.scss',
             'jkm_web_resposive/static/src/scss/secondary_variables.scss'),
        ],
        'web._assets_backend_helpers': [
            ('before', 'web/static/src/scss/bootstrap_overridden.scss',
             'jkm_web_resposive/static/src/scss/bootstrap_overridden.scss'),
        ],

        # --------------------------------------------------------------------
        # LIGHT MODE
        # --------------------------------------------------------------------
        'web.assets_frontend': [
            # home_menu_background is shared with the login page
            'jkm_web_resposive/static/src/webclient/home_menu/home_menu_background.scss',
            'jkm_web_resposive/static/src/webclient/navbar/navbar.scss',
        ],
        'web.assets_backend': [
            'jkm_web_resposive/static/src/scss/**/*.scss',
            'jkm_web_resposive/static/src/core/**/*.scss',
            'jkm_web_resposive/static/src/webclient/**/*.scss',
            'jkm_web_resposive/static/src/webclient/**/*.js',
            'jkm_web_resposive/static/src/webclient/**/*.xml',

            # Don't include dark mode files in light mode. Without this the
            # dark overrides are served unconditionally and the home menu gets
            # a dark ground while the captions keep their light-mode color.
            ('remove', 'jkm_web_resposive/static/src/**/*.dark.scss'),
        ],
        'web.assets_web': [
            ('replace', 'web/static/src/main.js',
             'jkm_web_resposive/static/src/main.js'),
        ],

        # --------------------------------------------------------------------
        # DARK MODE
        # --------------------------------------------------------------------
        # Odoo 19 has no `.o_dark` body class: dark mode is an entirely
        # separate compiled bundle, selected server-side from the user's
        # color_scheme. So dark styling is done by re-declaring variables
        # ahead of their light counterparts, never by a scoped selector.
        'web.dark_mode_variables': [
            # web._assets_primary_variables
            ('before', 'jkm_web_resposive/static/src/scss/primary_variables.scss',
             'jkm_web_resposive/static/src/scss/primary_variables.dark.scss'),
            ('before', 'jkm_web_resposive/static/src/**/*.variables.scss',
             'jkm_web_resposive/static/src/**/*.variables.dark.scss'),
            # web._assets_secondary_variables
            ('before', 'jkm_web_resposive/static/src/scss/secondary_variables.scss',
             'jkm_web_resposive/static/src/scss/secondary_variables.dark.scss'),
        ],
        'web.assets_web_dark': [
            ('include', 'web.dark_mode_variables'),
            # web._assets_backend_helpers
            ('before', 'jkm_web_resposive/static/src/scss/bootstrap_overridden.scss',
             'jkm_web_resposive/static/src/scss/bootstrap_overridden.dark.scss'),
            ('after', 'web/static/lib/bootstrap/scss/_functions.scss',
             'jkm_web_resposive/static/src/scss/bs_functions_overridden.dark.scss'),
            # web.assets_backend
            # `*.variables.dark.scss` are already in the list via
            # `web.dark_mode_variables` above; AssetPaths dedupes by path, so
            # this glob only picks up the component dark styles.
            'jkm_web_resposive/static/src/**/*.dark.scss',
        ],
        # Lazy views (graph, pivot) compile in their own bundle and would
        # otherwise stay light-themed.
        'web.assets_backend_lazy_dark': [
            ('include', 'web.dark_mode_variables'),
            ('before', 'jkm_web_resposive/static/src/scss/bootstrap_overridden.scss',
             'jkm_web_resposive/static/src/scss/bootstrap_overridden.dark.scss'),
            ('after', 'web/static/lib/bootstrap/scss/_functions.scss',
             'jkm_web_resposive/static/src/scss/bs_functions_overridden.dark.scss'),
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
