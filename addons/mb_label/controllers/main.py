import base64

from markupsafe import escape

from odoo import http
from odoo.http import request


class MbLabelController(http.Controller):
    def _job(self, job_id):
        job = request.env["mb.label.print.job"].browse(job_id).exists()
        job.check_access("read")
        return job

    @http.route("/mb_label/job/<int:job_id>/preview.png", type="http", auth="user")
    def preview(self, job_id):
        job = self._job(job_id)
        return request.make_response(
            base64.b64decode(job.preview_png or b""),
            headers=[("Content-Type", "image/png"), ("Cache-Control", "private, no-store")],
        )

    @http.route("/mb_label/job/<int:job_id>/label.pdf", type="http", auth="user")
    def pdf(self, job_id, download=0):
        job = self._job(job_id)
        disposition = "attachment" if str(download) == "1" else "inline"
        filename = (job.artifact_name or "label.pdf").replace('"', "")
        return request.make_response(
            base64.b64decode(job.artifact_pdf or b""),
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", '%s; filename="%s"' % (disposition, filename)),
                ("Cache-Control", "private, no-store"),
            ],
        )

    @http.route("/mb_label/job/<int:job_id>/print", type="http", auth="user")
    def browser_print(self, job_id, autoprint=0):
        job = self._job(job_id)
        copies = "".join(
            '<section class="label"><img src="/mb_label/job/%s/preview.png" alt="%s"></section>'
            % (job.id, escape(job.name))
            for _copy in range(job.copies)
        )
        script = (
            "<script>addEventListener('load',()=>window.print())</script>"
            if str(autoprint) == "1"
            else ""
        )
        html = """<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title>
<style>
@page { size: %smm %smm; margin: 0; }
html, body { margin: 0; padding: 0; background: white; }
.label { width: %smm; height: %smm; margin: 0; page-break-after: always; overflow: hidden; }
.label:last-child { page-break-after: auto; }
.label img { display: block; width: 100%%; height: 100%%; image-rendering: pixelated; }
@media screen { body { background: #ddd; } .label { margin: 10px auto; box-shadow: 0 2px 10px #777; } }
</style></head><body>%s%s</body></html>""" % (
            escape(job.name),
            job.width_mm,
            job.height_mm,
            job.width_mm,
            job.height_mm,
            copies,
            script,
        )
        return request.make_response(html, headers=[("Content-Type", "text/html; charset=utf-8")])
