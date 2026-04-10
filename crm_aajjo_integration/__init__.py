from . import controllers
from . import models


def _reactivate_aajjo_settings_view(env):
    """Post-init hook: ensure the AAJJO settings view is active.

    The crm_lead_automation_engine init() method may have previously
    deactivated this view. Re-enable it on module install/upgrade.
    """
    view = env.ref('crm_aajjo_integration.res_config_settings_view_form', raise_if_not_found=False)
    if view and not view.active:
        view.active = True
