import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .mykiln_client import (
    MykilnAuthError,
    MykilnClient,
    MykilnError,
    as_number,
    as_str,
    nested_id,
    parse_instant,
)
from .mykiln_normalize import normalize_firing, normalize_kilns, normalize_program

_logger = logging.getLogger(__name__)


def _kiln_external(record):
    """The kiln a firing belongs to, as the string `mb.kiln` is keyed on."""
    identifier = nested_id(record or {}, "kiln")
    return str(int(identifier)) if identifier is not None else "0"


def _newest_programs(observations):
    """One programme per (kiln, controller slot): the most recently fired.

    myKiln keeps a programme snapshot per firing rather than a library, so the
    same slot appears once per firing that ran it - and the profiles genuinely
    differ, because a potter edits a programme in place. The newest is the
    current one. Anything older is history, and history must not win: a
    backfill walks the archive and would otherwise leave every programme
    showing the oldest profile it ever had.
    """
    newest = {}
    for kiln_external, detail in observations:
        payload = normalize_program(detail)
        if not payload:
            continue
        key = (kiln_external, payload["program_number"])
        held = newest.get(key)
        if held is None:
            newest[key] = payload
            continue
        if payload["fired_at"] and (not held["fired_at"] or payload["fired_at"] > held["fired_at"]):
            newest[key] = payload
    return newest


