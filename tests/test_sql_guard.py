from dataclasses import replace

from agent.config import load_settings
from agent.safety.sql_guard import validate

settings = load_settings()


def test_drop_rejected():
    result = validate("DROP TABLE users", settings)
    assert not result.ok
    assert "SELECT" in result.error


def test_insert_rejected():
    result = validate("INSERT INTO orders VALUES (1)", settings)
    assert not result.ok


def test_multi_statement_rejected():
    result = validate("SELECT 1; DROP TABLE users", settings)
    assert not result.ok
    assert "one statement" in result.error


def test_unknown_table_rejected():
    result = validate("SELECT * FROM secrets", settings)
    assert not result.ok
    assert "secrets" in result.error


def test_information_schema_rejected():
    result = validate("SELECT * FROM `bigquery-public-data.thelook_ecommerce`.INFORMATION_SCHEMA.COLUMNS", settings)
    assert not result.ok


def test_foreign_dataset_rejected():
    result = validate("SELECT * FROM `bigquery-public-data.github_repos.commits`", settings)
    assert not result.ok


def test_bare_table_qualified_and_limited():
    result = validate("SELECT status FROM orders", settings)
    assert result.ok
    assert "bigquery-public-data" in result.sql
    assert "thelook_ecommerce" in result.sql
    assert "LIMIT" in result.sql


def test_qualified_table_accepted():
    result = validate("SELECT status FROM `bigquery-public-data.thelook_ecommerce.orders` LIMIT 5", settings)
    assert result.ok


def test_cte_alias_not_mistaken_for_table():
    result = validate("WITH recent AS (SELECT user_id FROM orders) SELECT COUNT(*) FROM recent", settings)
    assert result.ok


def test_existing_limit_preserved():
    result = validate("SELECT status FROM orders LIMIT 7", settings)
    assert result.ok
    assert "LIMIT 7" in result.sql


def test_dataset_qualifiers_follow_settings():
    other = replace(settings, bq_dataset="my-project.other_dataset")
    qualified = validate("SELECT status FROM orders", other)
    assert qualified.ok
    assert "my-project" in qualified.sql and "other_dataset" in qualified.sql
    # and the default dataset is now rejected under the changed config
    rejected = validate("SELECT status FROM `bigquery-public-data.thelook_ecommerce.orders`", other)
    assert not rejected.ok
