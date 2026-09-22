from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from ....core.db import DbSession, SqlBuilder
from ....core.db.DbEngine import DbEngine
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....domain.models import OllamaModelPull
from ....domain.models.OllamaModelPull import OllamaModelPullStatus


class OllamaModelPullRepository(BaseRepository[OllamaModelPull]):
    @staticmethod
    def model_cls() -> type[OllamaModelPull]:
        return OllamaModelPull

    @staticmethod
    def name() -> str:
        return "ollama_model_pull"

    def accept(self, model_name: str) -> tuple[OllamaModelPull, bool]:
        for _ in range(2):
            try:
                with DbSession.use(readonly=False) as db:
                    candidate = None
                    if DbEngine.get_main_engine().dialect.name == "postgresql":
                        candidate = OllamaModelPull(model_name=model_name)
                        candidate.id = SnowflakeID()
                        db.exec(
                            pg_insert(OllamaModelPull)
                            .values(
                                id=candidate.id,
                                created_at=candidate.created_at,
                                updated_at=candidate.created_at,
                                model_name=candidate.model_name,
                                status=candidate.status,
                                attempt=candidate.attempt,
                                percent=candidate.percent,
                            )
                            .on_conflict_do_nothing(index_elements=[OllamaModelPull.column("model_name")])
                        )
                    pull = db.exec(
                        SqlBuilder.select.table(OllamaModelPull)
                        .where(OllamaModelPull.column("model_name") == model_name)
                        .with_for_update()
                    ).first()
                    if pull is None:
                        pull = OllamaModelPull(model_name=model_name)
                        db.insert(pull)
                        return pull, True

                    if candidate is not None and pull.id == candidate.id:
                        return pull, True

                    if pull.status in {
                        OllamaModelPullStatus.Pending,
                        OllamaModelPullStatus.Queued,
                        OllamaModelPullStatus.Running,
                    }:
                        return pull, False

                    pull.status = OllamaModelPullStatus.Pending
                    pull.attempt += 1
                    pull.percent = 0.0
                    pull.status_text = None
                    pull.failure_reason = None
                    pull.claimed_at = None
                    db.update(pull)
                    return pull, True
            except IntegrityError:
                continue
        raise RuntimeError("Could not accept a concurrent Ollama model pull")

    def reserve_dispatch(self, pull_id: SnowflakeID, attempt: int) -> bool:
        now = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.update.table(OllamaModelPull)
                .values(
                    {
                        OllamaModelPull.column("status"): OllamaModelPullStatus.Queued,
                        OllamaModelPull.column("claimed_at"): now,
                        OllamaModelPull.column("updated_at"): now,
                    }
                )
                .where(
                    (OllamaModelPull.column("id") == pull_id)
                    & (OllamaModelPull.column("attempt") == attempt)
                    & (OllamaModelPull.column("status") == OllamaModelPullStatus.Pending)
                )
            ) == 1

    def release_dispatch(self, pull_id: SnowflakeID, attempt: int) -> bool:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.update.table(OllamaModelPull)
                .values(
                    {
                        OllamaModelPull.column("status"): OllamaModelPullStatus.Pending,
                        OllamaModelPull.column("claimed_at"): None,
                        OllamaModelPull.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (OllamaModelPull.column("id") == pull_id)
                    & (OllamaModelPull.column("attempt") == attempt)
                    & (OllamaModelPull.column("status") == OllamaModelPullStatus.Queued)
                )
            ) == 1

    def mark_stale_queued_pending(self, older_than: SafeDateTime, limit: int) -> int:
        with DbSession.use(readonly=False) as db:
            pulls = db.exec(
                SqlBuilder.select.table(OllamaModelPull)
                .where(
                    (OllamaModelPull.column("status") == OllamaModelPullStatus.Queued)
                    & (OllamaModelPull.column("claimed_at") < older_than)
                )
                .order_by(OllamaModelPull.column("claimed_at"), OllamaModelPull.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for pull in pulls:
                pull.status = OllamaModelPullStatus.Pending
                pull.claimed_at = None
                db.update(pull)
            return len(pulls)

    def claim(self, pull_id: SnowflakeID, attempt: int) -> bool:
        now = SafeDateTime.now()
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.update.table(OllamaModelPull)
                .values(
                    {
                        OllamaModelPull.column("status"): OllamaModelPullStatus.Running,
                        OllamaModelPull.column("claimed_at"): now,
                        OllamaModelPull.column("updated_at"): now,
                    }
                )
                .where(
                    (OllamaModelPull.column("id") == pull_id)
                    & (OllamaModelPull.column("attempt") == attempt)
                    & (OllamaModelPull.column("status") == OllamaModelPullStatus.Queued)
                )
            ) == 1

    def report(self, pull_id: SnowflakeID, attempt: int, percent: float, status_text: str | None) -> bool:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.update.table(OllamaModelPull)
                .values(
                    {
                        OllamaModelPull.column("percent"): percent,
                        OllamaModelPull.column("status_text"): status_text,
                        OllamaModelPull.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (OllamaModelPull.column("id") == pull_id)
                    & (OllamaModelPull.column("attempt") == attempt)
                    & (OllamaModelPull.column("status") == OllamaModelPullStatus.Running)
                )
            ) == 1

    def finish(self, pull_id: SnowflakeID, attempt: int, status: OllamaModelPullStatus, error: str | None = None) -> bool:
        if status not in {OllamaModelPullStatus.Success, OllamaModelPullStatus.Failed}:
            raise ValueError("A pull can only finish with success or failure")
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.update.table(OllamaModelPull)
                .values(
                    {
                        OllamaModelPull.column("status"): status,
                        OllamaModelPull.column("percent"): 100.0 if status == OllamaModelPullStatus.Success else 0.0,
                        OllamaModelPull.column("status_text"): status.value,
                        OllamaModelPull.column("failure_reason"): error[:1000] if error else None,
                        OllamaModelPull.column("updated_at"): SafeDateTime.now(),
                    }
                )
                .where(
                    (OllamaModelPull.column("id") == pull_id)
                    & (OllamaModelPull.column("attempt") == attempt)
                    & (OllamaModelPull.column("status") == OllamaModelPullStatus.Running)
                )
            ) == 1

    def get_by_id(self, pull_id: SnowflakeID) -> OllamaModelPull | None:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(OllamaModelPull).where(OllamaModelPull.column("id") == pull_id)
            ).first()

    def get_active(self, limit: int) -> list[OllamaModelPull]:
        with DbSession.use(readonly=False) as db:
            return db.exec(
                SqlBuilder.select.table(OllamaModelPull)
                .where(
                    OllamaModelPull.column("status").in_(
                        [OllamaModelPullStatus.Pending, OllamaModelPullStatus.Queued, OllamaModelPullStatus.Running]
                    )
                )
                .order_by(OllamaModelPull.column("created_at"), OllamaModelPull.column("id"))
                .limit(limit)
            ).all()

    def get_recent(self, limit: int) -> list[OllamaModelPull]:
        with DbSession.use(readonly=False) as db:
            active_statuses = [OllamaModelPullStatus.Pending, OllamaModelPullStatus.Queued, OllamaModelPullStatus.Running]
            active = db.exec(
                SqlBuilder.select.table(OllamaModelPull)
                .where(OllamaModelPull.column("status").in_(active_statuses))
                .order_by(OllamaModelPull.column("updated_at").desc(), OllamaModelPull.column("id").desc())
                .limit(limit)
            ).all()
            if len(active) >= limit:
                return active
            completed = db.exec(
                SqlBuilder.select.table(OllamaModelPull)
                .where(~OllamaModelPull.column("status").in_(active_statuses))
                .order_by(OllamaModelPull.column("updated_at").desc(), OllamaModelPull.column("id").desc())
                .limit(limit - len(active))
            ).all()
            return active + completed

    def mark_stale_uncertain(self, older_than: SafeDateTime, limit: int) -> list[OllamaModelPull]:
        with DbSession.use(readonly=False) as db:
            pulls = db.exec(
                SqlBuilder.select.table(OllamaModelPull)
                .where(
                    (OllamaModelPull.column("status") == OllamaModelPullStatus.Running)
                    & (OllamaModelPull.column("updated_at") < older_than)
                )
                .order_by(OllamaModelPull.column("updated_at"), OllamaModelPull.column("id"))
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for pull in pulls:
                pull.status = OllamaModelPullStatus.Uncertain
                pull.failure_reason = "Pull worker stopped reporting before a terminal Ollama result"
                db.update(pull)
            return pulls
