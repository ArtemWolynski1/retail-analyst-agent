from google.cloud import bigquery

from agent.config import Settings


def make_client(settings: Settings) -> bigquery.Client:
    return bigquery.Client(project=settings.gcp_project)


def dry_run(client: bigquery.Client, sql: str) -> int:
    """Validates syntax and permissions at zero cost; returns bytes the query would scan."""
    config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    return client.query(sql, job_config=config).total_bytes_processed


def run_query(
    client: bigquery.Client, sql: str, settings: Settings, timeout_s: int = 30
) -> list[bigquery.Row]:
    config = bigquery.QueryJobConfig(maximum_bytes_billed=settings.max_bytes_billed)
    job = client.query(sql, job_config=config)
    return list(job.result(timeout=timeout_s))
