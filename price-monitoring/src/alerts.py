"""
Price Alert Notification Module

Sends price change alerts through configurable channels:
  - Console (always on, for CI/CD logs)
  - Webhook (for Slack, Discord, custom endpoints)
  - Email (via SMTP)
  - GitHub Actions Job Summary (for CI visibility)

Enterprise pricing teams typically route these to Slack channels
or integrate with their existing BI/alerting tools via webhooks.
"""

import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — all via environment variables for 12-factor compliance
# ---------------------------------------------------------------------------
WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")
GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")


def send_alerts(alerts: list[dict]) -> dict:
    """
    Route alerts through all configured notification channels.

    Args:
        alerts: List of alert dicts from database.detect_price_changes().

    Returns:
        Summary dict of which channels were notified and any errors.
    """
    if not alerts:
        logger.info("No alerts to send.")
        return {"channels_notified": [], "alerts_count": 0}

    summary = {
        "channels_notified": [],
        "alerts_count": len(alerts),
        "errors": [],
    }

    # Always log to console (visible in CI/CD logs)
    _notify_console(alerts)
    summary["channels_notified"].append("console")

    # GitHub Actions Job Summary (renders as Markdown in the Actions UI)
    if GITHUB_STEP_SUMMARY:
        try:
            _notify_github_summary(alerts)
            summary["channels_notified"].append("github_summary")
        except Exception as e:
            summary["errors"].append(f"github_summary: {e}")
            logger.error("GitHub summary notification failed: %s", e)

    # Webhook (Slack, Discord, custom)
    if WEBHOOK_URL:
        try:
            _notify_webhook(alerts)
            summary["channels_notified"].append("webhook")
        except Exception as e:
            summary["errors"].append(f"webhook: {e}")
            logger.error("Webhook notification failed: %s", e)

    # Email
    if SMTP_HOST and EMAIL_TO:
        try:
            _notify_email(alerts)
            summary["channels_notified"].append("email")
        except Exception as e:
            summary["errors"].append(f"email: {e}")
            logger.error("Email notification failed: %s", e)

    logger.info(
        "Alert summary: %d alerts sent to %s",
        len(alerts),
        ", ".join(summary["channels_notified"]),
    )
    return summary


def _notify_console(alerts: list[dict]) -> None:
    """Print alerts to stdout/logger."""
    logger.info("=" * 60)
    logger.info("🚨 PRICE CHANGE ALERTS (%d detected)", len(alerts))
    logger.info("=" * 60)
    for alert in alerts:
        logger.info(alert["message"])
    logger.info("=" * 60)


def _notify_github_summary(alerts: list[dict]) -> None:
    """
    Write alerts to GitHub Actions Job Summary.
    This renders as a Markdown table in the Actions run UI.
    """
    with open(GITHUB_STEP_SUMMARY, "a") as f:
        f.write("## 🚨 Price Change Alerts\n\n")
        f.write("| Product | Retailer | Type | Old Price | New Price | Change |\n")
        f.write("|---------|----------|------|-----------|-----------|--------|\n")

        for alert in alerts:
            old_price = f"${alert['old_price']:.2f}" if alert["old_price"] else "N/A"
            new_price = f"${alert['new_price']:.2f}" if alert["new_price"] else "N/A"
            pct = f"{alert['pct_change']:+.1f}%" if alert["pct_change"] else "N/A"
            emoji = {
                "price_drop": "📉",
                "price_increase": "📈",
                "back_in_stock": "✅",
                "out_of_stock": "❌",
            }.get(alert["alert_type"], "ℹ️")

            f.write(
                f"| {alert['product_name'][:40]} | {alert['retailer']} "
                f"| {emoji} {alert['alert_type']} | {old_price} | {new_price} | {pct} |\n"
            )

        f.write(f"\n*{len(alerts)} alerts generated*\n\n")

    logger.info("Wrote %d alerts to GitHub Job Summary.", len(alerts))


def _notify_webhook(alerts: list[dict]) -> None:
    """
    Send alerts to a webhook endpoint.

    Supports Slack-compatible payload format by default.
    For Discord, set ALERT_WEBHOOK_FORMAT=discord in env.
    """
    webhook_format = os.environ.get("ALERT_WEBHOOK_FORMAT", "slack")

    if webhook_format == "slack":
        payload = _format_slack_payload(alerts)
    elif webhook_format == "discord":
        payload = _format_discord_payload(alerts)
    else:
        # Generic JSON payload
        payload = {"alerts": alerts}

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    logger.info("Webhook notification sent successfully.")


def _format_slack_payload(alerts: list[dict]) -> dict:
    """Format alerts for Slack incoming webhook."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 {len(alerts)} Price Change Alert(s) Detected",
            },
        },
        {"type": "divider"},
    ]

    for alert in alerts[:10]:  # Slack has block limits
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": alert["message"],
                },
            }
        )

    if len(alerts) > 10:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"_...and {len(alerts) - 10} more alerts_",
                },
            }
        )

    return {"blocks": blocks}


def _format_discord_payload(alerts: list[dict]) -> dict:
    """Format alerts for Discord webhook."""
    description = "\n".join(a["message"] for a in alerts[:15])
    return {
        "embeds": [
            {
                "title": f"🚨 {len(alerts)} Price Change Alert(s)",
                "description": description,
                "color": 15158332,  # Red
            }
        ]
    }


def _notify_email(alerts: list[dict]) -> None:
    """Send alert digest via email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 {len(alerts)} Price Change Alert(s) Detected"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    # Plain text version
    text_body = "PRICE CHANGE ALERTS\n" + "=" * 40 + "\n\n"
    text_body += "\n".join(a["message"] for a in alerts)

    # HTML version (nicer in email clients)
    html_body = """
    <html><body>
    <h2>🚨 Price Change Alerts</h2>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
    <tr style="background-color: #f2f2f2;">
        <th>Product</th><th>Retailer</th><th>Old Price</th>
        <th>New Price</th><th>Change</th>
    </tr>
    """

    for a in alerts:
        old_p = f"${a['old_price']:.2f}" if a["old_price"] else "N/A"
        new_p = f"${a['new_price']:.2f}" if a["new_price"] else "N/A"
        pct = f"{a['pct_change']:+.1f}%" if a["pct_change"] else "N/A"
        color = "#d4edda" if a["pct_change"] and a["pct_change"] < 0 else "#f8d7da"
        html_body += f"""
        <tr style="background-color: {color};">
            <td>{a['product_name'][:50]}</td>
            <td>{a['retailer']}</td>
            <td>{old_p}</td>
            <td>{new_p}</td>
            <td><strong>{pct}</strong></td>
        </tr>
        """

    html_body += "</table></body></html>"

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    logger.info("Email alert sent to %s", EMAIL_TO)
