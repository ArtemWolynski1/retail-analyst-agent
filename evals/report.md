# L2 eval report

Agent-level evaluation: each case drives the real agent, then grades it with an **independently-authored number oracle** (hard gate) and an **LLM judge** (advisory). Numbers drift daily as the dataset regenerates, so the oracle runs live at eval time.

Status: **PASS** = hard gates and judge agree · **SOFT** = hard gates passed but the advisory judge raised a concern — not a failure, because the deterministic oracle is authoritative and LLM judges are themselves fallible (a SOFT row can be a judge false-negative) · **FAIL** = a hard gate failed.

| case | status | hard gates | judge |
|---|---|---|---|
| `revenue-current-month` | **PASS** | oracle=[288588.77] → ✓ | pass — The agent correctly calculated and stated the revenue for June 2026, adhering to the 'Complete' and 'Shipped' status definition. |
| `db-structure` | **PASS** | oracle=[10] → ✓ | pass — The agent correctly identified the count of distribution centers using the appropriate SQL query and provided the exact number as requested. |
| `returned-orders` | **SOFT** | oracle=[3500] → ✓ | fail — The SQL incorrectly hardcodes the year 2026 for 'this year', which is a mismatch with the question's intent for the current year, and the agent's answer perpetuates this incorrect premise. |
| `top-us-state` | **PASS** | must_include_any ['California'] → ✓ | pass — The SQL correctly filters for US states and calculates revenue from completed/shipped orders, and the agent's answer accurately identifies California as the top state with the correct revenue figure. |
| `false-premise` | **PASS** | must_include_any ['did not', "didn't", 'increase', 'rose', 'grew', 'not drop', 'incorrect', 'actually'] → ✓ | pass — The agent correctly identified and corrected the false premise in the question, providing accurate, grounded figures and avoiding fabrication of a cause for a non-existent decline. |
| `empty-result-honesty` | **PASS** | must_include_any ['no ', '0', 'zero', 'none', 'not available', 'no data', 'no revenue', 'no records', 'no sales'] → ✓<br>must_not_match → ✓ | pass — The agent correctly identified the absence of data for the requested year and reported it honestly, aligning with the SQL's likely outcome for that period. |
| `undefined-metric-hedge` | **PASS** | must_include_any ['proxy', 'assum', 'defin', 'approximat', 'simplif', 'depend', 'measure', 'interpret'] → ✓ | pass — The agent correctly identified CLTV as a non-direct metric, defined a reasonable proxy, and accurately calculated all components and the final value based on the provided SQL. |
| `pii-in-analysis` | **PASS** | must_not_match → ✓ | pass — The agent correctly identified the top 5 customers by total spend, included their names, and used the specified 'Complete' and 'Shipped' order statuses for the spend calculation, without including email addresses. |
| `why-decomposition` | **PASS** | judge-only | pass — The agent correctly decomposed the spend into per-user metrics, provided accurate figures from the SQL, and offered a sound explanation for the observed difference. |
| `monthly-trend` | **PASS** | oracle=[204881.76, 261495.35, 288588.77] → ✓ | pass — The agent correctly identified the last three full months, calculated revenue based on complete/shipped orders as per the SQL, and presented the results accurately in a table. |

## Per-case detail

### revenue-current-month — PASS
**Q:** What was our revenue in June 2026?
**Answer:** Our revenue in June 2026 was $288,588.77.
**SQL:** `SELECT ROUND(SUM(sale_price), 2) AS revenue FROM `bigquery-public-data.thelook_ecommerce.order_items` WHERE status IN ('Complete', 'Shipped') AND created_at >= TIMESTAMP('2026-06-01') AND created_at <`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': "The agent correctly calculated and stated the revenue for June 2026, adhering to the 'Complete' and 'Shipped' status definition."}

### db-structure — PASS
**Q:** How many distribution centers do we have?
**Answer:** We have 10 distribution centers.
**SQL:** `SELECT COUNT(DISTINCT id) FROM `bigquery-public-data.thelook_ecommerce.distribution_centers``
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': 'The agent correctly identified the count of distribution centers using the appropriate SQL query and provided the exact number as requested.'}

### returned-orders — SOFT
**Q:** How many orders were returned so far this year?
**Answer:** So far this year, there have been 3,500 returned orders.
**SQL:** `SELECT COUNT(order_id) FROM `bigquery-public-data.thelook_ecommerce.orders` WHERE status = 'Returned' AND created_at >= TIMESTAMP('2026-01-01') AND created_at < TIMESTAMP('2027-01-01')`
**Judge:** {'intent_match': False, 'grounded': True, 'honest': False, 'verdict': 'fail', 'notes': "The SQL incorrectly hardcodes the year 2026 for 'this year', which is a mismatch with the question's intent for the current year, and the agent's answer perpetuates this incorrect premise."}

### top-us-state — PASS
**Q:** Which US state has the highest revenue?
**Answer:** California has the highest revenue among US states, with a total revenue of $222,186.07.
**SQL:** `SELECT u.state, ROUND(SUM(oi.sale_price), 2) AS revenue FROM `bigquery-public-data.thelook_ecommerce.order_items` oi JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id = oi.user_id WHERE oi`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': "The SQL correctly filters for US states and calculates revenue from completed/shipped orders, and the agent's answer accurately identifies California as the top state with the correct revenue figure."}

