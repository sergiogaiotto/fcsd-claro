import io
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def build_eml(
    to_email: str,
    subject: str,
    body_html: str,
    data: dict | None = None,
) -> bytes:
    """Build a .eml file with HTML body and optional Excel attachment.
    Opening the .eml file launches the local Outlook with everything pre-filled."""

    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"  # Outlook opens as draft (unsent)

    intro = (
        "<p>Prezado(a),</p>"
        "<p>Segue em anexo os dados solicitados via Quick Insights.</p>"
    )
    full_body = f"<html><body>{intro}{body_html}</body></html>"
    msg.attach(MIMEText(full_body, "html", "utf-8"))

    if data and "rows" in data and data["rows"]:
        df = pd.DataFrame(data["rows"])
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)

        part = MIMEBase(
            "application",
            "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        part.set_payload(buffer.read())
        encoders.encode_base64(part)
        filename = f"{subject}.xlsx"
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    return msg.as_bytes()


def export_to_excel_bytes(data: dict) -> bytes:
    if not data or "rows" not in data or not data["rows"]:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(data["rows"])

    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()
