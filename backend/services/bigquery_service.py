"""BigQuery service — violation analytics, trend queries, risk scoring."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from google.cloud import bigquery

from core.config import get_settings
from models.schemas import Violation

logger = logging.getLogger(__name__)
settings = get_settings()


# BigQuery table schema
VIOLATIONS_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("session_id", "STRING"),
    bigquery.SchemaField("camera_id", "STRING"),
    bigquery.SchemaField("site_id", "STRING"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("violation_type", "STRING"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("osha_code", "STRING"),
    bigquery.SchemaField("severity", "STRING"),
    bigquery.SchemaField("remediation", "STRING"),
    bigquery.SchemaField("confidence", "FLOAT"),
    bigquery.SchemaField("evidence_image_url", "STRING"),
    bigquery.SchemaField("annotated_image_url", "STRING"),
]


class BigQueryService:
    def __init__(self):
        self.client = bigquery.Client(project=settings.gcp_project_id)
        self.dataset_id = f"{settings.gcp_project_id}.{settings.bigquery_dataset}"
        self.violations_table = f"{self.dataset_id}.{settings.bigquery_table_violations}"

    def ensure_dataset_and_tables(self) -> None:
        """Create dataset and tables if they don't exist (called on startup)."""
        try:
            dataset = bigquery.Dataset(self.dataset_id)
            dataset.location = settings.gcp_region
            self.client.create_dataset(dataset, exists_ok=True)

            table = bigquery.Table(self.violations_table, schema=VIOLATIONS_SCHEMA)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="timestamp",
            )
            self.client.create_table(table, exists_ok=True)

            # Update schema to add any new fields (e.g. annotated_image_url)
            try:
                existing = self.client.get_table(self.violations_table)
                existing_fields = {f.name for f in existing.schema}
                new_fields = [f for f in VIOLATIONS_SCHEMA if f.name not in existing_fields]
                if new_fields:
                    updated_schema = list(existing.schema) + new_fields
                    existing.schema = updated_schema
                    self.client.update_table(existing, ["schema"])
                    logger.info(f"BigQuery schema updated with new fields: {[f.name for f in new_fields]}")
            except Exception as e:
                logger.warning(f"BigQuery schema update skipped: {e}")

            logger.info("BigQuery dataset and tables verified.")
        except Exception as e:
            logger.error(f"BigQuery setup error: {e}")

    async def log_violation(self, violation: Violation) -> None:
        """Insert a violation event into BigQuery for analytics."""
        row = {
            "id": violation.id,
            "session_id": violation.session_id,
            "camera_id": violation.camera_id,
            "site_id": violation.site_id,
            "timestamp": violation.timestamp.isoformat(),
            "violation_type": violation.violation_type,
            "description": violation.description,
            "osha_code": violation.osha_code,
            "severity": violation.severity,
            "remediation": violation.remediation,
            "confidence": violation.confidence,
            "evidence_image_url": violation.evidence_image_url or "",
            "annotated_image_url": violation.annotated_image_url or "",
        }
        errors = self.client.insert_rows_json(self.violations_table, [row])
        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
        else:
            logger.debug(f"Violation logged to BigQuery: {violation.id}")

    async def get_violations_summary(
        self, site_id: str, days: int = 30
    ) -> dict[str, Any]:
        """Aggregate violation summary for analytics dashboard."""
        query = f"""
        SELECT
            DATE(timestamp) as date,
            severity,
            violation_type,
            COUNT(*) as count
        FROM `{self.violations_table}`
        WHERE
            site_id = @site_id
            AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY 1, 2, 3
        ORDER BY 1 DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_id", "STRING", site_id)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        rows = [dict(row) for row in result]

        # Aggregate counts
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}
        trend: dict[str, int] = {}

        for row in rows:
            s = row["severity"]
            t = row["violation_type"]
            d = str(row["date"])
            c = row["count"]
            by_severity[s] = by_severity.get(s, 0) + c
            by_category[t] = by_category.get(t, 0) + c
            trend[d] = trend.get(d, 0) + c

        total = sum(by_severity.values())
        compliance_score = max(0, 100 - min(total * 2, 100))

        return {
            "total_violations": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "compliance_trend": [
                {"date": d, "violations": c} for d, c in sorted(trend.items())
            ],
            "compliance_score": compliance_score,
            "period_days": days,
        }

    async def get_site_risk_score(self, site_id: str) -> float:
        """Calculate a 0-100 risk score based on recent violations."""
        query = f"""
        SELECT
            SUM(CASE severity WHEN 'critical' THEN 10
                              WHEN 'high'     THEN 5
                              WHEN 'medium'   THEN 2
                              ELSE 1 END) AS weighted_score
        FROM `{self.violations_table}`
        WHERE
            site_id = @site_id
            AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_id", "STRING", site_id)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        rows = list(result)
        weighted = rows[0]["weighted_score"] if rows and rows[0]["weighted_score"] else 0
        return min(float(weighted), 100.0)

    async def get_top_violations(
        self, site_id: str, limit: int = 10, days: int = 30
    ) -> list[dict[str, Any]]:
        query = f"""
        SELECT osha_code, violation_type, COUNT(*) as count, severity
        FROM `{self.violations_table}`
        WHERE site_id = @site_id
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY osha_code, violation_type, severity
        ORDER BY count DESC
        LIMIT {limit}
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_id", "STRING", site_id)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        return [dict(row) for row in result]

    async def get_violations_count_today(self, site_id: str) -> int:
        query = f"""
        SELECT COUNT(*) as count
        FROM `{self.violations_table}`
        WHERE site_id = @site_id
          AND DATE(timestamp) = CURRENT_DATE()
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_id", "STRING", site_id)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        rows = list(result)
        return int(rows[0]["count"]) if rows else 0
