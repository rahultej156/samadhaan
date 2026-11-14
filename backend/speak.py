"""
Turning data into speakable English.

This module is the reason the `say` convention works. Bulbul reads "₹1,000.00"
as something like "rupee one thousand point zero zero", and a merchant hearing
"point zero zero" knows instantly they are talking to a machine. Dates as
"2026-11-19" are worse.

So every number and date that reaches a `say` string goes through here first.

Deliberately dependency-free: we control the exact output, which matters because
the next step is a Sarvam model translating it into Telugu or Hindi. No hyphens
(TTS pauses on them), no "point", no digits where words read better.

Indian numbering above ten thousand: 1,00,000 is "one lakh", not "one hundred
thousand". A merchant in Hyderabad expects lakhs.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

_UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]

_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]

_MONTHS = [
    "", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
    6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
    11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth",
    15: "fifteenth", 16: "sixteenth", 17: "seventeenth", 18: "eighteenth",
    19: "nineteenth", 20: "twentieth", 21: "twenty first",
    22: "twenty second", 23: "twenty third", 24: "twenty fourth",
    25: "twenty fifth", 26: "twenty sixth", 27: "twenty seventh",
    28: "twenty eighth", 29: "twenty ninth", 30: "thirtieth",
    31: "thirty first",
}


def _under_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    return _TENS[tens] if unit == 0 else f"{_TENS[tens]} {_UNITS[unit]}"


def _under_thousand(n: int) -> str:
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return f"{_UNITS[hundreds]} hundred"
    # "eight hundred and sixty eight" - the "and" is how it is said aloud here.
    return f"{_UNITS[hundreds]} hundred and {_under_hundred(rest)}"


def number_in_words(n: int) -> str:
    """125 -> 'one hundred and twenty five'. Indian grouping above 9,999."""
    if n < 0:
        return f"minus {number_in_words(-n)}"
    if n < 1000:
        return _under_thousand(n)

    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    if crore:
        parts.append(f"{number_in_words(crore)} crore")
    lakh, n = divmod(n, 100_000)
    if lakh:
        parts.append(f"{number_in_words(lakh)} lakh")
    thousand, n = divmod(n, 1000)
    if thousand:
        parts.append(f"{_under_thousand(thousand)} thousand")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def rupees_spoken(amount: Decimal | float | int | None) -> str:
    """
    Decimal('1000.00') -> 'one thousand rupees'
    Decimal('125.50')  -> 'one hundred and twenty five rupees and fifty paise'

    Whole amounts never get "point zero zero", which is the whole point.
    """
    if amount is None:
        return "no amount"
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    whole = int(value)
    paise = int((value - whole) * 100)

    rupee_word = "rupee" if whole == 1 else "rupees"
    spoken = f"{number_in_words(whole)} {rupee_word}"
    if paise:
        paise_word = "paisa" if paise == 1 else "paise"
        spoken += f" and {number_in_words(paise)} {paise_word}"
    return spoken


def rupees_text(amount: Decimal | float | int | None) -> str:
    """Display form for the dashboard and the written proof: '₹1,000.00'."""
    if amount is None:
        return "₹0.00"
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    whole = int(abs(value))
    paise = f"{abs(value) - whole:.2f}"[2:]

    # Indian digit grouping: last three digits, then pairs. 1234567 -> 12,34,567
    digits = str(whole)
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        grouped = ",".join(pairs + [tail])

    sign = "-" if value < 0 else ""
    return f"{sign}₹{grouped}.{paise}"


def date_spoken(d: date | datetime | None) -> str:
    """date(2026, 11, 19) -> 'the nineteenth of November'."""
    if d is None:
        return "an unknown date"
    if isinstance(d, datetime):
        d = d.date()
    return f"the {_ORDINALS[d.day]} of {_MONTHS[d.month]}"


def month_spoken(d: date | datetime | None) -> str:
    """For 'since your shop closed in March'."""
    if d is None:
        return "an unknown month"
    if isinstance(d, datetime):
        d = d.date()
    return _MONTHS[d.month]


def date_range_text(start: date | None, end: date | None) -> str:
    """Display form for the proof document: '12 March 2026 to 14 November 2026'."""
    def one(d: date | None) -> str:
        if d is None:
            return "unknown"
        return f"{d.day} {_MONTHS[d.month]} {d.year}"

    return f"{one(start)} to {one(end)}"


def months_spoken(count: int) -> str:
    """7 -> 'seven months'."""
    if count == 1:
        return "one month"
    return f"{number_in_words(count)} months"


def days_spoken(count: int) -> str:
    if count == 1:
        return "one day"
    return f"{number_in_words(count)} days"


def ago_text(then: datetime | None, now: datetime | None = None) -> str:
    """
    'about twenty minutes ago' / 'yesterday' / 'about three days ago'.

    Used when a merchant calls back, so the agent can show it remembers the
    earlier call without reading out a timestamp.
    """
    if then is None:
        return "earlier"
    now = now or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)

    seconds = max(0, int((now - then).total_seconds()))
    minutes = seconds // 60

    if minutes < 2:
        return "just now"
    if minutes < 60:
        # Round to the nearest five minutes: "about twenty minutes ago" sounds
        # human, "about nineteen minutes ago" sounds like a machine reading.
        rounded = max(5, 5 * round(minutes / 5))
        return f"about {number_in_words(rounded)} minutes ago"

    hours = minutes // 60
    if hours < 24:
        if hours == 1:
            return "about an hour ago"
        return f"about {number_in_words(hours)} hours ago"

    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"about {number_in_words(days)} days ago"
    weeks = days // 7
    if weeks == 1:
        return "about a week ago"
    return f"about {number_in_words(weeks)} weeks ago"


def join_spoken(items: list[str]) -> str:
    """['PAN card photo', 'GST certificate'] -> 'PAN card photo and GST certificate'."""
    clean = [i for i in items if i]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f" and {clean[-1]}"


def working_days_from(start: date, days: int) -> date:
    """
    Skip Saturdays and Sundays. A pickup promised for Sunday is a pickup that
    does not happen, and then the merchant calls back angrier.
    """
    current = start
    remaining = days
    while remaining > 0:
        current = date.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            remaining -= 1
    return current
