"""The one place this addon is allowed to talk to the catalogue service.

Read-only by construction: the client exposes GET and nothing else. The master
catalogue is cross-tenant reference data, and a tenant that could write to it
could change what every other tenant sees.
"""

import logging

import requests

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

TIMEOUT = 30


class MbCatalogueClient(models.AbstractModel):
    _name = "mb.catalogue.client"
    _description = "Master catalogue HTTP client (read-only)"

    @api.model
    def _get(self, service, path, params=None):
        """One GET against the catalogue service, returning decoded JSON.

        Raises UserError rather than letting a requests exception escape: this
        is called from buttons, and a connection error to a service the artisan
        has never heard of should read as "the catalogue is unreachable".
        """
        url = f"{service.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Accept": "application/json"}
        if service.api_key:
            headers["Authorization"] = f"Bearer {service.api_key}"
        try:
            response = requests.get(url, params=params or {}, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as error:
            raise UserError(_("The catalogue service did not answer in time.")) from error
        except requests.exceptions.RequestException as error:
            _logger.warning(
                "catalogue GET %s failed: %s", url, error
            )
            raise UserError(_("The catalogue service is unreachable.")) from error
        except ValueError as error:
            raise UserError(_("The catalogue service returned a malformed response.")) from error
