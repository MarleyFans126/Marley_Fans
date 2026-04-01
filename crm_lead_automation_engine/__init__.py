from . import models


def _post_init_update_acknowledgment_template(env):
    """
    Replace the default acknowledgment email template with the Marley
    Enterprises introduction email and attach the two PDF brochures.
    Delegates to the init() logic on crm.lead for fresh installs where
    init() may have run before XML data was loaded.
    """
    env['crm.lead'].init()
