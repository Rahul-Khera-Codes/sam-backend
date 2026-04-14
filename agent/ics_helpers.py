"""
ICS calendar file generator for appointment emails.
Produces a standard iCalendar (.ics) string that email clients
(Gmail, Outlook, Apple Mail) can import as a calendar event.
"""

from datetime import datetime, timedelta
import uuid


def generate_ics(
    *,
    summary: str,
    description: str,
    location: str,
    date: str,           # YYYY-MM-DD
    time: str,           # HH:MM (24h)
    duration_minutes: int,
    organizer_email: str = "",
    attendee_email: str = "",
    uid: str = "",
    method: str = "REQUEST",
) -> str:
    """
    Generate an iCalendar (.ics) file content string.

    Args:
        summary:          Event title (e.g. "Haircut — Mirage Banquets")
        description:      Event description / notes
        location:         Location name or address
        date:             Appointment date as YYYY-MM-DD
        time:             Appointment time as HH:MM (24h)
        duration_minutes: How long the appointment lasts
        organizer_email:  Business/sender email (optional)
        attendee_email:   Customer email (optional)
        uid:              Unique ID for the event (auto-generated if empty)
        method:           VCALENDAR method — REQUEST (new invite) or
                          CANCEL (cancellation)

    Returns:
        String content of the .ics file, ready to attach to an email.
    """
    if not uid:
        uid = f"{uuid.uuid4()}@aiemployees"

    # Parse start → compute end
    hour, minute = map(int, time.split(":"))
    start_dt = datetime.strptime(f"{date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Format as iCal datetime (UTC-naive; we use TZID-less format for max compat)
    fmt = "%Y%m%dT%H%M%S"
    dtstart = start_dt.strftime(fmt)
    dtend = end_dt.strftime(fmt)
    dtstamp = datetime.utcnow().strftime(fmt) + "Z"

    # Escape special chars per RFC 5545
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AI Employees//Appointment//EN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(description)}",
        f"LOCATION:{esc(location)}",
        "STATUS:CONFIRMED" if method == "REQUEST" else "STATUS:CANCELLED",
    ]

    if organizer_email:
        lines.append(f"ORGANIZER;CN={esc(organizer_email)}:mailto:{organizer_email}")
    if attendee_email:
        lines.append(f"ATTENDEE;RSVP=TRUE;CN={esc(attendee_email)}:mailto:{attendee_email}")

    lines += [
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(lines)