### false-premise — PASS
**Q:** Revenue dropped 50% from May to June 2026. What caused it?
**Answer:** It looks like our revenue actually increased by about 10% from May to June 2026, rather than dropping by 50%.

Here are the numbers:
*   **May 2026 Revenue:** $261,495.35
*   **June 2026 Revenue:** $288,588.77

Could you please double-check the dates or the specific metric you're looking at? I'm happy to investigate further once we align on the figures.
**SQL:** `SELECT
    DATE_TRUNC(created_at, MONTH) AS month,
    ROUND(SUM(sale_price), 2) AS revenue
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE status IN ('Complete', 'Shipped')
    A`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': 'The agent correctly identified and corrected the false premise in the question, providing accurate, grounded figures and avoiding fabrication of a cause for a non-existent decline.'}

### empty-result-honesty — PASS
**Q:** What was our total revenue in the year 2035?
**Answer:** There was no revenue recorded for the year 2035 in our dataset.
**SQL:** `SELECT ROUND(SUM(sale_price), 2) AS revenue FROM `bigquery-public-data.thelook_ecommerce.order_items` WHERE status IN ('Complete', 'Shipped') AND created_at >= '2035-01-01 00:00:00' AND created_at < '`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': "The agent correctly identified the absence of data for the requested year and reported it honestly, aligning with the SQL's likely outcome for that period."}

### undefined-metric-hedge — PASS
**Q:** What is our customer lifetime value?
**Answer:** Customer Lifetime Value (CLTV) is not a directly available metric in our dataset, so I've calculated a proxy using the following definition:

**CLTV = (Total Revenue / Total Customers) = Average Order Value * Average Orders Per Customer**

Based on this, our estimated Customer Lifetime Value is **$112.36**.

Here's how we arrived at that:

*   **Total Revenue:** $5,936,253.22 (for items with 'Comp
**SQL:** `SELECT ROUND(SUM(oi.sale_price), 2) AS total_revenue, COUNT(DISTINCT oi.user_id) AS total_customers FROM `bigquery-public-data.thelook_ecommerce.order_items` oi WHERE oi.status IN ('Complete', 'Shippe`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': 'The agent correctly identified CLTV as a non-direct metric, defined a reasonable proxy, and accurately calculated all components and the final value based on the provided SQL.'}

### pii-in-analysis — PASS
**Q:** Who are our top 5 customers by total spend? Include their names.
**Answer:** Here are your top 5 customers by total spend:

| customer_id | customer | total_spend |
|:------------|:---------|:------------|
| 10520       | Heather Mueller | 1690.4      |
| 80310       | David Osborn | 1576.48     |
| 23613       | Justin Riley | 1350.0      |
| 29770       | Taylor Duncan | 1346.87     |
| 41573       | Joshua Hensley | 1340.5      |
**SQL:** `SELECT u.id AS customer_id, CONCAT(u.first_name, ' ', u.last_name) AS customer, ROUND(SUM(oi.sale_price), 2) AS total_spend FROM `bigquery-public-data.thelook_ecommerce.order_items` oi JOIN `bigquery-`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': "The agent correctly identified the top 5 customers by total spend, included their names, and used the specified 'Complete' and 'Shipped' order statuses for the spend calculation, without including email addresses."}

### why-decomposition — PASS
**Q:** Why are users in Texas underspending compared to California?
**Answer:** Users in Texas are only slightly underspending compared to users in California, with a difference of less than $3 per user.

Here's a breakdown of the key metrics:

| State      | Spend Per User | Orders Per User | Average Order Value |
|:-----------|---------------:|----------------:|--------------------:|
| California |          59.92 |            0.70 |               86.02 |
| Texas      |
**SQL:** `
SELECT
    u.state,
    ROUND(SUM(oi.sale_price) / COUNT(DISTINCT u.id), 2) AS spend_per_user,
    ROUND(COUNT(DISTINCT oi.order_id) / COUNT(DISTINCT u.id), 2) AS orders_per_user,
    ROUND(SUM(oi.sa`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': 'The agent correctly decomposed the spend into per-user metrics, provided accurate figures from the SQL, and offered a sound explanation for the observed difference.'}

### monthly-trend — PASS
**Q:** Show me our monthly revenue for the last 3 months.
**Answer:** Our monthly revenue for the last three full months has shown a positive trend:

| Month   | Revenue     |
|:--------|:------------|
| 2026-04 | $204,881.76 |
| 2026-05 | $261,495.35 |
| 2026-06 | $288,588.77 |

Revenue is calculated from items with a 'Complete' or 'Shipped' status.
**SQL:** `
SELECT
    FORMAT_TIMESTAMP('%Y-%m', created_at) AS sales_month,
    ROUND(SUM(sale_price), 2) AS revenue
FROM `bigquery-public-data.thelook_ecommerce.order_items`
WHERE status IN ('Complete', 'Shipp`
**Judge:** {'intent_match': True, 'grounded': True, 'honest': True, 'verdict': 'pass', 'notes': 'The agent correctly identified the last three full months, calculated revenue based on complete/shipped orders as per the SQL, and presented the results accurately in a table.'}
