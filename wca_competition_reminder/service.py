import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from wca_competition_reminder.config import AppConfig, RecipientConfig
from wca_competition_reminder.distance import coordinates_are_valid
from wca_competition_reminder.email_content import build_delivery_drafts
from wca_competition_reminder.email_templates import EmailTemplateCatalog
from wca_competition_reminder.events import ordered_official_event_ids
from wca_competition_reminder.mailer import DeliverySendError, SmtpMailer
from wca_competition_reminder.models import CompetitionStatus
from wca_competition_reminder.state import StateStore
from wca_competition_reminder.subscriptions import recipient_from_record
from wca_competition_reminder.utils import mask_email, utc_now
from wca_competition_reminder.wca import WcaApiError, WcaClient

LOGGER = logging.getLogger(__name__)


class ReminderService:
    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        wca: WcaClient,
        mailer: SmtpMailer,
        *,
        clock: Callable[[], datetime] = utc_now,
        stop_requested: Callable[[], bool] = lambda: False,
        template_catalog: EmailTemplateCatalog | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._wca = wca
        self._mailer = mailer
        self._clock = clock
        self._stop_requested = stop_requested
        self._template_catalog = template_catalog

    def run_once(self) -> bool:
        started_at = self._clock()
        current_date = started_at.astimezone(self._config.timezone).date()

        if not self._state.is_baseline_initialized():
            summaries = self._wca.fetch_all_future(current_date)
            completed_at = self._clock()
            count = self._state.initialize_baseline(
                summaries,
                completed_at,
                snapshot_started_at=started_at,
            )
            LOGGER.info("baseline initialized competitions=%d", count)
            return True

        scan_succeeded = self._run_incremental_scan(current_date)
        if self._stop_requested():
            return scan_succeeded

        if scan_succeeded and self._state.full_reconciliation_due(
            self._clock(), timedelta(hours=self._config.full_reconcile_hours)
        ):
            scan_succeeded = self._run_full_reconciliation(current_date) and scan_succeeded

        if self._stop_requested():
            return scan_succeeded

        self._process_enrichments()
        if self._stop_requested():
            return scan_succeeded

        self._process_deliveries()
        return scan_succeeded

    def _run_incremental_scan(self, current_date: date) -> bool:
        checkpoint = self._state.incremental_checkpoint_at()
        announced_after = (checkpoint - timedelta(days=self._config.wca.overlap_days)).date()
        try:
            summaries = self._wca.fetch_recent_future(current_date, announced_after)
            completed_at = self._clock()
            stats = self._state.record_scan(
                summaries,
                completed_at,
                full_reconciliation=False,
            )
        except WcaApiError:
            if self._stop_requested():
                LOGGER.info("incremental WCA scan cancelled; checkpoint was not advanced")
            else:
                LOGGER.exception("incremental WCA scan failed; checkpoint was not advanced")
            return False
        LOGGER.info(
            "incremental scan fetched=%d discovered=%d details_pending=%d ignored=%d silent=%d",
            len(summaries),
            stats.discovered,
            stats.queued_for_details,
            stats.ignored,
            stats.silently_recorded,
        )
        return True

    def _run_full_reconciliation(self, current_date: date) -> bool:
        try:
            summaries = self._wca.fetch_all_future(current_date)
            completed_at = self._clock()
            stats = self._state.record_scan(
                summaries,
                completed_at,
                full_reconciliation=True,
            )
        except WcaApiError:
            if self._stop_requested():
                LOGGER.info("full WCA reconciliation cancelled")
            else:
                LOGGER.exception("full WCA reconciliation failed")
            return False
        LOGGER.info(
            "full reconciliation fetched=%d discovered=%d details_pending=%d ignored=%d silent=%d",
            len(summaries),
            stats.discovered,
            stats.queued_for_details,
            stats.ignored,
            stats.silently_recorded,
        )
        return True

    def _process_enrichments(self) -> None:
        now = self._clock()
        available_recipients = self._effective_recipients()
        for pending in self._state.due_enrichments(now):
            if self._stop_requested():
                LOGGER.info("enrichment processing stopped for shutdown")
                return
            competition_id = pending.summary.competition_id
            try:
                details = self._wca.fetch_details(competition_id)
            except WcaApiError as exc:
                if self._stop_requested():
                    LOGGER.info("competition detail fetch cancelled id=%s", competition_id)
                    return
                LOGGER.warning("competition detail retry id=%s error=%s", competition_id, exc)
                self._state.mark_enrichment_retry(competition_id, now, str(exc))
                continue

            if details.cancelled_at is not None:
                self._state.mark_ignored(
                    competition_id,
                    CompetitionStatus.IGNORED_CANCELLED,
                    details.raw_json,
                    now,
                )
                LOGGER.info("ignored cancelled competition id=%s", competition_id)
                continue
            official_event_ids = ordered_official_event_ids(details.event_ids)
            if not official_event_ids:
                self._state.mark_ignored(
                    competition_id,
                    CompetitionStatus.IGNORED_NO_OFFICIAL_EVENTS,
                    details.raw_json,
                    now,
                )
                LOGGER.info("ignored competition without official events id=%s", competition_id)
                continue

            event_recipients = tuple(
                recipient
                for recipient in available_recipients
                if recipient.follows_any(official_event_ids)
            )
            if not event_recipients:
                self._state.queue_deliveries(competition_id, details.raw_json, (), now)
                LOGGER.info(
                    "competition has no subscribed recipients id=%s events=%s",
                    competition_id,
                    ",".join(official_event_ids),
                )
                continue

            country = None
            if any(
                recipient.needs_region_for(official_event_ids)
                for recipient in event_recipients
            ):
                try:
                    country = self._wca.fetch_country(details.country_iso2)
                except WcaApiError as exc:
                    if self._stop_requested():
                        LOGGER.info("competition region lookup cancelled id=%s", competition_id)
                        return
                    LOGGER.warning(
                        "competition region lookup retry id=%s error=%s", competition_id, exc
                    )
                    self._state.mark_enrichment_retry(competition_id, now, str(exc))
                    continue

            recipients = (
                event_recipients
                if country is None
                else tuple(
                    recipient
                    for recipient in event_recipients
                    if recipient.follows_event_and_region(
                        official_event_ids,
                        country.name,
                        country.continent_name,
                    )
                )
            )
            if not recipients:
                self._state.queue_deliveries(competition_id, details.raw_json, (), now)
                assert country is not None
                LOGGER.info(
                    "competition has no matching recipients id=%s events=%s country=%s "
                    "continent=%s",
                    competition_id,
                    ",".join(official_event_ids),
                    country.name,
                    country.continent_name,
                )
                continue

            coordinates_valid = coordinates_are_valid(details.latitude, details.longitude)
            deadline = pending.coordinate_deadline_at
            if not coordinates_valid:
                deadline = deadline or now + timedelta(hours=self._config.coordinate_retry_hours)
                if now < deadline:
                    self._state.mark_enrichment_retry(
                        competition_id,
                        now,
                        "WCA competition coordinates are missing or invalid",
                        status=CompetitionStatus.PENDING_COORDINATES,
                        coordinate_deadline_at=deadline,
                    )
                    LOGGER.warning(
                        "competition coordinates unavailable id=%s retry_deadline=%s",
                        competition_id,
                        deadline.isoformat(),
                    )
                    continue

            country_name = country.name if country is not None else ""
            continent_name = country.continent_name if country is not None else ""
            matched_recipients = tuple(
                recipient.for_condition(condition)
                for recipient in recipients
                if (
                    condition := recipient.matching_condition(
                        official_event_ids,
                        country_name=country_name,
                        continent_name=continent_name,
                        competition_latitude=details.latitude,
                        competition_longitude=details.longitude,
                    )
                )
                is not None
            )
            if not matched_recipients:
                self._state.queue_deliveries(competition_id, details.raw_json, (), now)
                LOGGER.info(
                    "competition has no recipients within distance id=%s recipients=%d "
                    "coordinates_available=%s",
                    competition_id,
                    len(recipients),
                    coordinates_valid,
                )
                continue

            drafts = build_delivery_drafts(
                details,
                matched_recipients,
                from_address=self._config.smtp.from_address,
                subscription_base_url=self._config.web_base_url,
                distance_available=coordinates_valid,
                template_catalog=self._template_catalog,
                templates_path=self._config.email_templates_path,
            )
            queued = self._state.queue_deliveries(
                competition_id,
                details.raw_json,
                drafts,
                now,
            )
            LOGGER.info(
                "competition notifications queued id=%s recipients=%d distance_available=%s",
                competition_id,
                queued,
                coordinates_valid,
            )

    def _effective_recipients(self) -> tuple[RecipientConfig, ...]:
        """Merge web-managed subscriptions with the legacy TOML recipients.

        A web-managed address overrides a same-address TOML entry, including while it
        is cancelled. This makes cancellation deterministic and lets an existing
        configured recipient take control of its settings through the web form.
        """
        managed = {record.email: record for record in self._state.list_subscribers()}
        recipients = [
            recipient for recipient in self._config.recipients if recipient.email not in managed
        ]
        recipients.extend(
            recipient_from_record(record) for record in managed.values() if record.active
        )
        return tuple(recipients)

    def _process_deliveries(self) -> None:
        for _ in range(self._config.max_emails_per_run):
            if self._stop_requested():
                LOGGER.info("email delivery stopped for shutdown")
                return
            now = self._clock()
            delivery = self._state.claim_delivery(now, lease=timedelta(minutes=5))
            if delivery is None:
                return
            try:
                self._mailer.send(delivery)
            except DeliverySendError as exc:
                if exc.stop_run:
                    self._state.mark_delivery_retry(
                        delivery,
                        now,
                        str(exc),
                        immediate=True,
                    )
                    LOGGER.error(
                        "email delivery halted competition=%s recipient=%s error=%s",
                        delivery.competition_id,
                        mask_email(delivery.recipient_email),
                        exc,
                    )
                    raise
                if exc.permanent:
                    self._state.mark_delivery_blocked(delivery, str(exc))
                    LOGGER.error(
                        "email blocked competition=%s recipient=%s error=%s",
                        delivery.competition_id,
                        mask_email(delivery.recipient_email),
                        exc,
                    )
                else:
                    self._state.mark_delivery_retry(delivery, now, str(exc))
                    LOGGER.warning(
                        "email retry scheduled competition=%s recipient=%s error=%s",
                        delivery.competition_id,
                        mask_email(delivery.recipient_email),
                        exc,
                    )
            else:
                self._state.mark_delivery_sent(delivery, self._clock())
                LOGGER.info(
                    "email sent competition=%s recipient=%s",
                    delivery.competition_id,
                    mask_email(delivery.recipient_email),
                )
