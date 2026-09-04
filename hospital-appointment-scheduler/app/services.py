"""
Calendar & SMS services backed by SQLite.

Calendar: checks availability against the SQLite database — weekends are
unavailable, plus all pre-existing and dynamically booked slots in the DB.

SMS: returns a fake message SID by default.  If real Twilio credentials
are set in .env (non-mock), the real Twilio SDK is used.  All SMS records
are persisted to the SQLite database.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from .config import settings
from . import database as db

logger = logging.getLogger(__name__)


# ── Calendar ──────────────────────────────────────────────────────────────────
class CalendarService:
    """
    Calendar service backed by SQLite.

    Rules:
      - Weekends (Sat/Sun) are always unavailable.
      - Business hours: 09:00–17:00, weekdays only.
      - All slots in the database (pre-existing + dynamic) are unavailable.
    """

    def __init__(self):
        # Load pre-existing slots from DB at init time
        self._busy_slots_cache: set[str] = db.get_pre_existing_slots()
        logger.info(f"Calendar: loaded {len(self._busy_slots_cache)} pre-existing slots from DB")

    @property
    def BUSY_SLOTS(self) -> set[str]:
        """Pre-existing busy slots (for backward compatibility with main.py)."""
        return self._busy_slots_cache

    def check_availability(self, dt: datetime) -> bool:
        """Return True if the slot is available, False otherwise."""
        # Weekend check
        if dt.weekday() >= 5:
            logger.info(f"Calendar: {dt} is weekend → unavailable")
            return False

        # Business hours check
        if dt.hour < 9 or dt.hour >= 17:
            logger.info(f"Calendar: {dt} outside business hours → unavailable")
            return False

        # Pre-existing busy slot check
        slot_key = dt.strftime("%Y-%m-%d %H:%M")
        if slot_key in self._busy_slots_cache:
            logger.info(f"Calendar: {dt} is already booked (pre-existing) → unavailable")
            return False

        # Dynamic booking check (from DB)
        iso_dt = dt.strftime("%Y-%m-%dT%H:00:00")
        booked = db.get_booked_datetimes()
        if iso_dt in booked:
            logger.info(f"Calendar: {dt} is already booked (DB) → unavailable")
            return False

        logger.info(f"Calendar: {dt} → available")
        return True

    def find_next_available(self, dt: datetime) -> Optional[datetime]:
        """Find the next available slot after the given datetime."""
        candidate = dt.replace(minute=0, second=0, microsecond=0)
        if candidate < dt:
            candidate += timedelta(hours=1)

        for _ in range(168):
            if self.check_availability(candidate):
                return candidate
            candidate += timedelta(hours=1)

        logger.warning(f"Calendar: no availability found within 7 days of {dt}")
        return None

    def book_slot(
        self,
        dt: datetime,
        patient_name: str,
        department: str,
        contact_phone: str,
        sms_sid: str,
    ) -> dict:
        """Record a new booking in the DB. Assumes availability was already checked."""
        booking = db.add_booking(
            dt=dt,
            patient_name=patient_name,
            department=department,
            contact_phone=contact_phone,
            sms_sid=sms_sid,
        )
        logger.info(f"Calendar: booked {dt} for {patient_name}")
        return booking

    def get_bookings(self) -> list[dict]:
        """Return all bookings from DB as list of dicts (for API/UI)."""
        return db.get_all_bookings()

    def get_busy_slots(self) -> list[str]:
        """Return pre-existing busy slots as sorted list."""
        return sorted(self._busy_slots_cache)

    def find_bookings_by_name(self, patient_name: str) -> list[dict]:
        """Find all dynamic (non-pre-existing) bookings for a patient."""
        return db.find_bookings_by_name(patient_name)

    def reschedule_booking(self, booking_id: int, new_dt: datetime) -> bool:
        """Update an existing booking's datetime. Assumes availability was checked."""
        return db.update_booking_datetime(booking_id, new_dt)

    def cancel_booking(self, booking_id: int) -> bool:
        """Delete a booking by ID."""
        return db.delete_booking(booking_id)


# ── SMS ───────────────────────────────────────────────────────────────────────
class SMSService:
    """
    SMS confirmation service backed by SQLite.

    Mock mode (default): returns a fake SID.
    Real mode: uses the Twilio SDK when TWILIO_ACCOUNT_SID is set to a real value.
    All records are persisted to the database.
    """

    def __init__(self):
        self._is_mock = settings.is_twilio_mock
        self._client = None

        if not self._is_mock:
            try:
                from twilio.rest import Client
                self._client = Client(
                    settings.twilio_account_sid,
                    settings.twilio_auth_token,
                )
                logger.info("SMS: Twilio client initialized (real mode)")
            except Exception as e:
                logger.warning(f"SMS: Twilio init failed ({e}), falling back to mock")
                self._is_mock = True

    def send_confirmation(
        self,
        to_number: str,
        message: str,
    ) -> str:
        """
        Send an SMS confirmation.
        Returns the message SID (real or mock).
        """
        if not to_number:
            logger.warning("SMS: no phone number provided — skipping")
            db.add_sms_record(sid="SKIPPED_NO_PHONE", to_number="", body=message, mode="skip")
            return "SKIPPED_NO_PHONE"

        if self._is_mock or self._client is None:
            sid = f"MOCK_SID_{uuid.uuid4().hex[:12]}"
            logger.info(f"SMS (mock): to={to_number}, sid={sid}")
            logger.info(f"SMS (mock) body: {message[:100]}...")
            db.add_sms_record(sid=sid, to_number=to_number, body=message, mode="mock")
            return sid

        # Real Twilio
        try:
            # Twilio trial accounts require the body to be a predefined template
            # NAME (not formatted text). The available templates are:
            #   sms_2fa, sms_appointment_reminders, sms_order_confirmation,
            #   sms_delivery_updates, sms_customer_support, sms_marketing_promotions,
            #   sms_event_notifications, sms_account_alerts, sms_feedback_surveys,
            #   sms_internal_alerts
            #
            # For paid accounts, body can be any custom text.
            # We detect trial accounts by checking if the from-number starts with
            # a trial prefix, or we simply try the template name first.
            template_body = "sms_appointment_reminders"
            try:
                msg = self._client.messages.create(
                    body=template_body,
                    from_=settings.twilio_from_number,
                    to=to_number,
                )
            except Exception as template_err:
                # If template name fails (e.g. paid account), send the original message
                logger.warning(f"SMS: template name failed, trying custom body: {str(template_err)[:100]}")
                msg = self._client.messages.create(
                    body=message,
                    from_=settings.twilio_from_number,
                    to=to_number,
                )
            logger.info(f"SMS (twilio): to={to_number}, sid={msg.sid}")
            db.add_sms_record(sid=msg.sid, to_number=to_number, body=message, mode="twilio")
            return msg.sid
        except Exception as e:
            logger.error(f"SMS (twilio) error: {e}")
            db.add_sms_record(sid=f"ERROR_{e}", to_number=to_number, body=message, mode="error")
            return f"ERROR_{e}"

    def get_history(self) -> list[dict]:
        """Return all SMS records from DB as list of dicts (for API/UI)."""
        return db.get_all_sms_records()


# ── Singletons ────────────────────────────────────────────────────────────────
calendar_service = CalendarService()
sms_service = SMSService()