class MbKilnConnection(models.Model):
    """One workshop's connection, credentials, and sync state for a provider."""

    _name = "mb.kiln.connection"
    _description = "Kiln provider connection"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True, default="myKiln")
    provider = fields.Selection(
        selection=[("rohde_mykiln", "ROHDE myKiln")], required=True, default="rohde_mykiln"
    )
    base_url = fields.Char(required=True, default="https://mykiln.eu")
    username = fields.Char(required=True)
    password = fields.Char(
        # Odoo has no secret store, so this is a column like any other. It is
        # never logged or exported; it is sent only to the provider's
        # authentication endpoint. It
        # is restricted to the manager group in ir.model.access. If this
        # product goes multi-tenant, the credential moves to the connected
        # account gateway and this field goes away.
        groups="mrp.group_mrp_manager",
        help="Stored in this database. Restricted to manufacturing managers.",
    )
    provider_token = fields.Char(
        # myKiln issues reusable Django REST Framework tokens, so the cron keeps
        # the token instead of logging in on every wake. It has the same group
        # restriction as the password, is never logged, and is cleared whenever
        # the provider refuses it.
        groups="mrp.group_mrp_manager",
        copy=False,
        readonly=True,
    )
    provider_token_at = fields.Datetime(readonly=True, copy=False)

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company", required=True, index=True, default=lambda self: self.env.company
    )

    state = fields.Selection(
        selection=[("draft", "Never connected"), ("ok", "Connected"), ("error", "Failing")],
        default="draft",
        readonly=True,
    )
    last_sync = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    firing_limit = fields.Integer(
        default=5,
        required=True,
        help="How many recent firings the routine poll pulls. Small on "
        "purpose: history is the backfill's job, not the cron's.",
    )
    timeout = fields.Integer(
        default=120,
        required=True,
        help="Seconds to wait on one provider call. Measured against myKiln, "
        "a listing of fifty firings took twenty-two seconds and was "
        "slower than one of two hundred, so this is generous by design.",
    )

    backfill_state = fields.Selection(
        selection=[("idle", "Not started"), ("running", "Running"), ("done", "Complete")],
        default="idle",
        required=True,
        readonly=True,
    )
    backfill_offset = fields.Integer(readonly=True)
    backfill_total = fields.Integer(readonly=True)
    sync_programs = fields.Boolean(
        string="Refresh programmes",
        default=True,
        help="Keep each kiln's programmes in step with the controller as "
        "firings come in. The provider has no programme library to read, "
        "so a programme is learned from the firings that ran it - which "
        "means this costs nothing beyond the firings already imported.",
    )
    program_scan_limit = fields.Integer(
        default=50,
        required=True,
        help="How many recent firings the Refresh programmes button looks "
        "through to find each controller slot. Only the newest firing per "
        "slot is fetched in full, so this is one listing call plus one "
        "call per programme found.",
    )
    program_count = fields.Integer(compute="_compute_counts")

    store_raw_payload = fields.Boolean(
        string="Keep provider payload",
        default=True,
        help="Attach the provider's own JSON to each firing. Roughly 82 KB "
        "each, so about 6 MB for a full myKiln history. Worth it while "
        "the integration is young; switch it off once the normalized "
        "fields are trusted.",
    )
    backfill_page_size = fields.Integer(
        default=10,
        required=True,
        help="Firings listed per provider call during backfill. Kept small "
        "because the listing endpoint degrades badly with page size, "
        "while fetching each firing's detail and samples is cheap.",
    )
    backfill_progress = fields.Float(compute="_compute_backfill_progress", string="Backfill %")

    kiln_ids = fields.One2many(comodel_name="mb.kiln", inverse_name="connection_id", readonly=True)
    kiln_count = fields.Integer(compute="_compute_counts")
    firing_count = fields.Integer(compute="_compute_counts")

    @api.depends("backfill_offset", "backfill_total")
    def _compute_backfill_progress(self):
        for connection in self:
            total = connection.backfill_total
            connection.backfill_progress = (
                (100.0 * connection.backfill_offset / total) if total else 0.0
            )

    @api.depends(
        "kiln_ids",
        "kiln_ids.active",
        "kiln_ids.firing_ids",
        "kiln_ids.program_ids",
        "kiln_ids.program_ids.active",
    )
    def _compute_counts(self):
        # Two aggregates over every connection's kilns at once, rather than two
        # search_count per connection.
        kilns = self.kiln_ids
        firings = dict(
            self.env["mb.firing"]._read_group(
                [("kiln_id", "in", kilns.ids)], groupby=["kiln_id"], aggregates=["__count"]
            )
        )
        programs = dict(
            self.env["mb.kiln.program"]._read_group(
                [("kiln_id", "in", kilns.ids)], groupby=["kiln_id"], aggregates=["__count"]
            )
        )
        for connection in self:
            connection_kilns = connection.kiln_ids
            connection.kiln_count = len(connection_kilns)
            connection.firing_count = sum(firings.get(kiln, 0) for kiln in connection_kilns)
            connection.program_count = sum(programs.get(kiln, 0) for kiln in connection_kilns)

    # -- provider access ---------------------------------------------------

    def _client(self):
        self.ensure_one()
        record = self.sudo()
        if not record.password:
            raise UserError(_("%s has no password set.", self.display_name))
        return MykilnClient(
            record.username,
            record.password,
            record.base_url,
            timeout=record.timeout or 120,
            token=record.provider_token or None,
        )

    def _remember_token(self, client):
        """Persist a token the client had to fetch. A no-op when it reused one."""
        self.ensure_one()
        if client.token_changed and client.token:
            self.sudo().write(
                {
                    "provider_token": client.token,
                    "provider_token_at": fields.Datetime.now(),
                }
            )

    def _forget_token(self):
        """Drop a token the provider no longer accepts, so the next run logs in."""
        self.ensure_one()
        self.sudo().write({"provider_token": False, "provider_token_at": False})

    def action_test_connection(self):
        self.ensure_one()
        client = self._client()
        try:
            # Test always proves the credential, never the cached token.
            self._forget_token()
            client = self._client()
            client.login()
            self._remember_token(client)
        except MykilnError as error:
            self.write({"state": "error", "last_error": str(error)})
            raise UserError(_("Connection failed: %s", error)) from error
        self.write({"state": "ok", "last_error": False})
        return True

    # -- sync --------------------------------------------------------------

    def action_sync(self):
        """Manual poll. Records provider trouble instead of raising a traceback.

        The error state is written on a separate cursor because the exception
        rolls this transaction back - which is how the first live attempt lost
        its own failure record and surfaced a bare ReadTimeout instead.
        """
        failures = []
        for connection in self:
            try:
                connection._sync_one()
            except MykilnError as error:
                # Recorded, not raised. Raising would roll the write back and
                # hand the user a traceback, which is how the first live
                # attempt lost its own failure record.
                connection.write({"state": "error", "last_error": str(error)})
                failures.append("%s: %s" % (connection.display_name, error))
        if failures:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "title": _("myKiln did not answer"),
                    "message": "\n".join(failures),
                    "sticky": True,
                },
            }
        return True

    def _describe_kilns(self, client):
        """Kilns joined to live readings, and to the model catalogue if needed.

        The catalogue is three hundred rows describing every kiln ROHDE sells,
        so it is fetched only when it could tell us something: a kiln that
        reports a model we have not looked up yet, or one whose model has
        changed. A kiln whose owner never entered a model reports none, and no
        amount of catalogue will help - so it does not provoke the call every
        time the cron wakes.
        """
        self.ensure_one()
        raw_kilns = client.list_kilns()
        controllers = client.list_controllers()
        known = {kiln.provider_external_id: kiln for kiln in self.kiln_ids}
        wanted = False
        for raw in raw_kilns:
            identifier = as_number(raw.get("id"))
            model = as_str(raw.get("model_number")).strip()
            if identifier is None or not model:
                continue
            kiln = known.get(str(int(identifier)))
            if not kiln or not kiln.series or kiln.model_number != model:
                wanted = True
                break
        kiln_types = client.list_kiln_types() if wanted else None
        return normalize_kilns(raw_kilns, controllers, kiln_types)

    def _sync_one(self):
        self.ensure_one()
        try:
            client = self._client()
            kilns = self._describe_kilns(client)
            applied_kilns = self._apply_kilns(kilns)

            summaries = client.list_firings(limit=self.firing_limit, offset=0)
            self._import_firings(client, summaries, kilns, applied_kilns)
            self._remember_token(client)
        except MykilnAuthError as error:
            # Do not retry. Repeated authentication failure is an unhealthy
            # connection that a person has to look at, not a transient fault.
            # The stored token goes: it is the most likely thing to be stale.
            self._forget_token()
            self.write({"state": "error", "last_error": str(error)})
            _logger.warning("kiln connection %s: authentication failed", self.id)
            raise
        except MykilnError as error:
            self.write({"state": "error", "last_error": str(error)})
            _logger.warning("kiln connection %s: %s", self.id, error)
            raise
        self.write({"state": "ok", "last_error": False, "last_sync": fields.Datetime.now()})

    def _import_firings(self, client, summaries, kiln_payloads, applied_kilns):
        """Fetch and apply each listed firing. Returns how many were written.

        Programmes are applied first, from the same details, and that ordering
        is the point rather than an accident: `_apply_firing` links a firing to
        its programme by asking for a match, so a programme discovered in this
        very batch has to exist before the firing that revealed it is written.
        Applying them afterwards would leave the first sync's firings unlinked
        until something touched them again.
        """
        self.ensure_one()
        units = {k["external_id"]: k["units"] for k in kiln_payloads}
        states = {k["external_id"]: k["state"] for k in kiln_payloads}

        fetched = []
        for summary in summaries:
            firing_id = summary.get("id")
            if firing_id is None:
                continue
            detail = client.get_firing(firing_id)
            samples = client.get_firing_samples(firing_id)
            fetched.append((_kiln_external(detail), detail, samples))

        if self.sync_programs:
            self._apply_programs(
                _newest_programs(
                    (kiln_external, detail) for kiln_external, detail, _samples in fetched
                ),
                applied_kilns,
            )

        written = 0
        for kiln_external, detail, samples in fetched:
            payload = normalize_firing(
                detail, samples, units.get(kiln_external, "Celsius"), states.get(kiln_external)
            )
            if payload and self._apply_firing(payload, applied_kilns):
                written += 1
        return written

    def _apply_programs(self, programs, kilns):
        """Upsert one programme per (kiln, controller slot). Returns them.

        A programme whose kiln was not imported is skipped for the same reason
        a firing is: an implicit kiln would have no work centre and no name a
        person chose.
        """
        self.ensure_one()
        Program = self.env["mb.kiln.program"]
        applied = Program.browse()
        for (kiln_external, _number), payload in sorted(programs.items()):
            kiln = kilns.get(kiln_external)
            if not kiln:
                _logger.info(
                    "skipping programme %s: kiln %s not imported",
                    payload.get("name"),
                    kiln_external,
                )
                continue
            applied |= Program._apply_provider(kiln, payload)
        return applied

    def _apply_kilns(self, payloads):
        """Upsert on (provider, external id, company). Returns them by external id.

        The specification is written on every sync, and unlike the name it is
        not the potter's to keep. Manufacturer, model, chamber volume and
        maximum temperature describe the machine, and the machine is what the
        provider is reporting - a chamber does not become larger because
        someone typed a different number here. Everything the workshop decides
        - the name, how many pieces fit a load, which work centre it is - is
        left alone.

        A field the provider does not report is not written at all, rather than
        written as empty. A myKiln account with the volume left blank should
        not wipe a figure the potter measured with a bucket.
        """
        self.ensure_one()
        Kiln = self.env["mb.kiln"]
        found = {}
        for payload in payloads:
            external_id = payload["external_id"]
            kiln = Kiln.search(
                [
                    ("provider", "=", self.provider),
                    ("provider_external_id", "=", external_id),
                    ("company_id", "=", self.company_id.id),
                ],
                limit=1,
            )
            values = {
                "provider": self.provider,
                "provider_external_id": external_id,
                "connection_id": self.id,
                "company_id": self.company_id.id,
            }
            values.update(
                {
                    key: value
                    for key, value in (payload.get("specification") or {}).items()
                    if value is not None
                }
            )
            if kiln:
                # The name is set once. An artisan renames a kiln to what they
                # call it in the workshop, and a poll that renamed it back
                # would be a bug they cannot fix.
                kiln.write(values)
            else:
                values["name"] = payload["name"]
                kiln = Kiln.create(values)
            found[external_id] = kiln
        return found

    def _apply_firing(self, payload, kilns):
        """Idempotent on (provider, external id, company).

        Replaying the same firing updates the same record. A firing whose kiln
        is unknown is skipped rather than creating one implicitly: an implicit
        kiln would have no equipment, no work centre and no name a person chose.
        """
        self.ensure_one()
        kiln = kilns.get(payload["kiln_external_id"])
        if not kiln:
            _logger.info(
                "skipping firing %s: kiln %s not imported",
                payload["external_id"],
                payload["kiln_external_id"],
            )
            return self.env["mb.firing"]

        Firing = self.env["mb.firing"]
        firing = Firing.search(
            [
                ("provider", "=", self.provider),
                ("external_id", "=", payload["external_id"]),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        program = self.env["mb.kiln.program"]._match(
            kiln, payload["program"], payload.get("program_number")
        )
        values = {
            "kiln_id": kiln.id,
            "provider": self.provider,
            "external_id": payload["external_id"],
            "company_id": self.company_id.id,
            "date_start": payload["started_at"],
            "date_end": payload["ended_at"],
            "peak_temperature": payload["peak_temperature"] or 0.0,
            "program_name": payload["program"],
            "state": payload["state"],
        }
        if program:
            # The programme says what this firing was for and how long the
            # load has to stand before it can be opened. Without a mapping both
            # stay blank rather than being guessed from peak temperature.
            #
            # The link is kept as well as the label, and it points the other
            # way too: what a programme's firings actually took is how the
            # programme learns its own duration.
            values["program_id"] = program.id
            values["kind"] = program.kind
            reference = payload["ended_at"] or payload["last_sample_at"]
            if reference and program.cooling_hours:
                values["cooling_end"] = reference + timedelta(hours=program.cooling_hours)
        if firing:
            firing._mb_apply_provider_values(values)
        else:
            values["name"] = payload["title"] or "myKiln %s" % payload["external_id"]
            values.setdefault("kind", "other")
            firing = Firing.create(values)
        firing._attach_curve(payload["curve"], payload["external_id"])
        if self.store_raw_payload:
            firing._attach_raw(payload["raw"], payload["external_id"])
        return firing

    # -- programmes --------------------------------------------------------

    def action_refresh_programs(self):
        """Rebuild each kiln's programme list from the controller.

        Cheap, because it does not read every firing. The listing already
        carries the controller slot each firing ran on, so this asks for one
        page of firings, keeps the newest firing per slot, and fetches only
        those in full - three detail calls on the live account, not seventy-two.

        Sync does the same thing incrementally from firings it was importing
        anyway. This button is for the first run, and for after a potter has
        edited a programme on the controller and wants it here now.
        """
        found = 0
        for connection in self:
            try:
                found += connection._refresh_programs_one()
            except MykilnError as error:
                connection.write({"state": "error", "last_error": str(error)})
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "type": "danger",
                        "title": _("myKiln did not answer"),
                        "message": str(error),
                        "sticky": True,
                    },
                }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Programmes refreshed"),
                "message": _("%s programme(s) read from the controller.", found),
            },
        }

    def _refresh_programs_one(self):
        self.ensure_one()
        client = self._client()
        kilns = self._describe_kilns(client)
        applied_kilns = self._apply_kilns(kilns)

        summaries = client.list_firings(limit=self.program_scan_limit or 50, offset=0)
        candidates = {}
        for summary in summaries:
            number = as_number(summary.get("program_number"))
            firing_id = as_number(summary.get("id"))
            if number is None or firing_id is None:
                continue
            key = (_kiln_external(summary), int(number))
            started = parse_instant(summary.get("start_date_time"))
            held = candidates.get(key)
            if held is None or (started and (not held[1] or started > held[1])):
                candidates[key] = (int(firing_id), started)

        observations = []
        for kiln_external, _number in sorted(candidates):
            firing_id = candidates[(kiln_external, _number)][0]
            observations.append((kiln_external, client.get_firing(firing_id)))
        applied = self._apply_programs(_newest_programs(observations), applied_kilns)
        self._remember_token(client)
        return len(applied)

    # -- backfill ----------------------------------------------------------

    def action_start_backfill(self):
        """Arm a full history import.

        One shot from where you stand, resumable underneath. The provider holds
        seventy-two firings and each needs two calls, so the whole run is on
        the order of a minute - far too long for a button that blocks an RPC,
        and far too short to justify a job queue. So the button arms it and a
        cron chews through it in bounded slices, switching itself off at the
        end.
        """
        for connection in self:
            client = connection._client()
            connection.write(
                {
                    "backfill_state": "running",
                    "backfill_offset": 0,
                    "backfill_total": client.count_firings(),
                }
            )
        self.env.ref("mb_kiln_bridge.ir_cron_mb_kiln_backfill").sudo().write(
            {
                "active": True,
            }
        )
        return True

    def action_stop_backfill(self):
        self.write({"backfill_state": "idle"})
        return True

    def _backfill_slice(self):
        """Import pages while Odoo's cron budget says time remains."""
        self.ensure_one()
        with self.env.cr.savepoint():
            client = self._client()
            kilns = self._describe_kilns(client)
            applied_kilns = self._apply_kilns(kilns)

        while True:
            with self.env.cr.savepoint():
                summaries = client.list_firings(
                    limit=self.backfill_page_size, offset=self.backfill_offset
                )
                if not summaries:
                    self.backfill_state = "done"
                else:
                    self._import_firings(client, summaries, kilns, applied_kilns)
                    self.backfill_offset += len(summaries)
                    if self.backfill_total and self.backfill_offset >= self.backfill_total:
                        self.backfill_state = "done"
            if self.env.context.get("cron_id"):
                remaining = max(self.backfill_total - self.backfill_offset, 0)
                time_left = self.env["ir.cron"]._commit_progress(
                    processed=len(summaries), remaining=remaining
                )
                if not time_left:
                    break
            if self.backfill_state == "done":
                break
        self._remember_token(client)
        self.last_sync = fields.Datetime.now()
        return self.backfill_state

    @api.model
    def _cron_backfill(self):
        running = self.search([("backfill_state", "=", "running"), ("active", "=", True)])
        for connection in running:
            try:
                connection._backfill_slice()
            except Exception:
                _logger.exception("kiln backfill failed for connection %s", connection.id)
                connection.write(
                    {
                        "backfill_state": "idle",
                        "state": "error",
                        "last_error": "Backfill interrupted; see the log.",
                    }
                )
                self.env["ir.cron"]._commit_progress(processed=1)
        if not self.search_count([("backfill_state", "=", "running")]):
            self.env.ref("mb_kiln_bridge.ir_cron_mb_kiln_backfill").sudo().write({"active": False})
            self.env["ir.cron"]._commit_progress(remaining=0, deactivate=True)
        return True

    # -- cron --------------------------------------------------------------

    @api.model
    def _cron_sync(self):
        for connection in self.search([("active", "=", True), ("password", "!=", False)]):
            try:
                connection._sync_one()
            except Exception:
                # One failing workshop must not stop the others. The failure is
                # already recorded on the connection for someone to see.
                _logger.exception("kiln sync failed for connection %s", connection.id)
        return True
