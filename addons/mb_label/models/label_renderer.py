import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import re

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from odoo import _, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_amount

from .label_template import TOKEN_RE, build_qr_value, parse_filters, qr_identity_path


MM_TO_PT = 72.0 / 25.4
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATHS = {
    ("sans", False, False): FONT_PATH,
    ("sans", True, False): FONT_BOLD_PATH,
    ("sans", False, True): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ("sans", True, True): "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    ("serif", False, False): "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ("serif", True, False): "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ("serif", False, True): "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    ("serif", True, True): "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
    ("mono", False, False): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ("mono", True, False): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ("mono", False, True): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
    ("mono", True, True): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf",
}
DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.DOTALL)
EXPRESSION_RE = re.compile(r"\[\[([a-z]+)(?:\|([^\]]*))?\]\]", re.IGNORECASE)
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)


class MbLabelRenderService(models.AbstractModel):
    _name = "mb.label.render.service"
    _description = "Deterministic Label Render Service"

    def bindings_for(self, product, lot=None, manual=None, qr_url_prefix=""):
        product.ensure_one()
        if lot:
            lot.ensure_one()
            if lot.product_id != product:
                raise ValidationError(_("The lot or serial does not belong to this product."))
        sku = product.default_code or str(product.id)
        qr_path = qr_identity_path(sku, lot.name if lot else None)
        qr = build_qr_value(qr_url_prefix, sku, lot.name if lot else None)
        currency = self.env.company.currency_id
        price = format_amount(self.env, product.lst_price, currency).strip()
        values = {
            "product.default_code": product.default_code or "",
            # The template has a separate SKU binding. Odoo's display_name
            # often prefixes that SKU, which would duplicate it and consume
            # most of a small thermal label's first line.
            "product.name": product.name or "",
            "product.barcode": product.barcode or "",
            "product.price": price,
            "product.price.raw": product.lst_price,
            "lot.name": lot.name if lot else "",
            "company.name": self.env.company.name,
            "company.currency": currency.name,
            "qr": qr,
            "qr.path": qr_path,
        }
        for key, value in (manual or {}).items():
            if not re.fullmatch(r"[A-Za-z_][\w-]*", str(key)):
                raise ValidationError(_("Invalid manual label field."))
            values["manual.%s" % key] = str(value or "")
        return values

    def resolve(self, source, values, required=True):
        source = source or ""

        def replace(match):
            key, filters = match.group(1), parse_filters(match.group(2))
            value = values.get(key, "")
            value = self._apply_filters(value, filters, values)
            if required and value in (None, ""):
                raise ValidationError(_("Label binding '%s' has no value for this subject.", key))
            return str(value)

        return self._evaluate_expressions(TOKEN_RE.sub(replace, source))

    def _decimal_value(self, value):
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise ValidationError(_("A numeric label filter received a non-numeric value.")) from None

    def _format_decimal(self, value, minimum, maximum):
        language = (self.env.lang or "en_US").replace("-", "_")
        pattern = "#,##0"
        if maximum:
            pattern += "." + ("0" * minimum) + ("#" * (maximum - minimum))
        try:
            from babel.numbers import format_decimal
            return format_decimal(value, format=pattern, locale=language)
        except (ValueError, ArithmeticError):
            return format(value, ".%sf" % minimum)

    def _trim_money_zeros(self, value):
        currency = self.env.company.currency_id
        digits = max(0, currency.decimal_places)
        if not digits:
            return value
        return re.sub(r"([,.])0{%s}(?=(?:\s|[^\d])*$)" % digits, "", value)

    def _apply_filters(self, value, filters, values):
        for name, argument in filters:
            if name == "default":
                if value in (None, ""):
                    value = argument or ""
            elif name == "trim":
                value = str(value or "").strip()
            elif name == "upper":
                value = str(value or "").upper()
            elif name == "lower":
                value = str(value or "").lower()
            elif name == "title":
                value = str(value or "").title()
            elif name == "money":
                try:
                    numeric = self._decimal_value(value)
                except ValidationError:
                    continue
                value = format_amount(
                    self.env, float(numeric), self.env.company.currency_id).strip()
            elif name == "money_trim":
                try:
                    numeric = self._decimal_value(value)
                    value = format_amount(
                        self.env, float(numeric), self.env.company.currency_id).strip()
                except ValidationError:
                    value = str(value or "")
                value = self._trim_money_zeros(value)
            elif name == "number":
                value = self._format_decimal(self._decimal_value(value), 0, 3)
            elif name == "fixed":
                digits = int(argument)
                value = self._format_decimal(self._decimal_value(value), digits, digits)
        return value

    def _evaluate_expressions(self, source, now=None):
        now = now or datetime.now()

        def formatted(pattern):
            tokens = {
                "YYYY": "%04d" % now.year, "YY": "%02d" % (now.year % 100),
                "MM": "%02d" % now.month, "DD": "%02d" % now.day,
                "HH": "%02d" % now.hour, "mm": "%02d" % now.minute,
                "ss": "%02d" % now.second,
            }
            return re.sub(r"YYYY|YY|MM|DD|HH|mm|ss", lambda match: tokens[match.group(0)], pattern)

        builtins = {
            "date": formatted("DD/MM/YYYY"), "time": formatted("HH:mm"),
            "datetime": formatted("DD/MM/YYYY HH:mm"), "iso": formatted("YYYY-MM-DD"),
            "year": formatted("YYYY"), "month": MONTHS[now.month - 1],
            "monthyear": "%s %s" % (MONTHS[now.month - 1], now.year),
        }

        def replace(match):
            name, pattern = match.group(1).lower(), match.group(2)
            if pattern is not None and (name in builtins or name == "now"):
                return formatted(pattern)
            return builtins.get(name, match.group(0))

        return EXPRESSION_RE.sub(replace, source or "")

    def _font(self, px, bold=False, italic=False, family="sans"):
        path = FONT_PATHS.get((family, bool(bold), bool(italic)), FONT_PATH)
        try:
            return ImageFont.truetype(path, max(7, int(px)))
        except OSError:
            return ImageFont.load_default()

    def _barcode_image(self, kind, value, width, height, humanreadable=False):
        raw = self.env["ir.actions.report"].barcode(
            kind or "auto", value, width=max(40, width), height=max(40, height),
            quiet=True, humanreadable=humanreadable, barLevel="M")
        return Image.open(io.BytesIO(raw)).convert("1")

    def _qr_image(self, value, width, height, quiet_zone=4):
        code = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=1,
            border=int(quiet_zone),
        )
        code.add_data(value)
        code.make(fit=True)
        modules = code.make_image(fill_color="black", back_color="white").convert("1")
        side = min(width, height)
        if side < modules.width:
            raise ValidationError(_(
                "The QR element is too small for its encoded value. Enlarge it or shorten the URL."))
        modules = modules.resize((side, side), Image.Resampling.NEAREST)
        result = Image.new("1", (width, height), 1)
        result.paste(modules, ((width - side) // 2, (height - side) // 2))
        return result

    def _dither_image(self, image, mode="threshold", threshold=160):
        image = ImageOps.autocontrast(image.convert("L"))
        if mode == "floyd-steinberg":
            return image.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
        pixels = list(image.getdata())
        width, height = image.size
        if mode == "atkinson":
            values = [float(value) for value in pixels]
            output = [255] * len(values)
            for y in range(height):
                for x in range(width):
                    index = y * width + x
                    old = values[index]
                    new = 0 if old < 128 else 255
                    output[index] = new
                    error = (old - new) / 8
                    for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < width and ny < height:
                            values[ny * width + nx] += error
            result = Image.new("L", image.size)
            result.putdata(output)
            return result
        if mode == "ordered":
            bayer = (
                0, 32, 8, 40, 2, 34, 10, 42, 48, 16, 56, 24, 50, 18, 58, 26,
                12, 44, 4, 36, 14, 46, 6, 38, 60, 28, 52, 20, 62, 30, 54, 22,
                3, 35, 11, 43, 1, 33, 9, 41, 51, 19, 59, 27, 49, 17, 57, 25,
                15, 47, 7, 39, 13, 45, 5, 37, 63, 31, 55, 23, 61, 29, 53, 21,
            )
            output = [
                0 if value < bayer[(index // width % 8) * 8 + (index % width % 8)] * 255 / 64 else 255
                for index, value in enumerate(pixels)
            ]
            result = Image.new("L", image.size)
            result.putdata(output)
            return result
        return image.point(lambda pixel: 255 if pixel >= int(threshold) else 0)

    def render_png(self, version, values, dpi=None):
        version.ensure_one()
        dpi = int(dpi or version.dpi)
        px_per_mm = dpi / 25.4
        width = max(1, round(version.width_mm * px_per_mm))
        height = max(1, round(version.height_mm * px_per_mm))
        image = Image.new("L", (width, height), 255)
        elements = sorted(
            version.document_json.get("elements", []), key=lambda item: item.get("z", 0))
        def mm(value):
            return round(float(value or 0) * px_per_mm)

        def shape_mask(kind, box, stroke, filled):
            result = Image.new("L", (width, height), 0)
            shape = ImageDraw.Draw(result)
            x, y, w, h = box
            bounds = (x, y, x + w, y + h)
            if kind == "rect":
                shape.rectangle(bounds, fill=255 if filled else None,
                                outline=None if filled else 255, width=stroke)
            elif kind == "ellipse":
                shape.ellipse(bounds, fill=255 if filled else None,
                              outline=None if filled else 255, width=stroke)
            elif kind == "triangle":
                points = ((x + w // 2, y), (x + w, y + h), (x, y + h))
                shape.polygon(points, fill=255 if filled else None,
                              outline=None if filled else 255)
                if not filled and stroke > 1:
                    shape.line(points + (points[0],), fill=255, width=stroke, joint="curve")
            else:
                line_y = y + h // 2
                shape.line((x, line_y, x + w, line_y), fill=255, width=stroke)
            return result

        def tinted(mask, tint):
            if tint in (None, "solid"):
                return mask
            patterns = {
                "75": ((1, 1), (1, 0)),
                "50": ((1, 0), (0, 1)),
                "25": ((1, 0), (0, 0)),
            }
            pattern = patterns[tint]
            rows = []
            for py in range(height):
                pair = bytes(255 if value else 0 for value in pattern[py % 2])
                rows.append((pair * ((width + 1) // 2))[:width])
            tile = Image.frombytes("L", (width, height), b"".join(rows))
            return ImageChops.multiply(mask, tile)

        for element in elements:
            x, y = mm(element["x"]), mm(element["y"])
            w, h = max(1, mm(element["width"])), max(1, mm(element["height"]))
            kind = element["type"]
            resolved_content = None
            if kind == "text":
                resolved_content = self.resolve(
                    element.get("text", ""), values, required=element.get("required", True))
            elif kind in ("qr", "barcode"):
                resolved_content = self.resolve(
                    element.get("data", "{{qr}}"), values,
                    required=element.get("required", True))
            if kind in ("text", "qr", "barcode") and not element.get("required", True) \
                    and not resolved_content:
                continue
            layer = Image.new("L", (width, height), 255)
            mask = Image.new("L", (width, height), 0)
            layer_draw, mask_draw = ImageDraw.Draw(layer), ImageDraw.Draw(mask)
            ink = 255 if element.get("inverted") else 0
            background = element.get("background")
            if background and background != "transparent":
                bounds = (x, y, x + w, y + h)
                layer_draw.rectangle(bounds, fill=0 if background == "black" else 255)
                mask_draw.rectangle(bounds, fill=255)

            if kind in ("rect", "ellipse", "triangle", "line"):
                stroke = max(1, mm(element.get("stroke_width", 0.25)))
                geometry = shape_mask(kind, (x, y, w, h), stroke, element.get("filled", False))
                if element.get("filled"):
                    geometry = tinted(geometry, element.get("tint"))
                layer.paste(ink, (0, 0, width, height), geometry)
                mask.paste(255, (0, 0, width, height), geometry)
            elif kind == "text":
                text = resolved_content
                font = self._font(
                    mm(element.get("font_size", 3)), element.get("bold", False),
                    element.get("italic", False), element.get("font", "sans"))
                lines = []
                for paragraph in text.splitlines() or [""]:
                    if element.get("no_wrap"):
                        lines.append(paragraph)
                        continue
                    current = ""
                    for word in paragraph.split(" "):
                        candidate = (current + " " + word).strip()
                        if not current or layer_draw.textbbox((0, 0), candidate, font=font)[2] <= w:
                            current = candidate
                        else:
                            lines.append(current)
                            current = word
                    lines.append(current)
                line_height = max(1, font.getbbox("Ag")[3] - font.getbbox("Ag")[1])
                visible = lines[:max(1, h // line_height)]
                block_height = len(visible) * line_height
                valign = element.get("valign", "middle")
                first_y = y if valign == "top" else y + h - block_height if valign == "bottom" else y + (h - block_height) // 2
                for index, line in enumerate(visible):
                    line_width = layer_draw.textbbox((0, 0), line, font=font)[2]
                    align = element.get("align", "left")
                    line_x = x if align == "left" else (x + w - line_width if align == "right" else x + (w - line_width) // 2)
                    line_y = first_y + index * line_height
                    layer_draw.text((line_x, line_y), line, font=font, fill=ink)
                    mask_draw.text((line_x, line_y), line, font=font, fill=255)
                    if element.get("underline"):
                        underline_y = min(y + h - 1, line_y + line_height - 1)
                        thickness = max(1, round(font.size / 12))
                        line_box = (line_x, underline_y, line_x + line_width, underline_y + thickness)
                        layer_draw.rectangle(line_box, fill=ink)
                        mask_draw.rectangle(line_box, fill=255)
            elif kind in ("qr", "barcode"):
                value = resolved_content
                code = self._qr_image(
                    value, w, h, element.get("quiet_zone", 4)) if kind == "qr" else self._barcode_image(
                    element.get("format", "auto"), value, w, h,
                    element.get("show_value", False)).resize((w, h), Image.Resampling.NEAREST)
                layer.paste(code, (x, y))
                mask_draw.rectangle((x, y, x + w, y + h), fill=255)
            elif kind == "image":
                match = DATA_URL_RE.match(element.get("data", ""))
                if match:
                    try:
                        logo = Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert("L")
                        logo.thumbnail(
                            (w, h), Image.Resampling.NEAREST if element.get("pre_binarised")
                            else Image.Resampling.LANCZOS)
                        if element.get("pre_binarised"):
                            logo = logo.point(lambda pixel: 255 if pixel >= 128 else 0)
                        else:
                            logo = self._dither_image(
                                logo, element.get("dither", "threshold"),
                                element.get("dither_threshold", 160))
                        logo_x, logo_y = x + (w - logo.width) // 2, y + (h - logo.height) // 2
                        layer_draw.rectangle((x, y, x + w, y + h), fill=255)
                        layer.paste(logo, (logo_x, logo_y))
                        mask_draw.rectangle((x, y, x + w, y + h), fill=255)
                    except Exception as error:
                        raise ValidationError(_("The label contains an unreadable image.")) from error

            rotation = int(element.get("rotation", 0)) % 360
            if rotation:
                center = (x + w / 2, y + h / 2)
                layer = layer.rotate(-rotation, resample=Image.Resampling.BICUBIC,
                                     center=center, fillcolor=255)
                mask = mask.rotate(-rotation, resample=Image.Resampling.NEAREST,
                                   center=center, fillcolor=0)
            image = Image.composite(layer, image, mask)

        if version.round_media:
            outside = Image.new("L", (width, height), 255)
            keep = Image.new("L", (width, height), 0)
            ImageDraw.Draw(keep).ellipse((0, 0, width - 1, height - 1), fill=255)
            image = Image.composite(image, outside, keep)
        output = io.BytesIO()
        image.convert("1").save(output, format="PNG", optimize=False)
        return output.getvalue()

    def render_pdf(self, png, width_mm, height_mm, copies=1):
        output = io.BytesIO()
        width_pt, height_pt = width_mm * MM_TO_PT, height_mm * MM_TO_PT
        document = pdf_canvas.Canvas(output, pagesize=(width_pt, height_pt), pageCompression=1)
        for _copy in range(max(1, int(copies))):
            document.drawImage(
                ImageReader(io.BytesIO(png)), 0, 0, width=width_pt, height=height_pt,
                preserveAspectRatio=False, mask="auto")
            document.showPage()
        document.save()
        return output.getvalue()
